"""朝の文書の自動下書き: 答え合わせ → ジャグラー候補 → 予測文書（ホールごと）。

07:00 の ana-slo 取得後と、07:30 の再取得後の2回、このスクリプトを起動する。
前日分が DB に入ったホールだけを処理し、処理済みの段は印(.done)を残して飛ばす。
07:00 に揃わなかったホールは 07:30 の起動で処理される（取り直しが間に合わなければ翌日以降）。

順序の理由: 予測は前日の結果を参照したいので、ホールごとに
  1. answercheck  前日の答え合わせ（claude -p）
  2. juggler      ジャグラー候補（backtest.juggler_carryover tomorrow、機械実行）
  3. prediction   当日の予測（claude -p。1と2の出力を入力にする）
の順で進める。

やらないこと（人が確認してから行う）:
  - 予測の凍結（backtest.prediction_ledger freeze-doc）。誤読した予告がそのまま採点台帳に入るため。
  - 予告の登録（backtest.announce register）、git のコミット。
  - 予告の機械採点は run_morning.py の担当。07:00 に全ホールが揃わなかった日は
    答え合わせ時点で未採点のことがあり、claude には DB から直接照合させる。

出力:
  output/morning_docs/<当日>/<ホール>.{answercheck,juggler,prediction}.md と .done
  document/reviews/<前日>-answercheck.md、document/reviews/<当日>-prediction.md
    （既存の人手の文書は上書きしない。自動下書きの印があるものだけ作り直す。
      予測は凍結済みなら触らない）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from run_morning import hall_max_dates  # 同ディレクトリ
from runlock import acquire_or_exit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(PROJECT_ROOT / "venv" / "Scripts" / "python.exe")
JST = ZoneInfo("Asia/Tokyo")
OUT_ROOT = PROJECT_ROOT / "output" / "morning_docs"
REVIEWS = PROJECT_ROOT / "document" / "reviews"
PREDICTIONS = PROJECT_ROOT / "backtest" / "predictions"
AUTO_MARK = "<!-- auto-morning-docs -->"
CLAUDE_TIMEOUT_SEC = 25 * 60
CONCURRENCY = 3  # claude -p を同時に走らせるホール数（逐次だと10ホールで1時間近くかかる）

# backtest.prediction_ledger.HALL_KEY と同じ対応。表示名は文書の見出しに使う（freeze-doc が拾う）。
HALLS = {
    "kamata7": ("マルハンメガシティ2000-蒲田7", "蒲田7"),
    "kamata1": ("マルハンメガシティ2000-蒲田1", "蒲田1"),
    "rakuen": ("楽園蒲田店", "楽園"),
    "heiwajima": ("レイトギャップ平和島", "平和島"),
    "mitoya": ("みとや大森町店", "みとや"),
    "kinji_higashiguchi": ("金時蒲田東口店", "金時東口"),
    "kinji_keikyu": ("金時京急蒲田店", "金時京急"),
    "hiroki_higashiguchi": ("ヒロキ東口店", "ヒロキ東口"),
    "arrow": ("ARROW池上店", "ARROW"),
    "zassiki": ("ザ-シティ-ベルシティ雑色店", "雑色"),
}
# CLAUDE.md: 設定5以上の割合が高いホールは予告の有無にかかわらず候補を出す。
# 蒲田1は予告にジャグラー強化がある日だけ。機械実行は安いので表は作り、採否は予測段で決める。
JUGGLER_HALLS = {"kamata7", "rakuen", "mitoya", "kamata1"}
JUGGLER_LOW_NOTE = "ジャグラーの設定5以上の割合が低く、候補を出さない。"


def find_claude() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for name in ("claude.exe", "claude.cmd", "claude"):
        path = Path.home() / ".local" / "bin" / name
        if path.exists():
            return str(path)
    raise FileNotFoundError("claude CLI が見つからない")


def run_claude(prompt: str, label: str) -> bool:
    print("  [claude] %s" % label, flush=True)
    env = dict(os.environ, ECC_GATEGUARD="off", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        result = subprocess.run(
            [
                find_claude(),
                "-p",
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                "Bash",
            ],
            input=prompt,
            text=True,
            encoding="utf-8",
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            env=env,
            timeout=CLAUDE_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print("    失敗: %s" % exc, flush=True)
        return False
    for line in (result.stdout or "").strip().splitlines()[-3:]:
        print("    | %s" % line, flush=True)
    if result.returncode != 0:
        print("    失敗: 終了コード %d %s" % (result.returncode, (result.stderr or "").strip()[-300:]), flush=True)
    return result.returncode == 0


COMMON_RULES = """\
## 守ること（自動実行のため）
- 書いてよいのは指定した出力ファイル1つだけ。それ以外のファイル（台帳・予告JSON・設定・文書）は変更しない。
- git のコミット・プッシュ、`backtest.announce register/amend`、`backtest.prediction_ledger freeze-doc`、スクレイピングは実行しない。
- Pythonは `venv\\Scripts\\python.exe` を使う。出力は日本語。数字は実測で、推測を事実のように書かない。
- 迎合しない（CLAUDE.md）。根拠の薄いものは薄いと書く。確度は全体に低〜中程度のはず。
- 出力ファイルの先頭行は `## {display}` の見出しにする（後で全ホールを連結する）。
"""


def answercheck_prompt(key: str, yesterday: str, today: str, out: Path) -> str:
    hall, display = HALLS[key]
    ydash = "%s-%s-%s" % (yesterday[:4], yesterday[4:6], yesterday[6:])
    return f"""\
{display}（DB名: {hall}）の{yesterday}分の答え合わせを書いてください。出力先: {out}

## 手順
1. `document/reviews/` の直近の `*-answercheck.md` のうち{display}の節を1つ読み、体裁と深さを合わせる。
2. 前日の予測があれば `backtest/predictions/{yesterday}__{key}.json` と `document/reviews/{ydash}-prediction.md` の{display}の節、
   予告があれば `backtest/announce/{key}__{yesterday}*.json`（撤回済み `.withdrawn.json` と差し替え前は除く）を読む。
3. `/hall-analysis-checklist`、`/prediction-evaluation` の方針に従い、DBの実測と突き合わせる。
   差枚だけで的中/不成立と結論しない。機種はG比×平均差枚、台単位はRB確率を自己ベースラインと比べる。
   末尾・角番・並び・個別RBも見る。予告の機械採点（announce の result）が空でも、DBから直接照合してよい。
4. 予測が外れた・当たった理由、翌日以降に使える学びを短く書く。予測が無かった日は、実際に強かった機種・台・並びを書く。
5. 最後に1節「今日（{today}）の予測への示唆」を設け、箇条書き3点以内で書く。予測担当がこれを読む。

{COMMON_RULES.format(display=display)}"""


def prediction_prompt(key: str, today: str, answer: Path, juggler: Path, out: Path) -> str:
    hall, display = HALLS[key]
    return f"""\
{display}（DB名: {hall}）の{today}の予測を書いてください。出力先: {out}

## 入力
- 前日の答え合わせ: {answer}（末尾の「予測への示唆」も読む）
- ジャグラー候補: {juggler}
- 当日の予告: `backtest/announce/{key}__{today}*.json`（あれば。撤回済みは除く）と、
  `venv\\Scripts\\python.exe -m backtest.event_days check` 等で当日のイベント日台帳（document/registry/EVENT_DAYS.jsonl）を確認する。
  X の収集結果（scraper/twitter_monitor）に当日分の未登録の予告があれば読む。登録はしない。
- 体裁の手本: `document/reviews/` の直近の `*-prediction.md` の{display}の節。**この体裁を厳守**する。
  `backtest.prediction_ledger freeze-doc` が機械的に抜くのは次の3か所だけなので、書式を崩さない:
  推す機種は「判断:」の行、避ける機種は「避ける」を含む行、ジャグラーは「ジャグラー候補」の表。

## 方針
- CLAUDE.md「予測にはジャグラー候補を必ず含める」に従う。蒲田7・楽園・みとやは候補表を入れる。蒲田1は当日の予告にジャグラー強化がある日だけ入れる。
  それ以外のホールは表を出さず、「{JUGGLER_LOW_NOTE}」と一行書く。
- 予告があるホールは機種・列の予測＋ジャグラー候補、予告がないホールはジャグラー候補のみでよい。
- 予告の台番号・機種名・条件は原文どおりに。解釈が割れるものは「解釈が割れる」と書き、判断にしない。
- 推す根拠の数字（直近3か月、同条件の過去回の実績、母数）を添える。母数が小さければそう書く。

{COMMON_RULES.format(display=display)}"""


def run_juggler(key: str, out: Path) -> bool:
    hall, display = HALLS[key]
    if key not in JUGGLER_HALLS:
        out.write_text("## %s\n\n%s\n" % (display, JUGGLER_LOW_NOTE), encoding="utf-8")
        return True
    result = subprocess.run(
        [PYTHON, "-X", "utf8", "-m", "backtest.juggler_carryover", "tomorrow", "--hall", hall, "--top", "10"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print("    失敗: %s" % (result.stderr or "").strip()[-300:], flush=True)
        return False
    out.write_text(
        "## %s ジャグラー候補（機械出力）\n\n```\n%s\n```\n" % (display, result.stdout.strip()), encoding="utf-8"
    )
    return True


def is_auto_doc(path: Path) -> bool:
    return (not path.exists()) or AUTO_MARK in path.read_text(encoding="utf-8")[:400]


def dash(day: str) -> str:
    return "%s-%s-%s" % (day[:4], day[4:6], day[6:])


def merge(day_dir: Path, today: str, yesterday: str) -> None:
    """ホール別の断片を連結して document/reviews へ書く。人手の文書・凍結済みの文書は触らない。"""

    def pieces(stage: str) -> tuple[list[str], list[str]]:
        got, missing = [], []
        for key, (_, display) in HALLS.items():
            part = day_dir / ("%s.%s.md" % (key, stage))
            if (day_dir / ("%s.%s.done" % (key, stage))).exists() and part.exists():
                got.append(part.read_text(encoding="utf-8").strip())
            else:
                missing.append(display)
        return got, missing

    stamp = datetime.now(JST).strftime("%H:%M")

    got, missing = pieces("answercheck")
    if got:
        path = REVIEWS / ("%s-answercheck.md" % dash(yesterday))
        if not is_auto_doc(path):
            path = REVIEWS / ("%s-answercheck-auto.md" % dash(yesterday))
        head = "# %s 答え合わせ（自動下書き）\n\n%s %s 作成。未確認の下書き。" % (dash(yesterday), AUTO_MARK, stamp)
        if missing:
            head += "未生成: %s" % "・".join(missing)
        path.write_text(head + "\n\n" + "\n\n".join(got) + "\n", encoding="utf-8")
        print("書き出し: %s" % path.relative_to(PROJECT_ROOT), flush=True)

    got, missing = pieces("prediction")
    if got:
        path = REVIEWS / ("%s-prediction.md" % dash(today))
        if any(PREDICTIONS.glob("%s__*.json" % today)):
            print("予測は凍結済みのため文書を作り直さない。", flush=True)
            return
        if not is_auto_doc(path):
            print("人手の予測文書があるため上書きしない: %s" % path.name, flush=True)
            return
        head = (
            "# %s 予測（自動下書き・未凍結）\n\n%s %s 作成。人が読んで直してから凍結する:\n"
            "`venv\\Scripts\\python.exe -m backtest.prediction_ledger freeze-doc document/reviews/%s-prediction.md`"
            % (dash(today), AUTO_MARK, stamp, dash(today))
        )
        if missing:
            head += "\n未生成: %s（07:30 の起動で作る）" % "・".join(missing)
        path.write_text(head + "\n\n" + "\n\n".join(got) + "\n", encoding="utf-8")
        print("書き出し: %s" % path.relative_to(PROJECT_ROOT), flush=True)


def process_hall(key: str, day_dir: Path, yesterday: str, today: str, dry_run: bool) -> None:
    def done(stage: str) -> Path:
        return day_dir / ("%s.%s.done" % (key, stage))

    def part(stage: str) -> Path:
        return day_dir / ("%s.%s.md" % (key, stage))

    stages = [
        (
            "answercheck",
            lambda: run_claude(answercheck_prompt(key, yesterday, today, part("answercheck")), "%s 答え合わせ" % key),
        ),
        ("juggler", lambda: run_juggler(key, part("juggler"))),
        (
            "prediction",
            lambda: run_claude(
                prediction_prompt(key, today, part("answercheck"), part("juggler"), part("prediction")), "%s 予測" % key
            ),
        ),
    ]
    for stage, action in stages:
        if done(stage).exists():
            continue
        print("- %s / %s" % (key, stage), flush=True)
        if dry_run:
            continue
        if part(stage).exists():
            part(stage).unlink()  # 前回の失敗の残りを入力にしない
        if not (action() and part(stage).exists()):
            print("  → 失敗。この段で止める（後続の起動で再試行）", flush=True)
            return
        done(stage).write_text(datetime.now(JST).isoformat(), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--halls", nargs="*", choices=sorted(HALLS), help="対象ホール（省略時は前日分が揃った全ホール）"
    )
    parser.add_argument("--date", help="当日 YYYYMMDD（省略時は今日）")
    parser.add_argument("--dry-run", action="store_true", help="対象と段だけ表示し、claude も書き込みもしない")
    parser.add_argument("--force", action="store_true", help="完了印を無視して作り直す")
    args = parser.parse_args()

    lock = acquire_or_exit("morning_docs")
    try:
        today = args.date or datetime.now(JST).strftime("%Y%m%d")
        yesterday = (datetime.strptime(today, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        day_dir = OUT_ROOT / today
        if not args.dry_run:
            day_dir.mkdir(parents=True, exist_ok=True)
            if args.force:
                for stale in day_dir.glob("*.done"):
                    if not args.halls or stale.name.split(".")[0] in args.halls:
                        stale.unlink()

        print("朝の文書 当日=%s 前日=%s" % (today, yesterday), flush=True)
        handled: set[str] = set()
        while True:
            # 処理中に別の起動（run_morning.py）が前日分を取り込むことがあるので、1周ごとに見直す。
            maxes = hall_max_dates()
            targets, waiting = [], []
            for key in args.halls or HALLS:
                if key in handled:
                    continue
                if maxes.get(HALLS[key][0], "") >= yesterday:
                    targets.append(key)
                else:
                    waiting.append("%s(DB最終 %s)" % (key, maxes.get(HALLS[key][0], "なし")))
            print("対象: %s" % (", ".join(targets) or "なし"), flush=True)
            if waiting:
                print("前日分が未取り込みで待ち: %s" % ", ".join(waiting), flush=True)
            if not targets:
                break
            handled.update(targets)
            with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
                list(pool.map(lambda k: process_hall(k, day_dir, yesterday, today, args.dry_run), targets))
            if not args.dry_run:
                merge(day_dir, today, yesterday)
            if args.dry_run:
                break
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
