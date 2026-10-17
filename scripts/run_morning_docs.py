"""朝の文書の自動下書き: 答え合わせ → ジャグラー候補 → 予測文書（ホールごと）。

07:00 の ana-slo 取得後と、07:30 の再取得後の2回、このスクリプトを起動する。
前日分が DB に入ったホールだけを処理し、処理済みの段は印(.done)を残して飛ばす。
07:00 に揃わなかったホールは 07:30 の起動で処理される（取り直しが間に合わなければ翌日以降）。

順序の理由: 予測は前日の結果を参照したいので、ホールごとに
  1. answercheck  前日の答え合わせ（claude -p）
  2. juggler      ジャグラー候補（backtest.juggler_carryover tomorrow、機械実行）
  3. prediction   当日の予測（claude -p。1と2の出力を入力にする）
の順で進める。

claude に推測させないこと（2026-10-18 の初回で、曜日を間違える・DBがあるのに
「未取り込み」「参照不可」と書く出力が出たため）:
  - 日付・曜日・DB最終日・予告ファイルの一覧はスクリプトが計算してプロンプトに渡す。
  - 出力は検証し、不合格なら理由を添えて1回だけ書き直させる。それでも不合格なら
    .done を付けず .rejected.md に退避する（連結しない。次の起動で再試行）。
  - ジャグラー候補表は claude に書かせず、機械出力から全ホール共通の1節を組み立てる
    （backtest.prediction_ledger が「## ジャグラー候補」の表だけを拾うため）。

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
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
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
ANNOUNCE_DIR = PROJECT_ROOT / "backtest" / "announce"
AUTO_MARK = "<!-- auto-morning-docs -->"
CLAUDE_TIMEOUT_SEC = 25 * 60
CONCURRENCY = 5  # claude -p を同時に走らせるホール数（逐次だと10ホールで1時間近くかかる）
WEEKDAYS = "月火水木金土日"

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
# 予告ファイル名の頭は、ledger のキーと違うホールがある。
ANNOUNCE_PREFIX = {"hiroki_higashiguchi": "hiroki"}
# CLAUDE.md: 設定5以上の割合が高いホールは予告の有無にかかわらず候補を出す。
# 蒲田1は予告にジャグラー強化がある日だけ。機械実行は安いので表の元データは作り、載せるかは merge で決める。
JUGGLER_HALLS = {"kamata7", "rakuen", "mitoya", "kamata1"}
# 全ホール共通の「ジャグラー候補」表の1列目。prediction_ledger.hall_of が当てられる呼び名にする。
JUGGLER_LABEL = {"kamata7": "蒲田7", "rakuen": "楽園蒲田店", "mitoya": "みとや大森町店", "kamata1": "蒲田1"}
JUGGLER_LOW_NOTE = "ジャグラーの設定5以上の割合が低く、候補を出さない。"

# 分析できなかったと言い訳する出力は、DBが実在する以上は不合格にする。
BAD_PHRASES = re.compile(
    r"参照(不可|できな|が限定)|未取り込み|未取得|初期化|取得済みですか|ご確認ください|ユーザーへの確認"
    r"|データが(取得|参照)できな|DB(が|は)(空|存在しない|ない)"
)


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


# ---------------------------------------------------------------- 事実の計算と出力の検証


def jp_date(day: str) -> str:
    d = datetime.strptime(day, "%Y%m%d")
    return "%d-%02d-%02d(%s)" % (d.year, d.month, d.day, WEEKDAYS[d.weekday()])


def announce_files(key: str, day: str) -> list[Path]:
    """当日の予告ファイル。撤回済みは除く。"""
    prefix = ANNOUNCE_PREFIX.get(key, key)
    return sorted(p for p in ANNOUNCE_DIR.glob("%s__%s__*.json" % (prefix, day)) if ".withdrawn" not in p.name)


def facts_block(key: str, today: str, yesterday: str) -> str:
    hall, display = HALLS[key]
    latest = hall_max_dates().get(hall, "なし")
    announces = announce_files(key, today)
    listing = "\n".join("  - backtest/announce/%s" % p.name for p in announces) or "  - なし（予告は登録されていない）"
    return f"""\
## 確定している事実（スクリプトが計算した。これと矛盾することを書かない）
- 当日: {jp_date(today)} / 前日: {jp_date(yesterday)}。曜日はこれを使う。自分で数えない。
- {display}のDBは `db/{hall}.db`。`machine_detailed_results` の最終日は {latest}。前日分は入っている。
  「DBが空・未初期化・未取り込み・参照不可」と書いてはいけない。実際に sqlite3 で問い合わせて確かめる
  （スキーマは database/CLAUDE.md。date は YYYYMMDD の文字列、台番号は machine_number）。
- 当日の予告ファイル:
{listing}
- 予告に「狙い目はリプにぶら下げる」とあるときの機種・台番号は、予告の本文ではなく投稿者の自分への返信にある。
  `scraper/twitter_monitor/state.db` の `self_replies`（tweet_id, handle, tweet_text, posted_at_jst, image_paths）に集めてある。
  予告を出したアカウントの、予告より後の返信を読む（画像は image_paths の画像ファイル）。
  返信が見つからなければ「狙い目の返信はまだ収集できていない」と事実として書き、機種を創作しない。
"""


def weekday_errors(text: str, day: str) -> list[str]:
    d = datetime.strptime(day, "%Y%m%d")
    want = WEEKDAYS[d.weekday()]
    patterns = [
        r"%d/%d\s*[（(]\s*([%s])" % (d.month, d.day, WEEKDAYS),
        r"%d-%02d-%02d\s*[（(]\s*([%s])" % (d.year, d.month, d.day, WEEKDAYS),
        r"%d月%d日\s*[（(]\s*([%s])" % (d.month, d.day, WEEKDAYS),
    ]
    errors = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            if m.group(1) != want:
                errors.append(
                    "%d/%d の曜日が違う（正しくは%s曜日。%s と書かれている）" % (d.month, d.day, want, m.group(1))
                )
    return sorted(set(errors))


def validate_answercheck(text: str, yesterday: str) -> list[str]:
    errors = []
    if not text.lstrip().startswith("## "):
        errors.append("先頭行が `## <ホール名>` の見出しでない")
    for m in BAD_PHRASES.finditer(text):
        errors.append("分析できなかった・質問で終わった表現がある: 「%s」" % m.group(0))
    errors += weekday_errors(text, yesterday)
    if "予測への示唆" not in text:
        errors.append("末尾に「今日の予測への示唆」の節がない")
    return errors


def validate_prediction(text: str, key: str, today: str, need_judgement: bool) -> list[str]:
    errors = []
    if not text.lstrip().startswith("## "):
        errors.append("先頭行が `## <ホール名>` の見出しでない")
    for m in BAD_PHRASES.finditer(text):
        errors.append("分析できなかった・質問で終わった表現がある: 「%s」" % m.group(0))
    errors += weekday_errors(text, today)
    if need_judgement and not re.search(r"^[\s\-*]*\**判断\**\s*[:：]", text, re.M):
        errors.append("`判断: ...` で始まる行がない（凍結が推す機種・台をここから拾う）")
    return errors


COMMON_RULES = """\
## 守ること（自動実行のため）
- 書いてよいのは指定した出力ファイル1つだけ。それ以外のファイル（台帳・予告JSON・設定・文書）は変更しない。
- 質問で終わらない。判断材料が足りなければ、足りない理由を事実として書いたうえで、必ずファイルを書く。
- git のコミット・プッシュ、`backtest.announce register/amend`、`backtest.prediction_ledger freeze-doc`、スクレイピングは実行しない。
- Pythonは `venv\\Scripts\\python.exe` を使う。出力は日本語。数字は実測で、推測を事実のように書かない。
- 迎合しない（CLAUDE.md）。根拠の薄いものは薄いと書く。確度は全体に低〜中程度のはず。簡潔に（最大40行）。
- 出力ファイルの先頭行は `## {display}` の見出しにする（後で全ホールを連結する）。
"""


def answercheck_prompt(key: str, yesterday: str, today: str, out: Path) -> str:
    hall, display = HALLS[key]
    ydash = "%s-%s-%s" % (yesterday[:4], yesterday[4:6], yesterday[6:])
    return f"""\
{display}（DB名: {hall}）の{yesterday}分の答え合わせを書いてください。出力先: {out}

{facts_block(key, today, yesterday)}
## 手順
1. `document/reviews/` の直近の `*-answercheck.md` のうち{display}の節を1つ読み、体裁と深さを合わせる。
2. 前日の予測があれば `backtest/predictions/{yesterday}__{key}.json` と `document/reviews/{ydash}-prediction.md` の{display}の節、
   予告があれば `backtest/announce/{ANNOUNCE_PREFIX.get(key, key)}__{yesterday}__*.json`（撤回済み `.withdrawn.json` は除く）を読む。
3. `/hall-analysis-checklist`、`/prediction-evaluation` の方針に従い、DBの実測と突き合わせる。
   差枚だけで的中/不成立と結論しない。機種はG比×平均差枚、台単位はRB確率を自己ベースラインと比べる。
   末尾・角番・並び・個別RBも見る。予告の機械採点（announce の result）が空でも、DBから直接照合してよい。
4. 予測が外れた・当たった理由、翌日以降に使える学びを短く書く。予測が無かった日は、実際に強かった機種・台・並びを書く。
5. 表を書くときは、見出し行・区切り行(`|---|`)・全行の列数をそろえる。値が無い列は作らない。
6. 最後に1節「今日（{today}）の予測への示唆」を設け、箇条書き3点以内で書く。予測担当がこれを読む。

{COMMON_RULES.format(display=display)}"""


def prediction_prompt(key: str, today: str, yesterday: str, answer: Path, out: Path) -> str:
    hall, display = HALLS[key]
    has_announce = bool(announce_files(key, today))
    return f"""\
{display}（DB名: {hall}）の{today}の予測を書いてください。出力先: {out}

{facts_block(key, today, yesterday)}
## 入力
- 前日の答え合わせ: {answer}（末尾の「予測への示唆」も読む）
- 当日の予告: 上の予告ファイル（あれば）。撤回済みは除く。
  `venv\\Scripts\\python.exe -m backtest.event_days check` 等で当日のイベント日台帳（document/registry/EVENT_DAYS.jsonl）も確認する。
  X の収集結果（scraper/twitter_monitor）に当日分の未登録の予告があれば読む。登録はしない。
- 体裁の手本: `document/reviews/2026-10-17-prediction.md` の{display}の節。

## 書式（凍結が機械的に拾うので厳守）
- 見出しは `## {display}`。その下は自由に書いてよいが、次の2種類の行を書く。
  - 推す機種・台: 行頭を `判断:` で始める（例: `判断: カバネリ(42台)を軸に、台数の多い機種から。`）。
    {"予告・イベント日がある日は必ず1行書く。" if has_announce else "機種を絞る根拠が無ければ、その旨を `判断:` の行に書く。"}
  - 避ける機種: 「避ける」を含む行（例: `避ける: 東京喰種(7の付く日−405)。`）。無ければ書かない。
- 凍結は「避け」を含む行を全部「避ける機種」として拾い、そこに出る機種名をすべて避ける扱いにする。
  だから「避ける」「避け」という語は、避ける機種を書く `避ける:` の行以外では使わない。
  判断の行や解説では、「見送る」「推さない」「弱い」などと言い換える。
  `避ける:` の行には、避ける機種の名前だけを書き、推す機種の名前は入れない。
- **ジャグラー候補の表は書かない。** スクリプトが全ホール共通の「## ジャグラー候補」の節を作る。
  必要なら本文で「ジャグラーは末尾の表を参照」と書くだけにする。
- 予告が無いホール・機種を絞る根拠が無いホールは、数行で済ませる。

## 方針
- 予告の台番号・機種名・条件は原文どおりに。解釈が割れるものは「解釈が割れる」と書き、判断にしない。
- 推す根拠の数字（直近3か月、同条件の過去回の実績、母数）を添える。母数が小さければそう書く。
- 予告に「狙い目はリプに記載予定」のように、機種・台番号が後から出ると書かれている場合は、まだ出ていないことを事実として書き、機種を創作しない。

{COMMON_RULES.format(display=display)}"""


def generate(prompt: str, out: Path, validate: Callable[[str], list[str]], label: str) -> bool:
    """claude に書かせ、検証に通るまで最大2回。通らなければ .rejected.md に退避する。"""
    feedback = ""
    for attempt in (1, 2):
        if out.exists():
            out.unlink()
        if not run_claude(prompt + feedback, label if attempt == 1 else label + "（書き直し）"):
            return False
        errors = (
            validate(out.read_text(encoding="utf-8"))
            if out.exists()
            else ["出力ファイルが作られていない。質問や報告で終わらず、必ず指定のファイルに書く"]
        )
        if not errors:
            return True
        print("    不合格: %s" % " / ".join(errors), flush=True)
        feedback = "\n\n## 前回の出力は不合格だった\n%s\n同じ誤りを繰り返さず、ファイル全体を書き直す。\n" % "\n".join(
            "- " + e for e in errors
        )
    if out.exists():
        rejected = out.with_name(out.stem + ".rejected.md")
        rejected.unlink(missing_ok=True)
        out.rename(rejected)
    return False


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


# ---------------------------------------------------------------- 連結


def parse_juggler(text: str) -> tuple[str, list[tuple[int, str, bool, int, int]]]:
    """機械出力から (履歴の翌日平均, [(台, 機種, RB良好, G数, RB)]) を取り出す。"""
    avg = re.search(r"履歴の翌日平均\s*([\d.]+)", text)
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{3,4})\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(True|False)\s", line)
        if m:
            rows.append((int(m.group(1)), m.group(2), m.group(7) == "True", int(m.group(4)), int(m.group(5))))
    return (avg.group(1) if avg else "-"), rows


def juggler_section(day_dir: Path, today: str, ready: list[str]) -> str:
    """全ホール共通の「## ジャグラー候補」の節。prediction_ledger は1列目をホール、最終列を台番号として読む。"""
    table, low = [], []
    for key in ready:
        if key not in JUGGLER_LABEL:
            low.append(HALLS[key][1])
            continue
        if key == "kamata1" and not any(
            "ジャグ" in p.read_text(encoding="utf-8", errors="replace") for p in announce_files(key, today)
        ):
            low.append("%s（予告にジャグラー強化が無い日）" % HALLS[key][1])
            continue
        part = day_dir / ("%s.juggler.md" % key)
        if not part.exists():
            continue
        avg, rows = parse_juggler(part.read_text(encoding="utf-8"))
        top = rows[:5]
        if not top:
            continue
        groups: dict[str, list[int]] = {}
        for unit, name, _, _, _ in top:
            groups.setdefault(name.replace("ジャグラー", ""), []).append(unit)
        listing = "、".join("%s(%s)" % ("・".join(map(str, units)), name) for name, units in groups.items())
        good = ["%dは%sGでRB %d" % (u, format(g, ","), rb) for u, _, ok, g, rb in top if ok]
        note = "。RB良好: %s" % "、".join(good) if good else ""
        table.append("| %s | %s | %s%s |" % (JUGGLER_LABEL[key], avg, listing, note))
    lines = ["## ジャグラー候補（高設定の割合が高いホール、DB最終日の確定データから作る翌日向け）", ""]
    if table:
        lines += ["| ホール | 履歴の翌日平均 | 上位の候補（台、機種） |", "|---|---|---|"] + table
    if low:
        lines += ["", "%s は、%s" % ("・".join(low), JUGGLER_LOW_NOTE)]
    lines += ["", "予測力は弱い（約14%対無作為10%）ので参考値。開店後のRB確率で確認する。"]
    return "\n".join(lines)


def is_auto_doc(path: Path) -> bool:
    return (not path.exists()) or AUTO_MARK in path.read_text(encoding="utf-8")[:400]


def dash(day: str) -> str:
    return "%s-%s-%s" % (day[:4], day[4:6], day[6:])


def merge(day_dir: Path, today: str, yesterday: str) -> None:
    """ホール別の断片を連結して document/reviews へ書く。人手の文書・凍結済みの文書は触らない。"""

    def pieces(stage: str) -> tuple[list[str], list[str], list[str]]:
        got, missing, ready = [], [], []
        for key, (_, display) in HALLS.items():
            part = day_dir / ("%s.%s.md" % (key, stage))
            if (day_dir / ("%s.%s.done" % (key, stage))).exists() and part.exists():
                got.append(part.read_text(encoding="utf-8").strip())
                ready.append(key)
            else:
                missing.append(display)
        return got, missing, ready

    stamp = datetime.now(JST).strftime("%H:%M")

    got, missing, _ = pieces("answercheck")
    if got:
        path = REVIEWS / ("%s-answercheck.md" % dash(yesterday))
        if not is_auto_doc(path):
            path = REVIEWS / ("%s-answercheck-auto.md" % dash(yesterday))
        head = "# %s 答え合わせ（自動下書き）\n\n%s %s 作成。未確認の下書き。" % (dash(yesterday), AUTO_MARK, stamp)
        if missing:
            head += "未生成: %s" % "・".join(missing)
        path.write_text(head + "\n\n" + "\n\n".join(got) + "\n", encoding="utf-8")
        print("書き出し: %s" % path.relative_to(PROJECT_ROOT), flush=True)

    got, missing, ready = pieces("prediction")
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
        body = "\n\n".join(got) + "\n\n" + juggler_section(day_dir, today, ready)
        path.write_text(head + "\n\n" + body + "\n", encoding="utf-8")
        print("書き出し: %s" % path.relative_to(PROJECT_ROOT), flush=True)


def process_hall(key: str, day_dir: Path, yesterday: str, today: str, dry_run: bool) -> None:
    def done(stage: str) -> Path:
        return day_dir / ("%s.%s.done" % (key, stage))

    def part(stage: str) -> Path:
        return day_dir / ("%s.%s.md" % (key, stage))

    need_judgement = bool(announce_files(key, today)) or key in JUGGLER_HALLS
    stages = [
        (
            "answercheck",
            lambda: generate(
                answercheck_prompt(key, yesterday, today, part("answercheck")),
                part("answercheck"),
                lambda text: validate_answercheck(text, yesterday),
                "%s 答え合わせ" % key,
            ),
        ),
        ("juggler", lambda: run_juggler(key, part("juggler"))),
        (
            "prediction",
            lambda: generate(
                prediction_prompt(key, today, yesterday, part("answercheck"), part("prediction")),
                part("prediction"),
                lambda text: validate_prediction(text, key, today, need_judgement),
                "%s 予測" % key,
            ),
        ),
    ]
    for stage, action in stages:
        if done(stage).exists():
            continue
        print("- %s / %s" % (key, stage), flush=True)
        if dry_run:
            continue
        if stage == "juggler" and part(stage).exists():
            part(stage).unlink()
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
