"""答え合わせの「予測の照合」表（機械）と、本文の数字の検証。

当たり外れと数字はコードが出し、LLM は解釈の文章だけを書く（2026-11-01 計画）。

  1. build_check_table: 前日の凍結予測（推した機種・避けた機種・ジャグラー候補台）と予告の公約機種を、
     台数・平均差枚・勝率・G比・差枚×G比の順位・RB確率とその比・z で照合し、3段（確かに強い/平ら/弱い）で判定する。
     標本小（MODEL_MIN_UNITS 未満）は判定しない。
  2. check_table_numbers: 本文の数字（差枚・勝率・G比・RB・z・順位）を表と突き合わせる。
     表にある機種の行と食い違う数字・表の判定と逆の当たり外れは errors（不合格）、
     表のどこにも無い数字は warnings（出力に注記を足すだけ）。

DB・台帳は読み取り専用で開く。何も書き換えない。
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backtest import prediction_rb as prb  # noqa: E402
from morning_facts import _BASELINE_WORDS, _DATE, MODEL_MIN_UNITS, day_facts  # noqa: E402

# 多数の機種を同時に見るので、2026-10-26 の検算版（answercheck-addendum）と同じく z>3 だけを確かな偏りとする。
STRONG_Z = 3.0
# 差枚×G比の順位が上位（下位）1割なら強い（弱い）。ユーザー指定（2026-11-01）。
TOP_RANK_RATE = 0.10
UNIT_MIN_GAMES = prb.MIN_GAMES  # 台単位のRB比は、これ未満の回転では出さない
MAX_UNITS = 12  # 台の表の上限（RB候補が27台など多い日は先頭だけ）
MAX_EXTRA = 5  # 予測外で強かった機種の表示数
SMALL_HIST_DAYS = 90

VERDICT_STRONG, VERDICT_FLAT, VERDICT_WEAK = "確かに強い", "平ら", "弱い"
VERDICT_SMALL, VERDICT_HOLD = "標本小", "判定保留"

GROUP_PICK, GROUP_AVOID, GROUP_ANNOUNCE, GROUP_EXTRA = "推した機種", "避けた機種", "予告の公約", "予測外で強かった"
GROUP_JUG = "ジャグラー候補台"
# 予測の当たり外れを数える区分（予測外は予測ではないので除く）
_PREDICTED_GROUPS = (GROUP_PICK, GROUP_AVOID, GROUP_JUG, GROUP_ANNOUNCE)


@dataclass
class Row:
    group: str
    name: str
    n: int
    mean: float | None = None
    win: float | None = None
    g_ratio: float | None = None
    rank: int | None = None
    total: int | None = None
    rb_prob: float | None = None  # 当日の実測 1/x の x
    base_prob: float | None = None  # 通常日 1/x の x
    ratio: float | None = None
    z: float | None = None
    verdict: str = VERDICT_SMALL
    result: str = "判定なし"


@dataclass
class UnitRow:
    number: int
    name: str
    games: float | None
    rb_prob: float | None
    base_prob: float | None
    ratio: float | None
    z: float | None
    diff: float | None
    verdict: str
    result: str


@dataclass
class SmallUnitRow:
    number: int
    name: str
    games: float
    diff: float
    g_ratio: float
    score: float
    rank: int
    total: int
    hist_mean: float | None
    hist_games: float | None
    hist_days: int
    rb_prob: float | None
    base_prob: float | None
    z: float | None
    verdict: str
    result: str


@dataclass
class CheckTable:
    lines: list[str]
    rows: list[Row] = field(default_factory=list)
    units: list[UnitRow] = field(default_factory=list)
    day: str = ""
    known_names: list[str] = field(default_factory=list)  # その日DBにある全機種名（本文の帰属判定用）
    small_units: list[SmallUnitRow] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def judge(rank: int, total: int, z: float | None) -> str:
    k = max(1, math.ceil(total * TOP_RANK_RATE))
    up = (z is not None and z > STRONG_Z) or rank <= k
    down = (z is not None and z < -STRONG_Z) or rank > total - k
    if up and down:
        return VERDICT_HOLD
    return VERDICT_STRONG if up else VERDICT_WEAK if down else VERDICT_FLAT


def outcome(group: str, verdict: str) -> str:
    """予測の当たり外れ。避けた機種は強弱が逆（強ければ避けて外した）。"""
    if group not in _PREDICTED_GROUPS or verdict not in (VERDICT_STRONG, VERDICT_FLAT, VERDICT_WEAK):
        return "判定なし"
    if verdict == VERDICT_FLAT:
        return "平ら"
    good = verdict == VERDICT_STRONG
    if group == GROUP_AVOID:
        good = not good
    return "当たり" if good else "外れ"


def _ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)


def _baseline(con: sqlite3.Connection, day: str) -> dict[str, float]:
    """機種別の通常日RB率（RB/G）。prediction_rb.rb_result と同じ60日の自己ベースライン。"""
    target = datetime.strptime(day, "%Y%m%d")
    start = (target - timedelta(days=prb.BASELINE_DAYS)).strftime("%Y%m%d")
    end = (target - timedelta(days=1)).strftime("%Y%m%d")
    specs = prb._specs()
    judgeable: dict[str, bool] = {}
    acc: dict[str, list[float]] = {}
    for name, games, rb in con.execute(
        "SELECT machine_name, games_normalized, rb_count FROM machine_detailed_results WHERE date >= ? AND date <= ?",
        (start, end),
    ):
        if name not in judgeable:
            judgeable[name] = prb._judgeable(name, specs)
        if not judgeable[name] or games is None or games < prb.MIN_GAMES or rb is None:
            continue
        item = acc.setdefault(name, [0, 0.0, 0.0])
        item[0] += 1
        item[1] += games
        item[2] += rb
    return {n: v[2] / v[1] for n, v in acc.items() if v[0] >= prb.MIN_BASE_MACHINE_DAYS and v[1] > 0 and v[2] > 0}


def _rb_stats(rows: list[tuple], rate: float | None) -> dict:
    """rows: (games, rb)。rate: 通常日のRB率。判別不能・回転不足なら空。"""
    usable = [(g, rb) for g, rb in rows if g is not None and g >= prb.MIN_GAMES and rb is not None]
    if not usable or not rate:
        return {}
    games = sum(g for g, _ in usable)
    obs = sum(rb for _, rb in usable)
    exp = games * rate
    return {
        "rb_prob": games / obs if obs > 0 else None,
        "base_prob": 1 / rate,
        "ratio": obs / exp if exp > 0 else None,
        "z": (obs - exp) / math.sqrt(exp) if exp > 0 else None,
    }


def load_picks(predictions_dir: Path, key: str, day: str) -> tuple[dict, list[int]]:
    """凍結した予測の名指し（最新の改訂）と、RB候補（自動）の台。"""
    base = predictions_dir / ("%s__%s.json" % (day, key))
    revs = sorted(predictions_dir.glob("%s__%s__rev*.json" % (day, key)))
    chosen = revs[-1] if revs else base
    picks: dict = {}
    if chosen.exists():
        try:
            picks = json.loads(chosen.read_text(encoding="utf-8")).get("picks") or {}
        except OSError, ValueError:
            picks = {}
    auto_units: list[int] = []
    auto = predictions_dir / ("%s__%s__rbauto.json" % (day, key))
    if auto.exists():
        try:
            data = json.loads(auto.read_text(encoding="utf-8"))
            auto_units = [int(n) for n in (data.get("picks") or {}).get("units") or []]
        except OSError, ValueError, TypeError:
            auto_units = []
    return picks, auto_units


def announce_models(announce_dir: Path, prefix: str, day: str) -> list[str]:
    """予告で名指しされた機種（撤回・無効化は除く）。"""
    names: list[str] = []
    for path in sorted(announce_dir.glob("%s__%s__*.json" % (prefix, day))):
        if ".withdrawn" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if any(a.get("void") for a in data.get("amendments") or [] if isinstance(a, dict)):
            continue
        for c in data.get("claims") or []:
            name = c.get("machine_name") if isinstance(c, dict) else None
            if isinstance(name, str) and name not in names:
                names.append(name)
    return names


def _signed(value: float) -> str:
    return "%+d" % round(value)


def _fmt_prob(x: float | None) -> str:
    return "1/%d" % round(x) if x else "-"


def build_check_table(
    db_path: Path,
    predictions_dir: Path,
    announce_dir: Path,
    announce_prefix: str,
    key: str,
    day: str,
) -> CheckTable | None:
    """前日の予測の照合表。DB・その日のデータが無ければ None。"""
    if not db_path.exists():
        return None
    try:
        con = _ro(db_path)
        try:
            day_rows = con.execute(
                "SELECT machine_number, machine_name, games_normalized, diff_coins_normalized, rb_count "
                "FROM machine_detailed_results WHERE date=? AND diff_coins_normalized IS NOT NULL",
                (day,),
            ).fetchall()
            base_rate = _baseline(con, day) if day_rows else {}
            start = (datetime.strptime(day, "%Y%m%d") - timedelta(days=SMALL_HIST_DAYS)).strftime("%Y%m%d")
            end = (datetime.strptime(day, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
            hist_rows = (
                con.execute(
                    "SELECT machine_name, AVG(diff_coins_normalized), AVG(COALESCE(games_normalized, 0)), COUNT(*) "
                    "FROM machine_detailed_results WHERE date BETWEEN ? AND ? AND diff_coins_normalized IS NOT NULL "
                    "GROUP BY machine_name",
                    (start, end),
                ).fetchall()
                if day_rows
                else []
            )
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not day_rows:
        return None

    hall_avg_g = sum(r[2] or 0 for r in day_rows) / len(day_rows)
    by_model: dict[str, list[tuple]] = {}
    for number, name, games, diff, rb in day_rows:
        by_model.setdefault(name, []).append((number, games or 0, diff, rb))

    def stats(name: str) -> dict:
        items = by_model[name]
        mean = sum(d for _, _, d, _ in items) / len(items)
        avg_g = sum(g for _, g, _, _ in items) / len(items)
        g_ratio = avg_g / hall_avg_g if hall_avg_g else 0.0
        return {
            "mean": mean,
            "win": sum(1 for _, _, d, _ in items if d > 0) / len(items),
            "g_ratio": g_ratio,
            "score": mean * g_ratio,
        }

    universe = {n: stats(n) for n in by_model if len(by_model[n]) >= MODEL_MIN_UNITS}
    order = sorted(universe, key=lambda n: universe[n]["score"], reverse=True)
    rank_of = {n: i + 1 for i, n in enumerate(order)}
    total = len(order)

    def make_row(group: str, name: str) -> Row:
        if name not in by_model:
            return Row(group, name, 0, verdict="当日データ無し")
        n = len(by_model[name])
        if name not in universe:
            return Row(group, name, n, verdict=VERDICT_SMALL)
        s = universe[name]
        rb = _rb_stats([(g, r) for _, g, _, r in by_model[name]], base_rate.get(name))
        row = Row(
            group,
            name,
            n,
            mean=s["mean"],
            win=s["win"],
            g_ratio=s["g_ratio"],
            rank=rank_of[name],
            total=total,
            rb_prob=rb.get("rb_prob"),
            base_prob=rb.get("base_prob"),
            ratio=rb.get("ratio"),
            z=rb.get("z"),
        )
        row.verdict = judge(row.rank, total, row.z)
        row.result = outcome(group, row.verdict)
        return row

    picks, auto_units = load_picks(predictions_dir, key, day)
    rows: list[Row] = []
    used: set[str] = set()
    for group, names in (
        (GROUP_PICK, picks.get("models") or []),
        (GROUP_AVOID, picks.get("avoid_models") or []),
        (GROUP_ANNOUNCE, announce_models(announce_dir, announce_prefix, day)),
    ):
        for name in names:
            if name in used:
                continue
            used.add(name)
            rows.append(make_row(group, name))

    # 台1台の値は機種平均よりばらつきが大きく、機種順位表に混ぜると極端に出やすい。
    # 当日の全台分布で上位・下位1割を測り、機種の3段判定と同じ割合・z>3に揃える。
    # 直近90日の同機種平均は普段との比較材料として併記する（2026-11-07 みとや うみねこ2の手評価）。
    history = {name: (mean, games, days) for name, mean, games, days in hist_rows}
    all_scores = [diff * ((games or 0) / hall_avg_g if hall_avg_g else 0.0) for _, _, games, diff, _ in day_rows]
    small_units: list[SmallUnitRow] = []
    for name in dict.fromkeys(picks.get("models") or []):
        if name not in by_model or len(by_model[name]) >= MODEL_MIN_UNITS:
            continue
        hist_mean, hist_games, hist_days = history.get(name, (None, None, 0))
        for number, games, diff, rb in by_model[name]:
            g_ratio = games / hall_avg_g if hall_avg_g else 0.0
            score = diff * g_ratio
            rank = 1 + sum(other > score for other in all_scores)
            stat = _rb_stats([(games, rb)], base_rate.get(name)) if games >= UNIT_MIN_GAMES else {}
            z = stat.get("z")
            verdict = judge(rank, len(day_rows), z)
            small_units.append(
                SmallUnitRow(
                    number,
                    name,
                    games,
                    diff,
                    g_ratio,
                    score,
                    rank,
                    len(day_rows),
                    hist_mean,
                    hist_games,
                    hist_days,
                    stat.get("rb_prob"),
                    stat.get("base_prob"),
                    z,
                    verdict,
                    outcome(GROUP_PICK, verdict),
                )
            )

    unit_numbers = [int(n) for n in picks.get("jug_units") or []]
    unit_source = "ジャグラー候補台"
    if not unit_numbers and auto_units:
        unit_numbers, unit_source = auto_units, "RB候補台（自動）"
    by_number = {r[0]: (r[1], r[2], r[3], r[4]) for r in day_rows}
    units: list[UnitRow] = []
    for number in unit_numbers[:MAX_UNITS]:
        if number not in by_number:
            units.append(UnitRow(number, "-", None, None, None, None, None, None, "データ無し", "判定なし"))
            continue
        name, games, diff, rb = by_number[number]
        stat = _rb_stats([(games, rb)], base_rate.get(name)) if games and games >= UNIT_MIN_GAMES else {}
        if not stat:
            verdict = "回転不足" if not games or games < UNIT_MIN_GAMES else "判別不可"
            units.append(UnitRow(number, name, games, None, None, None, None, diff, verdict, "判定なし"))
            continue
        z = stat["z"]
        verdict = VERDICT_STRONG if z > STRONG_Z else VERDICT_WEAK if z < -STRONG_Z else VERDICT_FLAT
        units.append(
            UnitRow(
                number,
                name,
                games,
                stat["rb_prob"],
                stat["base_prob"],
                stat["ratio"],
                z,
                diff,
                verdict,
                outcome(GROUP_JUG, verdict),
            )
        )

    extras = 0
    for name in order:
        if extras >= MAX_EXTRA:
            break
        if name in used:
            continue
        row = make_row(GROUP_EXTRA, name)
        if row.verdict == VERDICT_STRONG:
            used.add(name)
            rows.append(row)
            extras += 1

    lines = _render(day, rows, small_units, units, unit_source, len(unit_numbers), hall_avg_g, total, db_path)
    return CheckTable(lines, rows, units, day, sorted(by_model), small_units)


def _render(
    day: str,
    rows: list[Row],
    small_units: list[SmallUnitRow],
    units: list[UnitRow],
    unit_source: str,
    n_units_all: int,
    hall_avg_g: float,
    total: int,
    db_path: Path,
) -> list[str]:
    pct = round(TOP_RANK_RATE * 100)
    out = [
        "#### 予測の照合（機械判定。当たり外れはこの表の判定をそのまま使い、書き直さない）",
        "",
        "- ホール平均G %s、%d台以上の機種は全%d。順位は平均差枚×G比（G比＝機種平均G÷ホール平均G）。"
        % (format(round(hall_avg_g), ","), MODEL_MIN_UNITS, total),
        "- 判定: z>%g、または順位が上位%d%%なら「確かに強い」、z<-%g または下位%d%%なら「弱い」、それ以外は「平ら」。"
        "%d台未満は「標本小」で判定しない。避けた機種は強弱が逆（強ければ外れ）。推した3台未満の機種は台ごとに下の表で判定する。"
        % (STRONG_Z, pct, STRONG_Z, pct, MODEL_MIN_UNITS),
    ]
    prev = (datetime.strptime(day, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    prev_facts = day_facts(db_path, prev)
    if prev_facts:
        out.append(
            "- 前日（%d/%d）のホール: 日平均 %s/台、総差枚 %s枚。"
            % (int(prev[4:6]), int(prev[6:8]), _signed(prev_facts.mean), format(prev_facts.total, "+,"))
        )
    if rows:
        out += [
            "",
            "| 区分 | 機種 | 台数 | 平均差枚 | 勝率 | G比 | 差枚×G比の順位 | RB確率(通常日) | RB比 | z | 判定 | 予測の結果 |",
            "|---|---|---:|---:|---:|---:|---:|---|---:|---:|---|---|",
        ]
        for r in rows:
            if r.mean is None:
                out.append(
                    "| %s | %s | %d | - | - | - | - | - | - | - | %s | 判定なし |" % (r.group, r.name, r.n, r.verdict)
                )
                continue
            rb = "%s (%s)" % (_fmt_prob(r.rb_prob), _fmt_prob(r.base_prob)) if r.base_prob else "-"
            out.append(
                "| %s | %s | %d | %s | %d%% | %.2f | %d機種中%d位 | %s | %s | %s | %s | %s |"
                % (
                    r.group,
                    r.name,
                    r.n,
                    _signed(r.mean),
                    round(100 * r.win),
                    r.g_ratio,
                    r.total,
                    r.rank,
                    rb,
                    "%.2f" % r.ratio if r.ratio is not None else "-",
                    "%+.1f" % r.z if r.z is not None else "-",
                    r.verdict,
                    r.result,
                )
            )
    else:
        out += ["", "名指しされた機種は無い（推した・避けた・予告の公約）。"]
    if small_units:
        out += [
            "",
            "少台数の推し（台ごとに評価。順位は当日の全%d台の差枚×G比、判定の割合と z の基準は機種と同じ。直近%d日は同機種の台×日の平均）:"
            % (small_units[0].total, SMALL_HIST_DAYS),
            "",
            "| 台番号 | 機種 | 回転数 | 差枚 | G比 | 差枚×G比の順位 | 直近90日の平均差枚 | 直近90日の平均G | RB確率(通常日) | z | 判定 | 予測の結果 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---|---:|---|---|",
        ]
        for u in small_units:
            rb = "%s (%s)" % (_fmt_prob(u.rb_prob), _fmt_prob(u.base_prob)) if u.base_prob else "-"
            out.append(
                "| %d | %s | %s | %s | %.2f | %d台中%d位 | %s | %s | %s | %s | %s | %s |"
                % (
                    u.number,
                    u.name,
                    format(round(u.games), ","),
                    _signed(u.diff),
                    u.g_ratio,
                    u.total,
                    u.rank,
                    _signed(u.hist_mean) if u.hist_mean is not None else "-",
                    format(round(u.hist_games), ",") if u.hist_games is not None else "-",
                    rb,
                    "%+.1f" % u.z if u.z is not None else "-",
                    u.verdict,
                    u.result,
                )
            )
    if units:
        note = "RB確率の(通常日)＝同機種の直近%d日。台のzは自機種の通常日に対する値" % prb.BASELINE_DAYS
        if n_units_all > MAX_UNITS:
            note += "。先頭%d台まで" % MAX_UNITS
        out += [
            "",
            "%s（%s）:" % (unit_source, note),
            "",
            "| 台番号 | 機種 | 回転数 | 差枚 | RB確率(通常日) | RB比 | z | 判定 | 予測の結果 |",
            "|---:|---|---:|---:|---|---:|---:|---|---|",
        ]
        for u in units:
            games = format(round(u.games), ",") if u.games is not None else "-"
            diff = _signed(u.diff) if u.diff is not None else "-"
            rb = "%s (%s)" % (_fmt_prob(u.rb_prob), _fmt_prob(u.base_prob)) if u.base_prob else "-"
            out.append(
                "| %d | %s | %s | %s | %s | %s | %s | %s | %s |"
                % (
                    u.number,
                    u.name,
                    games,
                    diff,
                    rb,
                    "%.2f" % u.ratio if u.ratio is not None else "-",
                    "%+.1f" % u.z if u.z is not None else "-",
                    u.verdict,
                    u.result,
                )
            )
    return out


# ---------------------------------------------------------------- 本文の数字の検証

_NUM = re.compile(r"[+\-]?\d[\d,]*(?:\.\d+)?")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("−", "-").replace("－", "-").replace("＋", "+")


def _parse(token: str) -> tuple[float, int]:
    cleaned = token.replace(",", "")
    decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
    return float(cleaned), decimals


def number_pool(text: str) -> list[float]:
    return [_parse(m.group(0))[0] for m in _NUM.finditer(normalize(text))]


def _close(written: float, decimals: int, actual: float, extra: float = 0.0) -> bool:
    return abs(written - actual) <= 0.5 * 10**-decimals + extra + 1e-9


# 指標語の直後の数字だけを見る。日付・曜日・台番号・台数・L00x は拾わない。
_SIGNED_OR_BIG = r"([+\-]\d[\d,]*(?:\.\d+)?|\d[\d,]{3,}(?:\.\d+)?)"
_LABELED = (
    ("mean", "平均差枚", re.compile(r"(?:平均差枚|平均|差枚)[^\d+\-|\n]{0,4}" + _SIGNED_OR_BIG)),
    ("win", "勝率", re.compile(r"勝率[^\d\n]{0,3}(\d+(?:\.\d+)?)\s*%")),
    ("g", "G比", re.compile(r"G比[^\d\n]{0,3}(\d+(?:\.\d+)?)")),
    ("z", "z", re.compile(r"(?<![A-Za-z])z\s*[=＝]?\s*([+\-]?\d+(?:\.\d+)?)")),
    ("ratio", "RB比", re.compile(r"RB比[^\d\n]{0,3}(\d+(?:\.\d+)?)")),
    ("prob", "RB確率", re.compile(r"1/(\d+)")),
    ("rank", "順位", re.compile(r"(\d+)\s*機種中\s*(\d+)\s*位")),
)
MAX_NAME_GAP = 14  # 機種名と数字の間の最大文字数（これを超えたら、その機種の値とみなさない）
_HALL_LEAD = re.compile(r"ホール|全体|全台|全ホール")
_POSITIVE = re.compile(r"当たり|的中")
_NEGATIVE = re.compile(r"外れ(?!値)|不的中|不成立")


@dataclass
class _Mention:
    kind: str
    label: str
    raw: str
    value: float
    decimals: int
    pos: int


def _mentions(line: str) -> list[_Mention]:
    found: list[_Mention] = []
    for kind, label, pattern in _LABELED:
        for m in pattern.finditer(line):
            if kind == "rank":
                found.append(_Mention("rank", label, m.group(0), float(m.group(2)), 0, m.start()))
                found.append(_Mention("rank_total", label, m.group(0), float(m.group(1)), 0, m.start()))
                continue
            value, decimals = _parse(m.group(1))
            found.append(_Mention(kind, label, m.group(1), value, decimals, m.start(1)))
    return found


def _row_value(row: Row, kind: str) -> list[float]:
    """行の値（複数あれば、どれかに合えばよい）。無ければ空（照合しない）。"""
    if kind == "mean" and row.mean is not None:
        return [row.mean]
    if kind == "win" and row.win is not None:
        return [100 * row.win]
    if kind == "g" and row.g_ratio is not None:
        return [row.g_ratio]
    if kind == "z" and row.z is not None:
        return [row.z]
    if kind == "ratio" and row.ratio is not None:
        return [row.ratio]
    if kind == "prob":
        return [p for p in (row.rb_prob, row.base_prob) if p]
    if kind == "rank" and row.rank is not None:
        return [row.rank]
    if kind == "rank_total" and row.total is not None:
        return [row.total]
    return []


def _mismatch(m: _Mention, actual: list[float]) -> str | None:
    """行の値と合わなければ理由を返す。差枚とRB確率は整数への丸めを許す。"""
    if not actual:
        return None
    extra = 0.5 if m.kind in ("mean", "prob") else 0.0
    if any(_close(m.value, m.decimals, a, extra) for a in actual):
        return None
    if m.kind in ("mean", "z", "ratio") and any(_close(-m.value, m.decimals, a, extra) for a in actual):
        return "符号が逆"
    return "値が違う"


def check_table_numbers(text: str, table: CheckTable | None, facts_md: str = "") -> tuple[list[str], list[str]]:
    """(errors, warnings)。errors は不合格、warnings は表に無い数字の注記。"""
    if table is None:
        return [], []
    errors: list[str] = []
    warnings: list[str] = []
    pool = number_pool(table.text + "\n" + facts_md)
    day_md = (int(table.day[4:6]), int(table.day[6:8])) if len(table.day) == 8 else None
    by_name: dict[str, Row] = {}
    for r in table.rows:
        if r.mean is not None:
            by_name.setdefault(normalize(r.name), r)
    # 帰属は、その日DBにある全機種名で判定する（表に無い機種の数字を、名前の似た表の機種に当てない）。
    known = sorted({normalize(n) for n in table.known_names} | set(by_name), key=len, reverse=True)
    unit_numbers = {str(u.number) for u in table.units} | {str(u.number) for u in table.small_units}
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#") or stripped.startswith("|---"):
            continue
        line = normalize(raw)
        if any(w in line for w in _BASELINE_WORDS):
            continue
        if day_md and any((int(a), int(b)) != day_md for a, b in _DATE.findall(line)):
            continue  # 当日以外の日付の数字を述べている行
        in_units = any(re.search(r"(?<!\d)%s(?!\d)" % n, line) for n in unit_numbers)
        spans: list[tuple[int, int, str]] = []
        for name in known:
            for hit in re.finditer(re.escape(name), line):
                if not any(a <= hit.start() and hit.end() <= b for a, b, _ in spans):
                    spans.append((hit.start(), hit.end(), name))
        spans.sort()
        for mention in _mentions(line):
            owner = None
            before = [sp for sp in spans if sp[1] <= mention.pos]
            if before and not in_units and not _HALL_LEAD.search(line[max(0, mention.pos - 8) : mention.pos]):
                near = before[-1]
                # 「A・B…35台 平均+537」のように並べた機種の合算値は、最後の機種の値ではない。
                listed = len(before) >= 2 and near[0] - before[-2][1] <= 2
                gap = line[near[1] : mention.pos]
                # 機種名から離れた数字、別の語を挟んだ数字（「A・B …」「| 28台 平均」）は、その機種の値とは限らない。
                near_enough = len(gap) <= MAX_NAME_GAP and not re.search(r"[。・|]", gap)
                if not listed and near_enough and near[2] in by_name:
                    owner = near[2]
            if owner:
                actual = _row_value(by_name[owner], mention.kind)
                why = _mismatch(mention, actual)
                if why:
                    errors.append(
                        "「%s」の%s が照合表と合わない（%s）: 「%s」と書かれているが、表では %s"
                        % (
                            by_name[owner].name,
                            mention.label,
                            why,
                            mention.raw.strip(),
                            " / ".join("%g" % v for v in actual),
                        )
                    )
                continue
            if mention.kind == "rank_total":
                continue
            extra = 0.5 if mention.kind in ("mean", "prob") else 0.0
            if not any(
                _close(mention.value, mention.decimals, p, extra) or _close(-mention.value, mention.decimals, p, extra)
                for p in pool
            ):
                warnings.append("%s %s" % (mention.label, mention.raw.strip()))
        hit_names = {n for _, _, n in spans}
        if len(hit_names) == 1 and next(iter(hit_names)) in by_name:
            row = by_name[next(iter(hit_names))]
            negative = bool(_NEGATIVE.search(line))
            positive = bool(_POSITIVE.search(_NEGATIVE.sub("", line)))
            if row.group in _PREDICTED_GROUPS and positive != negative:
                if (row.result == "当たり" and negative) or (row.result == "外れ" and positive):
                    errors.append(
                        "「%s」の当たり外れが照合表と逆: 表では「%s」（判定: %s）。表の判定をそのまま使う"
                        % (row.name, row.result, row.verdict)
                    )
    return sorted(set(errors)), sorted(set(warnings))
