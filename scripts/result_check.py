"""結果ツイートとの照合: 答え合わせの二段階目(2026-10-30 作業4)。

なぜ要るか:
    結果ツイートの多くは営業日の翌日に出る(10月に紐付いた分はすべて翌日)。朝7時台の自動の答え合わせは
    それより先に書き終わるので、あとから結果が出ても答え合わせに戻らなかった。また、差し込んでいたのは
    slo_tokyo の速報だけで、台番号を書く他の結果アカウントは使っていなかった。

何をするか:
    1. 営業日のホールごとに、結果発表(取り込み済みの報告と、候補ツイートの画像)から台番号を集める。
       集め方は backtest.event_days._result_data と同じ(アカウントの扱うホール・22時以降の投稿・本文の日付とホール名)。
    2. 画像の誤った紐付け(別ホール・別日の画像。収集の約19%)を、画像ごとに当日の実在台と照らして除く。
       台番号の8割以上が当日そのホールに実在し、3台以上あるときだけ、その画像を使う。
    3. 凍結した予測(人の名指し・RB自動候補)の台・機種が、結果の台に含まれたかを数える。
       差枚では台単位の設定を判定できないので、それとは別の列として出す。
    4. 前日・前々日の答え合わせに「結果ツイートとの照合」節を追記する。イベント日なのに結果がまだなら
       「結果ツイート未着(waiting)」と書く(黙って省略しない)。人手の文書は末尾へ、自動下書きの日は
       `<日付>-answercheck-addendum.md` へ(自動下書きは朝に作り直されるため)。

結果の台は「発信者が結果として挙げた台」で、ホールの公表とは限らない。的中の数は参考で、設定の確定ではない。

使い方:
    venv\\Scripts\\python.exe scripts\\result_check.py --days 20261026 20261027 --dry-run
    venv\\Scripts\\python.exe scripts\\result_check.py                 # 前日・前々日(朝の処理と同じ)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import event_days  # noqa: E402
from backtest.prediction_ledger import HALL_KEY  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")
DB_DIR = ROOT / "db"
REVIEWS = ROOT / "document" / "reviews"
PREDICTIONS = ROOT / "backtest" / "predictions"
ANALYSIS_DB = Path(event_days.RESULT_DB)
STATE_DB = Path(event_days.STATE_DB)
EVENT_LEDGER = Path(event_days.LEDGER)
# 照合のたびに1行。採点表(scoreboard)が台単位の的中を別系列として読むための記録。
CHECK_LOG = ROOT / "document" / "registry" / "RESULT_CHECKS.jsonl"

MIN_IMAGE_NUMBERS = 3
MIN_EXIST_RATE = 0.8
AUTO_DOC_MARK = "<!-- auto-morning-docs -->"
PICK_LABELS = {"units": "推した台", "jug_units": "ジャグラー候補", "models": "推した機種", "avoid_models": "避ける機種"}


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def day_units(hall: str, day: str, db_dir: Path = DB_DIR) -> dict[int, str]:
    """当日の {台番号: 機種名}。DBが無い・当日が無ければ空。"""
    path = db_dir / ("%s.db" % hall)
    if not path.exists():
        return {}
    with _ro(path) as con:
        return {
            int(n): name
            for n, name in con.execute(
                "SELECT machine_number, machine_name FROM machine_detailed_results WHERE date = ?", (day,)
            )
        }


def image_numbers(state_db: Path, tweet_ids: list[str]) -> dict[str, dict]:
    """候補ツイートの画像ごとの {image_path: {"tweet_id", "handle", "numbers"}}。"""
    if not tweet_ids or not state_db.exists():
        return {}
    out: dict[str, dict] = {}
    with _ro(state_db) as con:
        marks = ",".join("?" * len(tweet_ids))
        for tweet_id, handle, image, number in con.execute(
            "SELECT tweet_id, handle, image_path, machine_number FROM extraction_entries "
            "WHERE tweet_id IN (%s) AND machine_number IS NOT NULL" % marks,
            tweet_ids,
        ):
            try:
                n = int(str(number).strip())
            except ValueError:
                continue
            rec = out.setdefault(image, {"tweet_id": str(tweet_id), "handle": handle, "numbers": set()})
            rec["numbers"].add(n)
    return out


def accept_image(numbers: set[int], units: dict[int, str]) -> bool:
    """画像の台番号の8割以上が当日そのホールに実在し、3台以上あるか(別ホール・別日の画像を除く)。"""
    if len(numbers) < MIN_IMAGE_NUMBERS or not units:
        return False
    return sum(1 for n in numbers if n in units) / len(numbers) >= MIN_EXIST_RATE


def _report_source(con: sqlite3.Connection, report_id: str) -> str:
    for table in ("external_result_reports", "poster_result_reports"):
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        row = con.execute("SELECT source FROM %s WHERE report_id = ?" % table, (report_id,)).fetchone()
        if row:
            return row[0]
    return "?"


def collect(
    hall: str, day: str, analysis_db: Path = ANALYSIS_DB, state_db: Path = STATE_DB, db_dir: Path = DB_DIR
) -> dict:
    """営業日・ホールの結果発表と、結果の台番号を集める。"""
    reports, candidates = event_days._result_data(str(analysis_db), str(state_db), hall, day)
    units = day_units(hall, day, db_dir)
    names = sorted(set(units.values()))
    result_units: dict[int, set[str]] = {}
    result_models: dict[str, set[str]] = {}  # {DBの機種名: {粒度}}
    sources: list[dict] = []

    def add_units(nums, handle):
        for n in nums:
            if n in units:
                result_units.setdefault(n, set()).add(handle)

    if reports and analysis_db.exists():
        with _ro(analysis_db) as con:
            for r in reports:
                rid = r["report_id"]
                handle = _report_source(con, rid)
                before_u, before_m = len(result_units), len(result_models)
                add_units(
                    [
                        int(n)
                        for (n,) in con.execute(
                            "SELECT machine_number FROM external_result_machines WHERE report_id = ?", (rid,)
                        )
                    ],
                    handle,
                )
                for gran, name, lo, hi in _report_models(con, rid):
                    if lo is not None and hi is not None:
                        add_units(range(min(lo, hi), max(lo, hi) + 1), handle)  # 並びの範囲(本文に台番号)
                    elif name:
                        for real in _resolve_models(name, names):
                            result_models.setdefault(real, set()).add(gran)
                sources.append(
                    {
                        "handle": handle,
                        "url": r.get("tweet_url") or "",
                        "units": len(result_units) - before_u,
                        "models": len(result_models) - before_m,
                        "kind": "報告",
                    }
                )
    rejected = []
    tweet_ids = [str(r["report_id"]) for r in reports] + [c["tweet_id"] for c in candidates]
    for image, rec in sorted(image_numbers(state_db, tweet_ids).items()):
        if not accept_image(rec["numbers"], units):
            rejected.append({"image": Path(image).name, "handle": rec["handle"], "n": len(rec["numbers"])})
            continue
        add_units(rec["numbers"], rec["handle"])
        sources.append(
            {"handle": rec["handle"], "url": rec["tweet_id"], "units": len(rec["numbers"]), "models": 0, "kind": "画像"}
        )
    linked = bool(reports or result_units)
    return {
        "hall": hall,
        "day": day,
        "status": "linked" if linked else ("candidates" if candidates else "waiting"),
        "sources": sources,
        "units": {n: sorted(h) for n, h in sorted(result_units.items())},
        "models": {m: sorted(g) for m, g in sorted(result_models.items())},
        "rejected_images": rejected,
        "day_units": units,
    }


def _report_models(con: sqlite3.Connection, report_id: str) -> list[tuple[str, str, int | None, int | None]]:
    """報告の (粒度, 機種名, 台番号の下限, 上限)。slokotae7 等の本文と、slo_tokyo の速報の両方。"""
    out = []
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "external_result_models" in tables:
        out += [
            ((g or "").strip(), n, lo, hi)
            for g, n, lo, hi in con.execute(
                "SELECT granularity, model_name, number_from, number_to FROM external_result_models WHERE report_id = ?",
                (report_id,),
            )
        ]
    if "poster_result_models" in tables:
        for g, parts in con.execute(
            "SELECT granularity, model_parts FROM poster_result_models WHERE report_id = ?", (report_id,)
        ):
            for part in json.loads(parts or "[]"):
                out.append(((g or "").strip(), part, None, None))
    return out


def _resolve_models(name: str, names: list[str]) -> list[str]:
    """発信者の機種表記(「L無職転生・SBJ」のような連記を含む)を、当日の機種名に当てる。当たらなければ空。"""
    from backtest.model_alias import resolve_part
    from backtest.result_corpus import resolve_poster_model

    by_name = {n: [] for n in names}
    out = []
    for part in [p for p in name.replace("／", "・").split("・") if p.strip()]:
        real = resolve_poster_model(part, by_name)
        if real:
            out.append(real)
            continue
        r = resolve_part(part, names)
        if r["status"] == "ok" and len(r["names"]) == 1:
            out.append(r["names"][0])
    return out


AUTO_LABELS = {"rbauto": "RB自動候補", "rbdip": "凹み戻り", "rbdipctrl": "凹み戻りの対照"}


def frozen_picks(day: str, key: str, pred_dir: Path = PREDICTIONS) -> list[tuple[str, dict]]:
    """(ラベル, picks) の並び。人の凍結(改訂を含む)と RB 自動候補。"""
    out = []
    for path in sorted(pred_dir.glob("%s__%s*.json" % (day, key))):
        suffix = path.stem[len("%s__%s" % (day, key)) :]
        if suffix and not suffix.startswith("__"):
            continue  # kamata7 と kamata7x のような前方一致を除く
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        tag = suffix.lstrip("_")
        out.append((AUTO_LABELS.get(tag, tag or "人の予測"), data.get("picks") or {}))
    return out


def score_picks(found: dict, picks: dict) -> dict:
    """名指しのうち、結果に入った数。台は結果の台、機種は「結果の機種か、結果の台を1台以上含むか」。"""
    hit_units = set(found["units"])
    hit_models = set(found.get("models") or {})
    by_model: dict[str, list[int]] = {}
    for n, name in found["day_units"].items():
        by_model.setdefault(name, []).append(n)
    out = {}
    for k in ("units", "jug_units"):
        named = [int(u) for u in picks.get(k) or []]
        if named:
            out[k] = {"named": len(named), "hit": sorted(u for u in named if u in hit_units)}
    for k in ("models", "avoid_models"):
        named = list(picks.get(k) or [])
        if named:
            out[k] = {
                "named": len(named),
                "hit": [m for m in named if m in hit_models or any(n in hit_units for n in by_model.get(m, []))],
            }
    return out


def model_base_rate(found: dict) -> tuple[int, int] | None:
    """(当日の機種数, 結果の台か結果の機種を含む機種数)。結果が無ければ None。"""
    names = set(found["day_units"].values())
    if not names or not (found["units"] or found.get("models")):
        return None
    hit = {found["day_units"][n] for n in found["units"] if n in found["day_units"]} | set(found.get("models") or {})
    return len(names), len(hit & names)


def render(found: dict, scored: list[tuple[str, dict]], checked_at: str) -> list[str]:
    lines = ["## 結果ツイートとの照合: %s" % found["hall"], ""]
    if found["status"] != "linked":
        state = (
            "候補ツイートはあるが台番号を確かめられない"
            if found["status"] == "candidates"
            else "結果ツイート未着(waiting)"
        )
        lines.append("- %s。確認 %s。結果が出たら次の朝に追記する。" % (state, checked_at))
        return lines
    lines.append(
        "- 結果の台 %d台(発信者が結果として挙げた台。ホール公表とは限らない)。確認 %s。"
        % (len(found["units"]), checked_at)
    )
    for s in found["sources"]:
        if s["kind"] == "報告":
            lines.append(
                "  - 報告 %s: 本文の台 %d・機種 %d %s" % (s["handle"], s["units"], s.get("models", 0), s["url"])
            )
        else:
            lines.append("  - 画像 %s: %d台 %s" % (s["handle"], s["units"], s["url"]))
    if found["rejected_images"]:
        shown = "、".join("%s(%s, %d台)" % (r["image"], r["handle"], r["n"]) for r in found["rejected_images"][:4])
        lines.append(
            "  - 除外した画像 %d枚(台番号の8割未満しか当日このホールに無い。別ホール・別日の画像の疑い): %s"
            % (len(found["rejected_images"]), shown)
        )
    if found["units"]:
        names: dict[str, int] = {}
        for n in found["units"]:
            name = found["day_units"].get(n, "?")
            names[name] = names.get(name, 0) + 1
        top = sorted(names.items(), key=lambda kv: -kv[1])[:8]
        lines.append("- 結果の台の機種: " + "、".join("%s %d台" % kv for kv in top))
    if found.get("models"):
        lines.append(
            "- 結果の機種(本文の全台系・機種単位): "
            + "、".join("%s(%s)" % (m, "・".join(g) or "?") for m, g in found["models"].items())
        )
    base = model_base_rate(found)
    if base:
        lines.append("- 機種の基準率: 当日の%d機種のうち%d機種に結果あり。推した機種の的中はこれと比べて読む。" % base)
    if not scored:
        lines.append("- 凍結した予測なし。")
    for label, s in scored:
        if not s:
            continue
        parts = []
        for k in ("units", "jug_units", "models", "avoid_models"):
            if k in s:
                hit = s[k]["hit"]
                tail = "(" + "・".join(map(str, hit)) + ")" if hit else ""
                parts.append("%s %d/%d%s" % (PICK_LABELS[k], len(hit), s[k]["named"], tail))
        lines.append("- %s: %s" % (label, " / ".join(parts)))
    if any("avoid_models" in s for _, s in scored):
        lines.append("- 避ける機種の数字は、避けた機種に結果の台が入った数(少ないほど避けて正解)。")
    return lines


def marker(found: dict) -> str:
    return "<!-- resultcheck:%s:%s:%s:%d -->" % (found["hall"], found["day"], found["status"], len(found["units"]))


def append(found: dict, lines: list[str], reviews_dir: Path = REVIEWS) -> Path | None:
    """答え合わせへ追記する。同じ状態(同じ台数)は二度書かない。"""
    ds = found["day"]
    dashed = "%s-%s-%s" % (ds[:4], ds[4:6], ds[6:])
    main = reviews_dir / ("%s-answercheck.md" % dashed)
    side = reviews_dir / ("%s-answercheck-addendum.md" % dashed)
    main_text = main.read_text(encoding="utf-8") if main.exists() else ""
    target = main if main_text and AUTO_DOC_MARK not in main_text[:400] else side
    mark = marker(found)
    if any(p.exists() and mark in p.read_text(encoding="utf-8") for p in (main, side)):
        return None
    block = "\n".join([lines[0], "", mark, "", *lines[2:]]) + "\n"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    fresh = not target.exists()
    with target.open("a", encoding="utf-8") as fh:
        fh.write(("# %s 答え合わせ（遡及の追記）\n\n" % dashed) if fresh else "\n")
        fh.write(block)
    return target


def halls_for(
    day: str, pred_dir: Path = PREDICTIONS, event_ledger: Path = EVENT_LEDGER, db_dir: Path = DB_DIR
) -> dict[str, bool]:
    """{ホール: イベント日か}。イベント日のホールと、凍結した予測のあるホール(DBがあるもの)。"""
    out: dict[str, bool] = {}
    for hall, d in event_days._event_groups(str(event_ledger)):
        if d == day:
            out[hall] = True
    keys = {v: k for k, v in HALL_KEY.items()}
    for path in pred_dir.glob("%s__*.json" % day):
        hall = keys.get(path.stem.split("__")[1])
        if hall:
            out.setdefault(hall, False)
    return {h: ev for h, ev in out.items() if (db_dir / ("%s.db" % h)).exists()}


def lines_for_facts(hall: str, day: str) -> list[str]:
    """朝の機械集計に差し込む短い版。結果が無ければ空(機械集計を膨らませない)。"""
    try:
        found = collect(hall, day)
    except sqlite3.Error, OSError:
        return []
    if found["status"] != "linked" or not found["units"]:
        return []
    scored = [(label, score_picks(found, p)) for label, p in frozen_picks(day, HALL_KEY.get(hall, hall))]
    body = render(found, scored, "朝の集計時")
    return ["#### 結果ツイートの台(機械照合。発信者の結果でホール公表とは限らない)", "", *body[2:]]


def run(
    days: list[str],
    dry_run: bool = False,
    reviews_dir: Path = REVIEWS,
    log_path: Path = CHECK_LOG,
    collect_fn=collect,
    halls_fn=halls_for,
    picks_fn=frozen_picks,
) -> list[str]:
    checked_at = datetime.now(JST).isoformat(timespec="seconds")
    msgs = []
    for day in days:
        for hall, is_event in sorted(halls_fn(day).items()):
            found = collect_fn(hall, day)
            if found["status"] != "linked" and not is_event:
                continue  # イベントの無い日の未着は書かない(毎日全ホールの「未着」で埋まるため)
            scored = [(label, score_picks(found, p)) for label, p in picks_fn(day, HALL_KEY.get(hall, hall))]
            lines = render(found, scored, checked_at)
            if dry_run:
                msgs.append("\n".join(lines))
                continue
            path = append(found, lines, reviews_dir)
            if path is None:
                continue
            msgs.append("追記 %s %s → %s" % (day, hall, path.name))
            rec = {
                "checked_at": checked_at,
                "hall": hall,
                "business_date": day,
                "status": found["status"],
                "result_units": sorted(found["units"]),
                "sources": [s["handle"] for s in found["sources"]],
                "scores": dict(scored),
            }
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return msgs


def default_days(today: str) -> list[str]:
    d = datetime.strptime(today, "%Y%m%d")
    return [(d - timedelta(days=k)).strftime("%Y%m%d") for k in (2, 1)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", nargs="*", help="YYYYMMDD(省略時は前日・前々日)")
    parser.add_argument("--today", default=datetime.now(JST).strftime("%Y%m%d"))
    parser.add_argument("--dry-run", action="store_true", help="追記せず、書く内容を表示する")
    args = parser.parse_args(argv)
    for m in run(args.days or default_days(args.today), dry_run=args.dry_run):
        print(m)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
