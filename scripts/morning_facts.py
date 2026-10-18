"""朝の答え合わせの機械集計と、LLM出力の数字の検証。

run_morning_docs.py が claude -p に答え合わせを書かせるとき、次の2つを機械で行う。

  1. 標準の集計表（ホール平均・機種別・凍結した予測の採点・予告の機械採点）をDBと台帳から作り、
     プロンプトに渡し、出力ファイルの先頭にそのまま挿入する。claude に数字を計算させない。
  2. claude が書いたホール全体の平均差枚・総差枚が、DBの値と合うかを検証する。合わなければ
     不合格にして書き直させる（誤った数字が翌日の予測に流れるのを止める）。

DB・台帳は読み取り専用で開く。何も書き換えない。
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
from dataclasses import dataclass, field
from pathlib import Path

MODEL_MIN_UNITS = 3  # これ未満の台数の機種は表に出さない（1〜2台の突出を平均で語らせない）
BIG_WIN = 2000  # 「大きく出た台」の目安（枚）
TOP_MODELS = 12
BOTTOM_MODELS = 6

MEAN_TOLERANCE = 2.0  # 枚/台。丸め（+460.8 と +461）は許す
TOTAL_TOLERANCE_RATE = 0.01


@dataclass
class ModelRow:
    name: str
    n: int
    mean: float
    n_big: int
    win_rate: float
    avg_games: float


@dataclass
class DayFacts:
    day: str
    n_units: int
    mean: float
    median: float
    win_rate: float
    avg_games: float
    total: int
    models: list[ModelRow] = field(default_factory=list)


def day_facts(db_path: Path, day: str) -> DayFacts | None:
    """その日のホール全体と機種別の集計。DBが無い・その日のデータが無いときは None。"""
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            rows = con.execute(
                "SELECT machine_name, games_normalized, diff_coins_normalized "
                "FROM machine_detailed_results WHERE date=? AND diff_coins_normalized IS NOT NULL",
                (day,),
            ).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None

    diffs = [r[2] for r in rows]
    games = [r[1] or 0 for r in rows]
    by_model: dict[str, list[tuple[int, int]]] = {}
    for name, g, d in rows:
        by_model.setdefault(name, []).append((g or 0, d))
    models = [
        ModelRow(
            name=name,
            n=len(items),
            mean=sum(d for _, d in items) / len(items),
            n_big=sum(1 for _, d in items if d >= BIG_WIN),
            win_rate=sum(1 for _, d in items if d > 0) / len(items),
            avg_games=sum(g for g, _ in items) / len(items),
        )
        for name, items in by_model.items()
        if len(items) >= MODEL_MIN_UNITS
    ]
    models.sort(key=lambda m: m.mean, reverse=True)
    return DayFacts(
        day=day,
        n_units=len(rows),
        mean=sum(diffs) / len(diffs),
        median=float(statistics.median(diffs)),
        win_rate=sum(1 for d in diffs if d > 0) / len(diffs),
        avg_games=sum(games) / len(games),
        total=int(sum(diffs)),
        models=models,
    )


def _signed(value: float) -> str:
    return "%+d" % round(value)


def render_models(facts: DayFacts) -> list[str]:
    if not facts.models:
        return ["（%d台以上ある機種は無い）" % MODEL_MIN_UNITS]
    chosen = facts.models[:TOP_MODELS]
    tail = [m for m in facts.models[-BOTTOM_MODELS:] if m not in chosen]
    lines = ["| 機種 | 台数 | 平均差枚 | +%d以上の台 | 勝率 | 平均G |" % BIG_WIN, "|---|---:|---:|---:|---:|---:|"]
    for m in chosen + tail:
        lines.append(
            "| %s | %d | %s | %d | %d%% | %s |"
            % (m.name, m.n, _signed(m.mean), m.n_big, round(100 * m.win_rate), format(round(m.avg_games), ","))
        )
    if len(facts.models) > len(chosen) + len(tail):
        lines.append(
            "（上位%d機種と下位%d機種のみ。%d台以上の機種は全%d）"
            % (TOP_MODELS, BOTTOM_MODELS, MODEL_MIN_UNITS, len(facts.models))
        )
    return lines


def ledger_lines(predictions_dir: Path, key: str, day: str) -> list[str]:
    """凍結した予測（backtest/predictions）の採点。無ければ空。"""
    path = predictions_dir / ("%s__%s.json" % (day, key))
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return []
    result = data.get("result")
    lines = ["#### 凍結した予測の採点（prediction_ledger）", ""]
    if not result:
        return lines + ["未採点。"]
    lines.append(
        "当日の全台平均 %s、対象 %s台。edge は推した機種・台・ジャグラー候補なら「名指しした台の平均 − 当日の全台平均」、"
        "避ける機種なら「当日の全台平均 − 機種の平均」（正なら避けて正解）。"
        % (_signed(result.get("day_mean", 0)), result.get("universe_size", "?"))
    )
    labels = {"models": "推した機種", "avoid_models": "避ける機種", "units": "推した台", "jug_units": "ジャグラー候補"}
    for k, label in labels.items():
        r = result.get(k)
        picks = (data.get("picks") or {}).get(k) or []
        if not r:
            continue
        lines.append(
            "- %s（%s）: %d台、平均 %s、edge %s"
            % (
                label,
                "・".join(map(str, picks)) or "-",
                r.get("n_machines", 0),
                _signed(r.get("mean_diff", 0)),
                _signed(r.get("edge", 0)),
            )
        )
    return lines


def announce_lines(announce_dir: Path, prefix: str, day: str) -> list[str]:
    """予告の機械採点（announce score の result）。撤回・無効化は除く。"""
    out: list[str] = []
    for path in sorted(announce_dir.glob("%s__%s__*.json" % (prefix, day))):
        if ".withdrawn" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if data.get("voided"):
            continue
        result = data.get("result")
        if not result:
            out.append("- %s: 未採点" % path.stem)
            continue
        claims = result.get("claims") or []
        if not claims:
            out.append("- %s: 主張なし（機種名指しなし）" % path.stem)
            continue
        for c in claims:
            kind = c.get("type")
            claim = c.get("claim") or {}
            name = claim.get("machine_name") or ""
            if kind == "model_named_ratio":
                what = "%s 1/%s" % (name, claim.get("ratio") or c.get("ratio"))
            elif kind == "zentaikei_count":
                what = "全台系 %s機種以上（実測 %s機種）" % (claim.get("n_models"), c.get("observed_n_models"))
            else:
                what = "%s %s" % (kind, name)
            out.append("- %s: %s → %s" % (path.stem, what, "的中" if c.get("hit") else "外れ"))
    if not out:
        return []
    return ["#### 予告の機械採点（announce score）", "", *out]


def render_facts(facts: DayFacts, key: str, predictions_dir: Path, announce_dir: Path, announce_prefix: str) -> str:
    head = "- %d台、日平均 %s/台、中央値 %s、勝率 %d%%、平均G %s、総差枚 %s枚。" % (
        facts.n_units,
        _signed(facts.mean),
        _signed(facts.median),
        round(100 * facts.win_rate),
        format(round(facts.avg_games), ","),
        format(facts.total, "+,"),
    )
    parts = ["### 機械集計（スクリプトがDBから計算。数字はここから引用する）", "", head, ""]
    parts += render_models(facts)
    for block in (
        ledger_lines(predictions_dir, key, facts.day),
        announce_lines(announce_dir, announce_prefix, facts.day),
    ):
        if block:
            parts += ["", *block]
    return "\n".join(parts)


# ---------------------------------------------------------------- 出力の数字の検証

_NUM = r"([+\-−－＋]?\s?\d[\d,]*(?:\.\d+)?)"
# ホール全体の平均を示すキーワードのすぐ後ろに数字が続く記述だけを見る。
# 「| ホール平均 | 7の付く日+203 | +99 |」のような表の行は、キーワードと数字の間に枠線があるので対象外。
# 本文中の記述は符号つきの数字だけ読む（「ホール全体平均の2倍以上」の2を平均と取り違えない）。
_SIGNED_NUM = r"([+\-−－＋]\s?\d[\d,]*(?:\.\d+)?)"
_HALL_INLINE = re.compile(r"(?:ホール全体|ホール平均|日平均|全体平均)\**[^\d+\-−－＋|\n]{0,3}" + _SIGNED_NUM)
# 「平均差枚 +99/台」は、直近の見出しが「ホール全体」のときだけホール全体の値とみなす
# （「### ジャグラー」の下の「平均差枚」はジャグラーだけの値で、ホール全体とは別）。
_MEAN_LABEL = re.compile(r"^[\s>*\-#|]*\**平均差枚\**[^\d+\-−－＋|\n]{0,8}" + _NUM)
_TOTAL = re.compile(r"(?:総差枚|合計差枚|合計)[^\d+\-−－＋|\n]{0,3}" + _NUM)
_DATE = re.compile(r"(\d{1,2})/(\d{1,2})")
# 基準値・過去日・予測時の数字を述べる行は、当日の値との比較にならないので見ない（誤って弾くより見逃す）。
_BASELINE_WORDS = ("他日", "の付く日", "通常", "過去", "予測", "期待", "前日", "直近", "30日", "平年")


def parse_number(text: str) -> float:
    cleaned = text.replace(",", "").replace(" ", "").replace("−", "-").replace("－", "-").replace("＋", "+")
    return float(cleaned)


def check_numbers(text: str, facts: DayFacts | None) -> list[str]:
    """ホール全体の平均差枚・総差枚が、DBの値と合うか。合わない記述を文にして返す。"""
    if facts is None:
        return []
    errors: list[str] = []
    day_md = (int(facts.day[4:6]), int(facts.day[6:8]))
    under_hall_heading = False
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            under_hall_heading = "ホール全体" in line and "ジャグ" not in line
            continue
        if any(w in line for w in _BASELINE_WORDS):
            continue
        if any((int(a), int(b)) != day_md for a, b in _DATE.findall(line)):
            continue  # 当日以外の日付の数字を述べている行
        written = [m.group(1) for m in _HALL_INLINE.finditer(line)]
        label = _MEAN_LABEL.match(line)
        if label and under_hall_heading:
            written.append(label.group(1))
        for number in written:
            if abs(parse_number(number) - facts.mean) > MEAN_TOLERANCE:
                errors.append(
                    "ホール全体の平均差枚が DB と合わない: 「%s」と書かれているが、DBでは %s/台（機械集計の表の値を使う）"
                    % (number.strip(), _signed(facts.mean))
                )
        t = _TOTAL.search(line)
        if t and written:
            total = parse_number(t.group(1))
            if abs(total - facts.total) > max(100.0, TOTAL_TOLERANCE_RATE * abs(facts.total)):
                errors.append(
                    "総差枚が DB と合わない: 「%s」と書かれているが、DBでは %s枚"
                    % (t.group(1).strip(), format(facts.total, "+,"))
                )
    return sorted(set(errors))


def inject_facts(path: Path, facts_md: str) -> None:
    """出力ファイルの先頭の見出し（`## <ホール名>`）の直後に、機械集計を差し込む。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return
    path.write_text("\n".join([lines[0], "", facts_md, "", *lines[1:]]).rstrip() + "\n", encoding="utf-8")
