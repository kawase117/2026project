"""学びの台帳(document/registry/LESSONS.jsonl)と、予測文書の判断行の点検。

なぜ要るか(2026-10 の月次振り返り 3.1):
    答え合わせの「学び」に同じ文(前日の強さは続かない・少台数機種は根拠にならない)を
    月に8回以上書き直したのに、翌朝の予測の判断行に同じ誤りが残り続けた。学びを文章で
    残すだけでは次の予測に入らないので、台帳にして凍結前に機械で照らす。

台帳に入れるもの:
    2回以上確認した学び、または統計の裏づけがある学びだけ。1日の観察は入れない
    (`add` は確認日が2つ以上か --stat-basis が無いと拒否する)。

1行1件の項目:
    id            L001, L002, ...
    rule          学びの本文(1文)
    basis_type    予測で誤用される根拠の型(prev_day / small_n_models / few_past_events / midday_rb / wordplay)
    applies_to    点検する行の種類("judge" = 判断:、"avoid" = 避ける)
    patterns      その型の根拠を書いた行を見つける正規表現
    exempt        学びを正しく使っている行(「根拠にしない」など)を外す正規表現
    first_seen    最初に書いた日
    reconfirmed   再確認した日(first_seen を含めない)
    exceptions    当てはまらない場合の説明(人が読む)
    source        出所(文書名)
    stat_basis    統計の裏づけ(あれば)

点検の規則(check_lines):
    判断・避けるの行が台帳の型に当たり、かつ型と独立した根拠(予告・公約・機械割・稼働・
    台数の変化・RB判別機の自動候補・60日の基準など)を1つも含まないとき、その行を止める。
    「予告なし」のような打ち消しは独立した根拠と数えない。

使い方:
    venv\\Scripts\\python.exe -m backtest.lessons list
    venv\\Scripts\\python.exe -m backtest.lessons summary              # id と rule だけ(プロンプト用)
    venv\\Scripts\\python.exe -m backtest.lessons check document/reviews/2026-10-30-prediction.md
    venv\\Scripts\\python.exe -m backtest.lessons reconfirm L001 --date 2026-10-31 --source document/reviews/...
    venv\\Scripts\\python.exe -m backtest.lessons add --rule ... --basis-type ... --pattern ... --date ... --date ...
    venv\\Scripts\\python.exe -m backtest.lessons stats --month 2026-11  # 止めた・通した・再確認の回数
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LESSONS_PATH = ROOT / "document" / "registry" / "LESSONS.jsonl"
# freeze-doc が止めた・--allow で通した記録。dry-run では書かない。
GATE_LOG_PATH = ROOT / "document" / "registry" / "LESSON_GATE_LOG.jsonl"

KINDS = ("judge", "avoid")
# 台帳の型と独立した根拠。これを1つでも含む行は止めない(判断の主が別にあるため)。
INDEPENDENT_BASIS = re.compile(
    r"予告|公約|先バレ|取材|来店|イベント|周年|機械割|稼働|打たれ|増台|減台|入替|入れ替え|新台|撤去|鉄台"
    r"|RB比|RB判別|自動候補|rb_candidates|term60|直近60日|60日平均|基準"
)
# 「予告なし」「イベント登録なし」は根拠ではない
_NEGATED_BASIS = re.compile(
    r"(予告|イベント(日|登録)?|取材)\s*(は|も|・)?\s*(なし|無し|ない|なく|がない|がなく|が無い|が無く|登録なし)"
)
_ID = re.compile(r"^L(\d{3,})$")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


# ---------------------------------------------------------------- 台帳


def load(path: Path = LESSONS_PATH) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} {n}行目が JSON でない: {exc}") from exc
    return out


def save(lessons: list[dict], path: Path = LESSONS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lessons), encoding="utf-8")


def next_id(lessons: list[dict]) -> str:
    nums = [int(m.group(1)) for x in lessons if (m := _ID.match(x["id"]))]
    return "L%03d" % (max(nums, default=0) + 1)


def _check_date(d: str) -> str:
    datetime.strptime(d, "%Y-%m-%d")
    return d


def add(
    lessons: list[dict],
    rule: str,
    basis_type: str,
    patterns: list[str],
    dates: list[str],
    source: str,
    applies_to: list[str] | None = None,
    exempt: list[str] | None = None,
    exceptions: list[str] | None = None,
    stat_basis: str = "",
) -> dict:
    """台帳に1件足す。確認日2つ以上か統計の裏づけが無いものは拒否する。"""
    dates = sorted({_check_date(d) for d in dates})
    if not dates:
        raise ValueError("確認した日(--date)が1つ以上必要")
    if len(dates) < 2 and not stat_basis:
        raise ValueError("登録は2回以上確認したもの、または統計の裏づけ(--stat-basis)があるものだけ")
    if not patterns:
        raise ValueError("検出用の --pattern が1つ以上必要")
    for p in patterns + (exempt or []):
        re.compile(p)
    kinds = applies_to or list(KINDS)
    if set(kinds) - set(KINDS):
        raise ValueError(f"applies_to は {KINDS} のみ")
    rec = {
        "id": next_id(lessons),
        "rule": rule,
        "basis_type": basis_type,
        "applies_to": kinds,
        "patterns": patterns,
        "exempt": exempt or [],
        "first_seen": dates[0],
        "reconfirmed": dates[1:],
        "exceptions": exceptions or [],
        "source": source,
        "stat_basis": stat_basis,
    }
    lessons.append(rec)
    return rec


def find(lessons: list[dict], lesson_id: str) -> dict:
    for x in lessons:
        if x["id"] == lesson_id:
            return x
    raise ValueError(f"台帳に無い id: {lesson_id}")


def reconfirm(lessons: list[dict], lesson_id: str, date: str, source: str = "") -> bool:
    """再確認の日付を足す。同じ日は二重に数えない(False を返す)。"""
    rec = find(lessons, lesson_id)
    date = _check_date(date)
    if date == rec["first_seen"] or date in rec["reconfirmed"]:
        return False
    rec["reconfirmed"] = sorted(rec["reconfirmed"] + [date])
    if source:
        rec.setdefault("reconfirm_sources", {})[date] = source
    return True


def summary_lines(lessons: list[dict]) -> list[str]:
    """プロンプトに渡す要約。id と rule だけ。"""
    return [f"- {x['id']}: {x['rule']}" for x in lessons]


# ---------------------------------------------------------------- 点検


def hits(line: str, kind: str, lessons: list[dict]) -> list[str]:
    """行が当たった学びの id。学びを正しく使っている行(exempt)は数えない。"""
    t = _norm(line)
    out = []
    for x in lessons:
        if kind not in x.get("applies_to", KINDS):
            continue
        if not any(re.search(p, t) for p in x["patterns"]):
            continue
        if any(re.search(p, t) for p in x.get("exempt", [])):
            continue
        out.append(x["id"])
    return out


def has_independent_basis(line: str) -> bool:
    return bool(INDEPENDENT_BASIS.search(_NEGATED_BASIS.sub(" ", _norm(line))))


def check_lines(lines: list[tuple[str, str, str]], lessons: list[dict]) -> list[dict]:
    """(hall, kind, line) の並びから、台帳の型だけを根拠にした行を返す。"""
    out = []
    for hall, kind, line in lines:
        ids = hits(line, kind, lessons)
        if ids and not has_independent_basis(line):
            out.append({"hall": hall, "kind": kind, "line": line.strip(), "lessons": ids})
    return out


def parse_allow(values: list[str] | None, lessons: list[dict]) -> dict[str, str]:
    """--allow L003:理由 を {id: 理由} にする。理由の無い許可は認めない。"""
    out = {}
    for v in values or []:
        lid, sep, reason = v.partition(":")
        lid = lid.strip()
        if not sep or not reason.strip():
            raise ValueError(f"--allow は L003:理由 の形で書く: {v}")
        find(lessons, lid)
        out[lid] = reason.strip()
    return out


def log_gate(events: list[dict], path: Path = GATE_LOG_PATH) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def _gate_log(path: Path = GATE_LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def stats(lessons: list[dict], month: str | None = None, log_path: Path = GATE_LOG_PATH) -> list[dict]:
    """学びごとに、凍結で止めた回数・--allow で通した回数・再確認した回数(月で絞れる)。

    止めた・通した回数は、行の数ではなく「凍結の実行×ホール」の単位で数える
    (同じ文書を直して2回凍結にかけて2回止まれば2回と数える)。
    """
    events = [e for e in _gate_log(log_path) if not month or e["target_date"].startswith(month.replace("-", ""))]
    out = []
    for x in lessons:
        dates = [x["first_seen"]] + x["reconfirmed"]
        if month:
            dates = [d for d in dates if d.startswith(month)]
        mine = [e for e in events if e["lesson"] == x["id"]]
        out.append(
            {
                "id": x["id"],
                "rule": x["rule"],
                "blocked": len({(e["at"], e["hall"]) for e in mine if e["action"] == "blocked"}),
                "allowed": len({(e["at"], e["hall"]) for e in mine if e["action"] == "allowed"}),
                "reconfirmed": len(dates),
            }
        )
    return out


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="台帳を全件表示する")
    sub.add_parser("summary", help="id と rule だけを表示する(答え合わせのプロンプト用)")
    p_ck = sub.add_parser("check", help="予測文書の判断・避けるの行を台帳と照らす(凍結しない)")
    p_ck.add_argument("doc")
    p_rc = sub.add_parser("reconfirm", help="既知の学びを再確認した日を足す")
    p_rc.add_argument("lesson_id")
    p_rc.add_argument("--date", required=True)
    p_rc.add_argument("--source", default="")
    p_add = sub.add_parser("add", help="学びを登録する(2回以上の確認か統計の裏づけが必要)")
    p_add.add_argument("--rule", required=True)
    p_add.add_argument("--basis-type", required=True)
    p_add.add_argument("--pattern", action="append", required=True, dest="patterns")
    p_add.add_argument("--exempt", action="append", default=[])
    p_add.add_argument("--applies-to", action="append", choices=KINDS, dest="applies_to")
    p_add.add_argument("--date", action="append", default=[], dest="dates", help="確認した日(複数可)")
    p_add.add_argument("--exception", action="append", default=[], dest="exceptions")
    p_add.add_argument("--source", required=True)
    p_add.add_argument("--stat-basis", default="")
    p_st = sub.add_parser("stats", help="学びごとの止めた・通した・再確認の回数")
    p_st.add_argument("--month", help="YYYY-MM")
    args = parser.parse_args(argv)

    lessons = load()
    if args.cmd == "list":
        for x in lessons:
            print(f"{x['id']} [{x['basis_type']}] {x['rule']}")
            print(f"    初出 {x['first_seen']} / 再確認 {len(x['reconfirmed'])}回 / 出所 {x['source']}")
    elif args.cmd == "summary":
        print("\n".join(summary_lines(lessons)))
    elif args.cmd == "check":
        from backtest.prediction_ledger import decision_lines

        found = check_lines(decision_lines(Path(args.doc).read_text(encoding="utf-8")), lessons)
        for f in found:
            kind = "判断" if f["kind"] == "judge" else "避ける"
            print(f"止まる {f['hall']} [{kind}] {','.join(f['lessons'])}: {f['line']}")
        print(f"止まる行 {len(found)}件")
    elif args.cmd == "reconfirm":
        try:
            added = reconfirm(lessons, args.lesson_id, args.date, args.source)
        except ValueError as exc:
            p_rc.error(str(exc))
        save(lessons)
        print(f"{args.lesson_id}: {'再確認を追加' if added else '同じ日は登録済み'} {args.date}")
    elif args.cmd == "add":
        try:
            rec = add(
                lessons,
                args.rule,
                args.basis_type,
                args.patterns,
                args.dates,
                args.source,
                applies_to=args.applies_to,
                exempt=args.exempt,
                exceptions=args.exceptions,
                stat_basis=args.stat_basis,
            )
        except (ValueError, re.error) as exc:
            p_add.error(str(exc))
        save(lessons)
        print(f"登録 {rec['id']}: {rec['rule']}")
    elif args.cmd == "stats":
        print("| id | 学び | 止めた | 通した | 再確認 |")
        print("|---|---|---:|---:|---:|")
        for s in stats(lessons, args.month):
            print(f"| {s['id']} | {s['rule']} | {s['blocked']} | {s['allowed']} | {s['reconfirmed']} |")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
