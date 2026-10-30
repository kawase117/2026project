"""示唆続行台を営業中に拾う: クイック収集の回転数から、閉店時に7,000Gへ届きそうなAT台を凍結して翌朝採点する
(2026-10 振り返り 作業6)。

なぜ見るか:
    作業5(backtest.continuation_scan)で、AT機で7,000G以上回った台は、差枚がマイナスでも結果ツイートに
    入りやすいと分かった。ただし7,000G到達は閉店後にしか確定しない。目的は高設定にいち早く座ることなので、
    営業中のクイック収集(scraper/realtime の snapshots)から、昼過ぎの時点でペースに乗ったAT台を拾う。

何をするか:
    - ペース台: 開店10:00からの経過時間で、回転数が「8,000G × 経過 ÷ 13時間」以上の台
      (既存の運用、メモ quick-scrape-rb-models-only。全ホール23:00閉店で統一)。AT機だけを対象にし、
      ジャグラー・新台(導入0〜6日)は外す。
    - 時刻は 13時・15時・17時の3点。各時刻の窓 [H時, H+2時) で最初のスナップショットを使う。
    - 凍結(freeze-due): クイック収集の直後に呼ぶ。窓の中で時刻ごとに1回だけ書く(上書きしない)。
    - 採点(score-due): 翌朝、閉店時の実績(ホールDB)で
        (a) 7,000G到達の割合 − 同じ日・同じ機種のペース外の台の割合(%ポイント)
        (b) 結果ツイートに入った割合 − 同じ比較(AT台が結果に挙がった日だけ)
        (c) 閉店時の差枚 − 同じ比較
        (3) その時刻から座った場合の残りの差枚(閉店時 − 収集時点。収集時点の差枚がある取得元だけ)
      比較の相手は、その時点で回転数が取れていたペース外のAT台。機種×日の層で、ペース台の台数で重みづけする。
    - 遡及(retro): 過去のスナップショットで同じ計算をして報告する。参考扱いで、凍結も採点表への反映もしない。

注意:
    - 蒲田7・蒲田1はクイック収集の対象外(2026-10 時点)。収集が増えれば同じ処理で回る。
    - 蒲田7は作業5で土日・イベント日の比が弱かった(1.17)ので、SPLIT_HALLS のホールは平日と分けて系列にする。
    - 楽園(サイトセブン)のクイック収集は、RB判別機種の台表で quick のスナップショットを書いたあと、凍結に使う回だけ
      追加段でAT機の台表とペース台のグラフ(差枚)を足し、mode=pace のスナップショットを書く(2026-10-31〜、
      scraper.realtime.run の site_pace_keys がこのモジュールと同じ判定で選ぶ)。load_snapshots は pace を直前の
      quick と置き換える。追加段が失敗しても quick は残るので、失うのはAT機の台と差枚だけ。
    - DMM系(ヒロキ)はAT機の回転数が取れない台が多い。回転数の無い台はペース台にも比較の相手にも入れない。
    - (3) はヒロキ(DMMの推定差枚)と、2026-10-31 以降の楽園(ペース台のグラフ)で出る。ダイデータは差枚を取らない。

使い方:
    venv\\Scripts\\python.exe -m backtest.continuation_pace freeze-due            # クイック収集の直後
    venv\\Scripts\\python.exe -m backtest.continuation_pace score-due             # 朝(scripts/run_morning.py)
    venv\\Scripts\\python.exe -m backtest.continuation_pace show --date 20261030  # 答え合わせ用の一覧
    venv\\Scripts\\python.exe -m backtest.continuation_pace retro --since 20261001 --out path.md
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from backtest.continuation_scan import AT_TYPES, NEW_DAYS, busy_dates, load_labels
from scraper.realtime.schema import JST

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "db"
SNAPSHOT_DIR = ROOT / "scraper" / "realtime" / "output" / "snapshots"
FROZEN_DIR = Path(__file__).resolve().parent / "continuation_pace"

# スナップショットのホール名 → (ホールDBの名前, ファイル名の短縮名)。西口は収集側で2通りの名前がある。
HALLS = {
    "楽園蒲田店": ("楽園蒲田店", "rakuen"),
    "みとや大森町店": ("みとや大森町店", "mitoya"),
    "ヒロキ東口店": ("ヒロキ東口店", "hiroki"),
    "ヒロキMAX蒲田店": ("ヒロキMAX蒲田店", "hiroki_max"),
    "ヒロキ蒲田西口店": ("ヒロキ蒲田西口店", "hiroki_nishiguchi"),
    "ヒロキ西口店": ("ヒロキ蒲田西口店", "hiroki_nishiguchi"),
    "マルハンメガシティ2000-蒲田7": ("マルハンメガシティ2000-蒲田7", "kamata7"),
    "マルハンメガシティ2000-蒲田1": ("マルハンメガシティ2000-蒲田1", "kamata1"),
}
SPLIT_HALLS = ("マルハンメガシティ2000-蒲田7",)
CHECKPOINTS = (13, 15, 17)
WINDOW_HOURS = 2
OPEN_HOUR = 10
BUSINESS_HOURS = 13.0  # 10:00〜23:00
PACE_TARGET = 8000
REACH = 7000
MIN_ELAPSED = 1.0  # 開店直後の見込みは振れが大きいので使わない


# ---------------------------------------------------------------- スナップショット


def data_time(row: dict) -> datetime:
    """台の数字が何時点のものか。取得元の更新時刻があればそれを、無ければ観測時刻を使う。"""
    return datetime.fromisoformat(row.get("source_updated_at") or row["observed_at"])


def elapsed_hours(t: datetime) -> float:
    start = t.replace(hour=OPEN_HOUR, minute=0, second=0, microsecond=0)
    return (t - start).total_seconds() / 3600


def checkpoint_of(t: datetime) -> int | None:
    for h in CHECKPOINTS:
        if h <= t.hour < h + WINDOW_HOURS:
            return h
    return None


def load_snapshots(date: str, snapshot_dir: Path = SNAPSHOT_DIR) -> dict[str, list[tuple[datetime, Path, list[dict]]]]:
    """営業日 → {ホールDB名: [(データ時刻, ファイル, 行)...]}(時刻順)。

    楽園の追加段(mode=pace: RB機種の台表 + AT機の台表 + ペース台の差枚)は、直前の quick の行を置き換える。
    データ時刻は quick のものを保つ(窓の判定を追加段の有無で変えない)。追加段が無ければ quick をそのまま使う。
    """
    out: dict[str, list] = defaultdict(list)
    paces: list[tuple[str, Path]] = []
    for path in sorted(snapshot_dir.glob(f"*_{date}_*.jsonl")):
        snap_hall, _, mode = path.name.split(f"_{date}_")[0].rpartition("_")
        if snap_hall not in HALLS or mode not in ("quick", "full", "pace"):
            continue
        if mode == "pace":
            paces.append((snap_hall, path))
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            continue
        t = max(data_time(r) for r in rows)
        if t.strftime("%Y%m%d") != date:
            continue  # 収集に失敗して前の日の台表を書いたもの(2026-10-31 に楽園で発生)
        out[HALLS[snap_hall][0]].append((t, path, rows))
    for snap_hall, path in paces:
        stamp = path.name.split(f"_{date}_")[1]
        base = [
            i
            for i, (_, p, _) in enumerate(out.get(HALLS[snap_hall][0], []))
            if p.name.startswith(f"{snap_hall}_quick_{date}_") and p.name.split(f"_{date}_")[1] <= stamp
        ]
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if base and rows:
            snaps = out[HALLS[snap_hall][0]]
            i = max(base, key=lambda j: snaps[j][1].name)
            snaps[i] = (snaps[i][0], path, rows)
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return dict(out)


def pick_snapshot(snaps: list[tuple[datetime, Path, list[dict]]], hour: int):
    """時刻 hour の窓 [hour, hour+2) に入る最初のスナップショット。"""
    for item in snaps:
        if checkpoint_of(item[0]) == hour:
            return item
    return None


# ---------------------------------------------------------------- ホールDB


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def hall_context(con: sqlite3.Connection, date: str) -> dict:
    """凍結に使う、前日までのDBの情報: AT機種・機種の初出日・台番号の最新の機種名。"""
    marks = ",".join("?" * len(AT_TYPES))
    sql = f"SELECT machine_name_normalized FROM machine_master WHERE game_type IN ({marks})"
    at = {n for (n,) in con.execute(sql, AT_TYPES)}
    first = dict(
        con.execute(
            "SELECT machine_name, MIN(date) FROM machine_detailed_results WHERE date < ? GROUP BY machine_name", (date,)
        )
    )
    last = con.execute("SELECT MAX(date) FROM machine_detailed_results WHERE date < ?", (date,)).fetchone()[0]
    layout = {}
    if last:
        layout = {
            int(n): name
            for n, name in con.execute(
                "SELECT machine_number, machine_name FROM machine_detailed_results WHERE date = ?", (last,)
            )
        }
    return {"at": at, "first": first, "layout": layout}


def close_rows(con: sqlite3.Connection, date: str) -> dict[int, dict]:
    """閉店時の実績: 台番号 → 機種・回転数・差枚。"""
    return {
        int(n): {"model": name, "games": g, "diff": d}
        for n, name, g, d in con.execute(
            "SELECT machine_number, machine_name, games_normalized, diff_coins_normalized "
            "FROM machine_detailed_results WHERE date = ?",
            (date,),
        )
    }


# ---------------------------------------------------------------- ペース台


def _games_known(row: dict) -> bool:
    g = row.get("games")
    if g is None:
        return False
    # DMM系は回転数が取れないと 0 のまま当たりだけ付く。当たりのある 0G は欠損として扱う
    return not (g == 0 and any(row.get(k) for k in ("bb", "rb", "at_first_hits")))


def pace_units(rows: list[dict], ctx: dict, date: str, t: datetime, pace_target: int = PACE_TARGET) -> dict:
    """スナップショットの行から、対象のAT台(回転数の取れた台)とペースの判定を作る。"""
    elapsed = elapsed_hours(t)
    line = pace_target * elapsed / BUSINESS_HOURS
    units, skipped = [], defaultdict(int)
    day = datetime.strptime(date, "%Y%m%d")
    for r in rows:
        # 機種は前日のDBの配置を正とする(スナップショットの機種名は略称のことがある)
        model = ctx["layout"].get(int(r["unit"])) or r.get("model")
        if model not in ctx["at"] or "ジャグラー" in (model or ""):
            skipped["AT機以外"] += 1
            continue
        first = ctx["first"].get(model)
        if r.get("is_new_machine") or first is None or (day - datetime.strptime(first, "%Y%m%d")).days <= NEW_DAYS:
            skipped["新台"] += 1
            continue
        if not _games_known(r):
            skipped["回転数なし"] += 1
            continue
        games = int(r["games"])
        units.append(
            {
                "unit": int(r["unit"]),
                "model": model,
                "games": games,
                "projected": round(games * BUSINESS_HOURS / elapsed),
                "pace": games >= line,
                "diff_at_obs": r.get("diff"),
            }
        )
    return {
        "elapsed_h": round(elapsed, 2),
        "pace_line_games": round(line),
        "units": sorted(units, key=lambda u: -u["games"]),
        "skipped": dict(skipped),
    }


def build_frozen(hall: str, date: str, hour: int, snap, ctx: dict, busy: bool, pace_target: int = PACE_TARGET):
    t, path, rows = snap
    if elapsed_hours(t) < MIN_ELAPSED:
        return None
    return {
        "hall": hall,
        "target_date": date,
        "checkpoint_hour": hour,
        "data_time": t.isoformat(),
        "snapshot_file": path.name,
        "pace_target": pace_target,
        "reach": REACH,
        "busy": busy,
        **pace_units(rows, ctx, date, t, pace_target),
        "result": None,
    }


# ---------------------------------------------------------------- 採点


def _mean(values) -> float | None:
    v = [float(x) for x in values if x is not None]
    return statistics.fmean(v) if v else None


def _stratified_edge(units: list[dict], key: str) -> tuple[float | None, int]:
    """機種ごとに(ペース台の平均 − ペース外の平均)を取り、ペース台の台数で重みづけした平均。"""
    by_model: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        if u.get(key) is not None:
            by_model[u["model"]].append(u)
    num = weight = 0.0
    strata = 0
    for members in by_model.values():
        hi = [u[key] for u in members if u["pace"]]
        lo = [u[key] for u in members if not u["pace"]]
        if not hi or not lo:
            continue
        num += len(hi) * (statistics.fmean(hi) - statistics.fmean(lo))
        weight += len(hi)
        strata += 1
    return (num / weight if weight else None), strata


def score(frozen: dict, close: dict[int, dict], labels: set[int] | None) -> dict | None:
    """凍結した一覧を閉店時の実績で採点する。閉店時の実績が無ければ None。"""
    if not close:
        return None
    units = []
    for u in frozen["units"]:
        c = close.get(u["unit"])
        if not c or c["games"] is None or c["model"] != u["model"]:
            continue  # 入れ替え・欠損の台は数えない
        rest = None
        if c["diff"] is not None and u.get("diff_at_obs") is not None:
            rest = float(c["diff"]) - float(u["diff_at_obs"])
        units.append(
            {
                **u,
                "close_games": c["games"],
                "close_diff": c["diff"],
                "reached": 100.0 if c["games"] >= frozen["reach"] else 0.0,
                "rest_diff": rest,
                "rest_games": c["games"] - u["games"],
                "labeled": None if labels is None else (100.0 if u["unit"] in labels else 0.0),
            }
        )
    # その日の結果ツイートがAT台を1台も挙げていなければ、AT台について何も言っていないので使わない
    if not any(u["labeled"] for u in units):
        for u in units:
            u["labeled"] = None
    pace = [u for u in units if u["pace"]]
    reach_edge, strata = _stratified_edge(units, "reached")
    result_edge, result_strata = _stratified_edge(units, "labeled")
    diff_edge, _ = _stratified_edge(units, "close_diff")
    eventual = [u for u in units if u["reached"]]
    rests = [u["rest_diff"] for u in pace if u["rest_diff"] is not None]
    return {
        "n_pace": len(pace),
        "n_ctrl": len(units) - len(pace),
        "strata": strata,
        "pace_reach_rate": _mean(u["reached"] for u in pace),
        "ctrl_reach_rate": _mean(u["reached"] for u in units if not u["pace"]),
        "reach_edge": reach_edge,
        # 閉店時に7,000Gへ届いた台のうち、この時刻でペース台に挙がっていた割合(拾えた割合)
        "recall": _mean(100.0 if u["pace"] else 0.0 for u in eventual),
        "n_reached": len(eventual),
        "result_edge": result_edge,
        "result_strata": result_strata,
        "pace_result_rate": _mean(u["labeled"] for u in pace),
        "diff_edge": diff_edge,
        "pace_diff_mean": _mean(u["close_diff"] for u in pace),
        "rest_diff_mean": _mean(rests),
        "rest_n": len(rests),
        "rest_positive": _mean(100.0 if r > 0 else 0.0 for r in rests),
        "rest_games_mean": _mean(u["rest_games"] for u in pace),
        "units": [
            {
                k: u[k]
                for k in ("unit", "model", "games", "close_games", "close_diff", "reached", "rest_diff", "labeled")
            }
            for u in pace
        ],
    }


# ---------------------------------------------------------------- 入出力


def frozen_path(hall: str, date: str, hour: int, frozen_dir: Path = FROZEN_DIR) -> Path:
    short = next(s for h, s in HALLS.values() if h == hall)
    return frozen_dir / f"{date}__{short}__{hour:02d}.json"


def _is_busy(date: str, busy: set[str]) -> bool:
    return date in busy or datetime.strptime(date, "%Y%m%d").weekday() >= 5


def freeze_due(
    now: datetime | None = None,
    snapshot_dir: Path = SNAPSHOT_DIR,
    frozen_dir: Path = FROZEN_DIR,
    db_dir: Path = DB_DIR,
) -> list[Path]:
    """当日のスナップショットのうち、まだ凍結していない時刻の窓に入ったものを凍結する。

    窓の締め切り(H+2時)を過ぎてからは凍結しない(後から書いた一覧が事前の判断に混ざらないため)。
    """
    now = (now or datetime.now(JST)).astimezone(JST)
    date = now.strftime("%Y%m%d")
    written = []
    for hall, snaps in load_snapshots(date, snapshot_dir).items():
        db = db_dir / f"{hall}.db"
        if not db.exists():
            continue
        with closing(_ro(db)) as con:
            ctx = hall_context(con, date)
        busy = _is_busy(date, busy_dates(hall))
        for hour in CHECKPOINTS:
            path = frozen_path(hall, date, hour, frozen_dir)
            snap = pick_snapshot(snaps, hour)
            if path.exists() or snap is None or now.hour >= hour + WINDOW_HOURS:
                continue
            frozen = build_frozen(hall, date, hour, snap, ctx, busy)
            if frozen is None:
                continue
            frozen["frozen_at"] = now.isoformat(timespec="seconds")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(frozen, stream, ensure_ascii=False, indent=1)
            written.append(path)
    return written


def score_due(frozen_dir: Path = FROZEN_DIR, db_dir: Path = DB_DIR) -> list[Path]:
    """未採点の凍結を、閉店時の実績が入っていれば採点する。採点済みは書き換えない。"""
    done = []
    labels: dict[str, dict[str, set[int]]] = {}
    for path in sorted(frozen_dir.glob("*__*__*.json")) if frozen_dir.exists() else []:
        frozen = json.loads(path.read_text(encoding="utf-8"))
        if frozen.get("result") is not None:
            continue
        hall, date = frozen["hall"], frozen["target_date"]
        with closing(_ro(db_dir / f"{hall}.db")) as con:
            close = close_rows(con, date)
        if hall not in labels:
            labels[hall] = load_labels(hall)
        result = score(frozen, close, labels[hall].get(date))
        if result is None:
            continue
        frozen["result"] = result
        frozen["scored_at"] = datetime.now(JST).isoformat(timespec="seconds")
        path.write_text(json.dumps(frozen, ensure_ascii=False, indent=1), encoding="utf-8")
        done.append(path)
    return done


def load_scored(frozen_dir: Path = FROZEN_DIR, since: str | None = None) -> list[dict]:
    out = []
    for path in sorted(frozen_dir.glob("*__*__*.json")) if frozen_dir.exists() else []:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("result") and not (since and obj["target_date"] < since):
            out.append(obj)
    return out


def series_label(frozen: dict) -> str:
    label = f"{frozen['checkpoint_hour']}時"
    if frozen["hall"] in SPLIT_HALLS:
        label += "・土日イベント" if frozen["busy"] else "・平日"
    return label


def _f(v, fmt):
    return "—" if v is None else format(v, fmt)


def render_show(items: list[dict]) -> str:
    """答え合わせ用: 前日のペース台が閉店時に7,000Gへ届いたか、結果に入ったか。"""
    out = []
    for f in sorted(items, key=lambda x: (x["hall"], x["checkpoint_hour"])):
        res = f.get("result")
        head = f"### {f['hall']} {f['checkpoint_hour']}時(データ {f['data_time'][11:16]}、ペース線 {f['pace_line_games']:,}G)"
        if not res:
            out += [head, "", f"未採点(ペース台 {sum(u['pace'] for u in f['units'])}台)。", ""]
            continue
        out += [
            head,
            "",
            f"ペース台 {res['n_pace']}台 / 7,000G到達 {_f(res['pace_reach_rate'], '.0f')}%"
            f"(同機種のペース外 {_f(res['ctrl_reach_rate'], '.0f')}%、差 {_f(res['reach_edge'], '+.0f')}pt)"
            f" / 拾えた割合 {_f(res['recall'], '.0f')}%(閉店時7,000G到達 {res['n_reached']}台のうち)"
            f" / 結果ツイート {_f(res['pace_result_rate'], '.0f')}%"
            f" / 残りの差枚 {_f(res['rest_diff_mean'], '+.0f')}枚({res['rest_n']}台)",
            "",
            "| 台 | 機種 | 時点G | 閉店G | 7,000G | 閉店差枚 | 残り差枚 | 結果 |",
            "|---:|---|---:|---:|---|---:|---:|---|",
        ]
        for u in res["units"]:
            lab = "—" if u["labeled"] is None else ("○" if u["labeled"] else "×")
            out.append(
                f"| {u['unit']} | {u['model']} | {u['games']:,} | {_f(u['close_games'], ',.0f')} | "
                f"{'○' if u['reached'] else '×'} | {_f(u['close_diff'], '+,.0f')} | {_f(u['rest_diff'], '+,.0f')} | {lab} |"
            )
        out.append("")
    return "\n".join(out) if out else "凍結したペース台の一覧が無い。"


# ---------------------------------------------------------------- 遡及(参考)


def retro(
    since: str, until: str, snapshot_dir: Path = SNAPSHOT_DIR, db_dir: Path = DB_DIR, pace_target: int = PACE_TARGET
) -> list[dict]:
    """過去のスナップショットで凍結と採点を再現する(ファイルは書かない)。"""
    out = []
    day, end = datetime.strptime(since, "%Y%m%d"), datetime.strptime(until, "%Y%m%d")
    labels: dict[str, dict[str, set[int]]] = {}
    busy: dict[str, set[str]] = {}
    while day <= end:
        date = day.strftime("%Y%m%d")
        for hall, snaps in load_snapshots(date, snapshot_dir).items():
            db = db_dir / f"{hall}.db"
            if not db.exists():
                continue
            with closing(_ro(db)) as con:
                ctx, close = hall_context(con, date), close_rows(con, date)
            if hall not in labels:
                labels[hall], busy[hall] = load_labels(hall), busy_dates(hall)
            for hour in CHECKPOINTS:
                snap = pick_snapshot(snaps, hour)
                frozen = snap and build_frozen(hall, date, hour, snap, ctx, _is_busy(date, busy[hall]), pace_target)
                if not frozen:
                    continue
                frozen["result"] = score(frozen, close, labels[hall].get(date))
                if frozen["result"]:
                    out.append(frozen)
        day += timedelta(days=1)
    return out


def summarize_retro(items: list[dict]) -> list[dict]:
    """ホール×時刻ごとに、差は日を1単位にした平均、率と残りの差枚は台を足し上げた値を出す。"""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for f in items:
        groups[(f["hall"], series_label(f))].append(f)
    rows = []
    for (hall, label), fs in sorted(groups.items()):
        res = [f["result"] for f in fs]
        units = [u for r in res for u in r["units"]]
        rests = [u["rest_diff"] for u in units if u["rest_diff"] is not None]
        rows.append(
            {
                "hall": hall,
                "label": label,
                "days": len(fs),
                "n_pace": sum(r["n_pace"] for r in res),
                "n_ctrl": sum(r["n_ctrl"] for r in res),
                "pace_reach_rate": _mean(u["reached"] for u in units),
                "reach_edge": _mean(r["reach_edge"] for r in res),
                "reach_edge_days": sum(r["reach_edge"] is not None for r in res),
                "recall": _mean(r["recall"] for r in res),
                "result_edge": _mean(r["result_edge"] for r in res),
                "result_days": sum(r["result_edge"] is not None for r in res),
                "diff_edge": _mean(r["diff_edge"] for r in res),
                "pace_diff_mean": _mean(u["close_diff"] for u in units),
                "rest_diff_mean": _mean(rests),
                "rest_n": len(rests),
                "rest_positive": _mean(100.0 if r > 0 else 0.0 for r in rests),
            }
        )
    return rows


def render_retro(rows: list[dict], since: str, until: str, pace_target: int) -> str:
    out = [
        f"# 示唆続行台のペース(遡及、{since}〜{until}、ペース線 {pace_target:,}G×経過÷13)",
        "",
        "**参考扱い**。過去のクイック収集で凍結と採点を再現した数字で、判定は11月の前向きの数字で行う。",
        "到達差・結果差・差枚差は「ペース台 − 同じ日・同じ機種のペース外の台」(機種×日の層、ペース台の台数で重みづけ)の日平均。"
        "拾えた割合は、閉店時に7,000Gへ届いた台のうち、その時刻でペース台だった割合の日平均。"
        "残りの差枚は、その時刻に座った場合の「閉店時の差枚 − 収集時点の差枚」の台平均(収集時点の差枚がある取得元だけ)。",
        "",
        "| ホール | 時刻 | 日数 | ペース台 | 対照 | 到達率 | 到達差(日数) | 拾えた割合 | 結果差(日数) | 差枚差 "
        "| ペース台の閉店差枚 | 残りの差枚(台) | 残り>0 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        out.append(
            f"| {r['hall']} | {r['label']} | {r['days']} | {r['n_pace']} | {r['n_ctrl']} | "
            f"{_f(r['pace_reach_rate'], '.0f')}% | {_f(r['reach_edge'], '+.0f')}pt ({r['reach_edge_days']}) | "
            f"{_f(r['recall'], '.0f')}% | {_f(r['result_edge'], '+.0f')}pt ({r['result_days']}) | "
            f"{_f(r['diff_edge'], '+.0f')} | {_f(r['pace_diff_mean'], '+.0f')} | "
            f"{_f(r['rest_diff_mean'], '+.0f')} ({r['rest_n']}) | {_f(r['rest_positive'], '.0f')}% |"
        )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze-due", help="当日のスナップショットで、まだ凍結していない時刻を凍結する")
    sub.add_parser("score-due", help="未採点の凍結を閉店時の実績で採点する")
    p_show = sub.add_parser("show", help="ある日のペース台と採点を表で出す(答え合わせ用)")
    p_show.add_argument("--date", required=True)
    p_retro = sub.add_parser("retro", help="過去のスナップショットで遡って計算する(参考、ファイルは書かない)")
    p_retro.add_argument("--since", required=True)
    p_retro.add_argument("--until", default=(datetime.now(JST) - timedelta(days=1)).strftime("%Y%m%d"))
    p_retro.add_argument("--pace-target", type=int, default=PACE_TARGET)
    p_retro.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.command == "freeze-due":
        for path in freeze_due():
            print(f"凍結 {path.name}")
    elif args.command == "score-due":
        for path in score_due():
            print(f"採点 {path.name}")
    elif args.command == "show":
        items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FROZEN_DIR.glob(f"{args.date}__*.json"))]
        print(render_show(items))
    elif args.command == "retro":
        rows = summarize_retro(retro(args.since, args.until, pace_target=args.pace_target))
        md = render_retro(rows, args.since, args.until, args.pace_target)
        print(md)
        if args.out:
            args.out.write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
