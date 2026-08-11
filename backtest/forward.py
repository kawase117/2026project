"""フォワードテスト: 未来日の選択を事前に凍結し、後から答え合わせする。

バックテストと決定的に違う点:
    バックテストは「過去データから見つけた仮説を過去データで確認する」自己参照から
    逃れられない。フォワードテストは、選択を **データが存在しない時点で** 確定させる。
    ここで出た結果だけが instinct の status を unverified から confirmed/refuted に
    動かす資格を持つ。

運用:
    1. 前日夜に plan-all を実行 → 全ルールの台リストが JSON に凍結される
       （result は null）。回すルールを人が選ばないのが要点。
    2. 当日は凍結された台にだけ座る。リストを見て選び直さない
    3. データ反映後に score を実行 → 同じファイルの result 欄が埋まる
       すでに result が入っているファイルは上書きしない（やり直しの禁止）
    4. 定期的に audit を実行し、実行記録が欠けた日が無いか確認する

使い方:
    # 日次（定時実行向け。--date 省略で翌日）
    venv\\Scripts\\python.exe -m backtest.forward plan-all
    # 実行記録の欠落・不整合の点検
    venv\\Scripts\\python.exe -m backtest.forward audit --from 20260801 --to 20260812
    # 単発（動作確認・個別ルールの手動凍結。RUNS には記録されない）
    venv\\Scripts\\python.exe -m backtest.forward plan backtest/prereg/xxx.json --date 20260801
    venv\\Scripts\\python.exe -m backtest.forward score backtest/forward/xxx__20260801.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

# 運用タイムゾーン。ホストのローカル設定に依存させない。
JST = ZoneInfo("Asia/Tokyo")

from backtest.prereg import PreRegistration
from backtest.run_backtest import (
    apply_eligibility,
    load_frame,
    restrict_to_current_machine,
    score_history,
    usable_models,
)

FORWARD_DIR = Path(__file__).resolve().parent / "forward"
PREREG_DIR = Path(__file__).resolve().parent / "prereg"
# plan 本体のダイジェストを追記専用で記録する台帳。plan JSON 自体が
# 書き換えられても、ここと突き合わせれば改ざんが検出できる。
LEDGER = FORWARD_DIR / "LEDGER.jsonl"
# plan-all の実行記録。「その日にどのルールをどう処理したか」を全件残す。
# LEDGER が残すのは *凍結できた* plan だけなので、あるルールの plan が
# 無い日について「エントリー日ではなかった」のか「回し忘れた」のか
# 「回したが履歴不足で落ちた」のかが LEDGER からは区別できない。
# フォワードテストの証拠価値は「負けそうな日を飛ばしていない」ことに
# 依存するため、飛ばした事実と理由もまた記録されていなければならない。
RUNS_LEDGER = FORWARD_DIR / "RUNS.jsonl"


def plan_digest(plan_obj: dict) -> str:
    """plan の確定部分（result を除く全体）のダイジェスト。

    freeze_hash は事前登録ルールの同一性しか保証しない。picks や target_date を
    結果を見た後で書き換えても freeze_hash 検証は通ってしまうため、
    plan 本体そのものを別途ハッシュして台帳に残す。
    """
    body = {k: v for k, v in plan_obj.items() if k not in ("result", "plan_digest")}
    payload = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _prepare(reg: PreRegistration) -> tuple[pd.DataFrame, pd.DataFrame]:
    """universe / history のフレームを事前登録の定義どおりに用意する。"""
    df = load_frame(reg.hall)
    universe_all = apply_eligibility(df, reg.universe)
    if reg.min_games_today > 0:
        universe_all = universe_all[universe_all["games_normalized"] >= reg.min_games_today]
    eligible_all = apply_eligibility(universe_all, reg.eligibility)
    history_all = eligible_all[eligible_all["games_normalized"] >= reg.min_games]
    return universe_all, history_all


def is_entry_day(reg: PreRegistration, target: str) -> bool:
    ts = pd.Timestamp(target)
    if reg.entry_days.get("dd") and ts.day not in set(reg.entry_days["dd"]):
        return False
    if reg.entry_days.get("weekday") and ts.weekday() not in set(reg.entry_days["weekday"]):
        return False
    return True


def plan(reg: PreRegistration, target_date: str, allow_past: bool = False) -> dict:
    """target_date の選択を、それ以前のデータだけを使って確定させる。

    Args:
        target_date: YYYYMMDD。原則として DB の最終日より後であること。
        allow_past: DB に既に存在する日付でも plan を許す（動作確認用）。
            True にした場合は is_dry_run を立て、実績の証拠として使わない。
    """
    if reg.score == "none":
        raise ValueError(
            "score='none' はフィルタのみのルールで、選択台を確定できないため "
            "フォワードテストに載せられない。台を絞る score を指定すること。"
        )

    universe_all, history_all = _prepare(reg)
    db_max = str(universe_all["date"].max())

    if not allow_past and target_date <= db_max:
        raise ValueError(
            f"target_date={target_date} は DB の最終日 {db_max} 以下。"
            "フォワードテストは未来日でのみ有効。動作確認なら --allow-past を付けること。"
        )
    if not is_entry_day(reg, target_date):
        raise ValueError(f"{target_date} はこのルールのエントリー日ではない（entry_days 条件外）")

    d0 = pd.Timestamp(target_date)
    lo = d0 - pd.Timedelta(days=reg.lookback_days)
    hist = history_all[(history_all["dt"] >= lo) & (history_all["dt"] < d0)]
    # 未来日なので当日の設置機種は分からない。直近の営業日の設置状況を
    # 代理として使い、台入替をまたいだ履歴を落とす。
    latest = universe_all[universe_all["date"] == db_max]
    hist = restrict_to_current_machine(hist, latest)
    if hist.empty:
        raise ValueError(f"lookback 窓 [{lo.date()}, {d0.date()}) に履歴がない")

    base = {
        "rule_id": reg.rule_id,
        "hall": reg.hall,
        "freeze_hash": reg.freeze_hash(),
        "target_date": target_date,
        "data_asof": db_max,
        "lookback_window": [str(lo.date()), str(d0.date())],
        "score": reg.score,
        "selection_unit": reg.selection_unit,
        "success_criterion": reg.success_criterion,
        "is_dry_run": bool(allow_past),
    }

    if reg.selection_unit == "machine_model":
        usable = usable_models(hist, reg)
        scores = score_history(hist[hist["machine_name"].isin(usable)], reg.score).dropna()
        if scores.empty:
            raise ValueError("min_history_days / min_machines_per_model を満たす機種がない")
        top_models = scores.sort_values(ascending=False).head(reg.top_n)
        model_row_counts = hist.groupby("machine_name").size()

        # 当日座る台は直近営業日 (db_max) のロスターで確定する。(machine_number,
        # machine_name) ペアで取る — games>0 等の稼働フィルタを先にかけると
        # 台入替直後・低稼働台が欠落し、機種入替後の台番号も混入する
        # （2026-08-03 セッションで確認済みのバグ）。universe_all はそのフィルタを
        # 経ていないので latest にも games>0 の絞り込みは無い。
        roster = latest[["machine_number", "machine_name"]].drop_duplicates()

        models_out: list[dict] = []
        picks: list[dict] = []
        for model, sc in top_models.items():
            machines = sorted(int(mn) for mn in roster.loc[roster["machine_name"] == model, "machine_number"])
            if not machines:
                continue
            row_count = int(model_row_counts.get(model, 0))
            models_out.append(
                {
                    "machine_name": model,
                    "score": round(float(sc), 6),
                    "history_rows": row_count,
                    "machines": machines,
                }
            )
            for mn in machines:
                picks.append(
                    {
                        "machine_number": mn,
                        "machine_name": model,
                        "score": round(float(sc), 6),
                        "history_days": row_count,
                    }
                )
        if not picks:
            raise ValueError("選択機種の当日ロスターが直近営業日データに存在しない")

        base["models"] = models_out
        base["picks"] = picks
        base["result"] = None
        return base

    counts = hist.groupby("machine_number").size()
    usable = counts[counts >= reg.min_history_days].index
    scores = score_history(hist[hist["machine_number"].isin(usable)], reg.score).dropna()
    if scores.empty:
        raise ValueError("min_history_days を満たす台がない")

    top = scores.sort_values(ascending=False).head(reg.top_n)
    names = hist.drop_duplicates("machine_number").set_index("machine_number")["machine_name"].to_dict()

    base["picks"] = [
        {
            "machine_number": int(mn),
            "machine_name": names.get(mn, ""),
            "score": round(float(sc), 6),
            "history_days": int(counts[mn]),
        }
        for mn, sc in top.items()
    ]
    base["result"] = None
    return base


def _reg_from_plan(plan_obj: dict) -> PreRegistration:
    """plan が参照している事前登録を読み直し、ハッシュ一致を検証する。"""
    reg = PreRegistration.load(PREREG_DIR / f"{plan_obj['rule_id']}.json")
    if reg.freeze_hash() != plan_obj["freeze_hash"]:
        raise ValueError(
            "事前登録が plan 作成後に書き換えられている。"
            f"plan={plan_obj['freeze_hash']} / 現在={reg.freeze_hash()}。"
            "採点は中止。ルールを変えたなら新しい rule_id で登録し直すこと。"
        )
    return reg


def _ledger_entries() -> dict[str, str]:
    """台帳から (rule_id__target_date -> digest) を読む。"""
    if not LEDGER.exists():
        return {}
    out = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        out[rec["key"]] = rec["plan_digest"]
    return out


def _append_ledger(plan_obj: dict, note: str = "") -> None:
    key = f"{plan_obj['rule_id']}__{plan_obj['target_date']}"
    rec = {
        "key": key,
        "plan_digest": plan_digest(plan_obj),
        "freeze_hash": plan_obj["freeze_hash"],
        "data_asof": plan_obj["data_asof"],
        "picks": [p["machine_number"] for p in plan_obj["picks"]],
    }
    if note:
        rec["note"] = note
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _verify_ledger(plan_obj: dict) -> None:
    """plan 本体が台帳の記録と一致するか検証する。"""
    key = f"{plan_obj['rule_id']}__{plan_obj['target_date']}"
    recorded = _ledger_entries().get(key)
    if recorded is None:
        raise ValueError(
            f"台帳に {key} の記録がない。plan 作成時に記録されていないか、"
            "台帳が失われている。この plan は証拠として採点できない。"
        )
    actual = plan_digest(plan_obj)
    if actual != recorded:
        raise ValueError(f"plan が作成後に書き換えられている。台帳={recorded} / 現在={actual}。採点を中止。")


# このスコアで選ぶルールは RB（+ジャグ/ハナハナの104%判定）を根拠に台を選んでいる。
# 差枚は投資ペースやBB配分にも左右されるため、「選んだ根拠（RB発生率）自体が
# 当日当たっていたか」を差枚と切り離して見る必要がある（AT系の hist_mean_diff には
# rb_rate は意味を持たないので対象外）。
RB_BASED_SCORES = {"hist_mean_rb_prob", "hist_mean_rb_prob_model_z", "hist_hit104_rate"}


def _rb_perspective(
    reg: PreRegistration, universe_all: pd.DataFrame, target: str, picked_numbers: list[int]
) -> dict | None:
    """選出根拠である RB 発生率について、当日の実測値・同条件台内での順位を返す。"""
    if reg.score not in RB_BASED_SCORES:
        return None

    eligible_all = apply_eligibility(universe_all, reg.eligibility)
    today_elig = eligible_all[eligible_all["date"] == target].dropna(subset=["rb_rate"])
    if today_elig.empty:
        return None

    baseline_rb = float(today_elig["rb_rate"].mean())
    ranked = today_elig.sort_values("rb_rate", ascending=False).reset_index(drop=True)
    n = len(ranked)
    rank_by_machine = {int(r["machine_number"]): i + 1 for i, r in ranked.iterrows()}
    row_by_machine = {int(r["machine_number"]): r for _, r in today_elig.iterrows()}

    picks_rb = []
    for mn in picked_numbers:
        r = row_by_machine.get(mn)
        picks_rb.append(
            {
                "machine_number": mn,
                "rb_rate": round(float(r["rb_rate"]), 5) if r is not None else None,
                "baseline_ratio": round(float(r["rb_rate"]) / baseline_rb, 2)
                if r is not None and baseline_rb
                else None,
                "rb_rank": rank_by_machine.get(mn),
                "rb_universe_size": n,
            }
        )

    return {
        "day_baseline_rb_rate": round(baseline_rb, 5),
        "picks_rb": picks_rb,
    }


def _model_perspective(plan_obj: dict, today: pd.DataFrame) -> list[dict] | None:
    """機種粒度 plan 専用: 指名機種ごとの総和ベース集計。

    plan_obj["picks"] のフラットな平均（mean_edge_per_pick 等）は台×日を
    等重みで扱う点で総和ベースの要件は満たすが、「どの機種が効いたか」は
    機種単位で見ないと分からない。ここでは機種ごとに sum(diff)/sum(games) を
    出し、台ごとの平均を機種間で単純平均する（本来やってはいけない集計）は
    行わない。
    """
    if plan_obj.get("selection_unit") != "machine_model":
        return None
    out = []
    for m in plan_obj.get("models", []):
        machines = m["machines"]
        realized = today[today["machine_number"].isin(machines)]
        entry = {
            "machine_name": m["machine_name"],
            "n_machines": len(machines),
            "n_realized": int(len(realized)),
        }
        if not realized.empty:
            entry["sum_diff"] = round(float(realized["diff_coins_normalized"].sum()), 1)
            entry["sum_games"] = round(float(realized["games_normalized"].sum()), 1)
            entry["mean_diff"] = round(float(realized["diff_coins_normalized"].mean()), 1)
        out.append(entry)
    return out


def score(plan_obj: dict) -> dict:
    """凍結済み plan に対して、実績データで答え合わせする。"""
    if plan_obj.get("result") is not None:
        raise ValueError("この plan は既に採点済み。結果の作り直しは禁止。")

    reg = _reg_from_plan(plan_obj)
    _verify_ledger(plan_obj)
    target = plan_obj["target_date"]
    universe_all, _ = _prepare(reg)

    today = universe_all[universe_all["date"] == target]
    if today.empty:
        raise ValueError(f"{target} のデータが DB にまだ無い。取り込み後に再実行すること。")

    baseline = float(today["diff_coins_normalized"].mean())
    picked_numbers = [p["machine_number"] for p in plan_obj["picks"]]
    realized = today[today["machine_number"].isin(picked_numbers)]

    rows = [
        {
            "machine_number": int(r["machine_number"]),
            "games": float(r["games_normalized"]),
            "diff": float(r["diff_coins_normalized"]),
            "edge": float(r["diff_coins_normalized"]) - baseline,
        }
        for _, r in realized.iterrows()
    ]

    plan_obj["result"] = {
        "scored_with_hash": plan_obj["freeze_hash"],
        "day_baseline": round(baseline, 1),
        "universe_size": int(len(today)),
        "picks_realized": rows,
        "mean_diff_per_pick": round(sum(r["diff"] for r in rows) / len(rows), 1) if rows else None,
        "mean_edge_per_pick": round(sum(r["edge"] for r in rows) / len(rows), 1) if rows else None,
        # データに現れなかった台。撤去・休止なら実運用でも座れていないので記録する。
        "missing_machines": sorted(set(picked_numbers) - set(realized["machine_number"])),
        "rb_perspective": _rb_perspective(reg, universe_all, target, picked_numbers),
        "model_perspective": _model_perspective(plan_obj, today),
    }
    return plan_obj


_YYYYMMDD = re.compile(r"^\d{8}$")


def parse_date(value: str) -> date:
    """YYYYMMDD を厳格に解釈する。

    pd.Timestamp は "2026-08-12" のようなハイフン付きも受けてしまうが、
    この系では日付をファイル名と辞書順比較の両方に使うため、8桁固定で
    なければならない。緩い解釈を通すと `k7__2026-08-12.json` のような
    ファイルが生まれ、target_date <= db_max の比較も壊れる。
    """
    if not isinstance(value, str) or not _YYYYMMDD.match(value):
        raise ValueError(f"日付は YYYYMMDD の8桁で指定すること: {value!r}")
    return datetime.strptime(value, "%Y%m%d").date()


def _freeze_plan(plan_obj: dict) -> Path:
    """plan を JSON に書き出し、台帳に追記する。既存ファイルは絶対に上書きしない。

    存在チェックと書き込みを分けると、その隙間に別プロセスが書いた凍結済み
    証拠を truncate で消しうる。排他生成 ("x") で原子的に確保する。
    """
    out = FORWARD_DIR / f"{plan_obj['rule_id']}__{plan_obj['target_date']}.json"
    plan_obj["plan_digest"] = plan_digest(plan_obj)
    body = json.dumps(plan_obj, ensure_ascii=False, indent=2) + "\n"
    try:
        with out.open("x", encoding="utf-8") as fh:
            fh.write(body)
    except FileExistsError as exc:
        raise FileExistsError(f"既に存在する: {out}（作り直しは禁止）") from exc
    _append_ledger(plan_obj)
    return out


def plan_integrity(rule_id: str, target_date: str) -> str:
    """凍結済み plan の健全性を返す: "absent" / "frozen" / "orphaned"。

    plan ファイルの存在だけで「凍結済み」と判定してはいけない。JSON の
    書き込み後・台帳追記前に落ちると、ファイルはあるのに台帳に無い
    「みなしご plan」が残る。この状態は後で score() が採点を拒否するため、
    再実行時に already_frozen として素通りさせると欠測が静かに確定する。
    """
    path = FORWARD_DIR / f"{rule_id}__{target_date}.json"
    if not path.exists():
        return "absent"
    try:
        _verify_ledger(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return "orphaned"
    return "frozen"


def load_preregs() -> list[PreRegistration]:
    """prereg ディレクトリの事前登録を全件読む。

    rule_id を持たない JSON（claims.json 等の付随ファイル）は事前登録では
    ないので黙って除外する。それ以外の読み込み失敗は握り潰さず投げる
    （壊れた事前登録を「今日は無かったこと」にしてはいけない）。

    ファイル名と rule_id の一致、および rule_id の一意性を要求する。
    不一致だと _reg_from_plan が採点時に事前登録を引けず、重複すると
    「1ルール1件」の前提が崩れて欠測がカウント上見えなくなる。
    """
    regs: list[PreRegistration] = []
    seen: set[str] = set()
    for path in sorted(PREREG_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "rule_id" not in data:
            continue
        reg = PreRegistration.load(path)
        if reg.rule_id != path.stem:
            raise ValueError(f"ファイル名と rule_id が不一致: {path.name} / rule_id={reg.rule_id}")
        if reg.rule_id in seen:
            raise ValueError(f"rule_id が重複している: {reg.rule_id}")
        seen.add(reg.rule_id)
        regs.append(reg)
    return regs


def _now_jst(now: datetime | None = None) -> datetime:
    """運用タイムゾーン（JST）に揃えた現在時刻。

    ホストのローカルタイムゾーンに依存させない。naive な datetime は
    どの時刻か決まらないので受け付けない（announce.py で出た TZ 境界バグと
    同種の穴を塞ぐ）。
    """
    if now is None:
        return datetime.now(JST)
    if now.tzinfo is None:
        raise ValueError("now はタイムゾーン付きで渡すこと（naive datetime は不可）")
    return now.astimezone(JST)


def is_late_wallclock(target_date: str, now: datetime | None = None) -> bool:
    """対象日が始まってからの凍結か。実時間（壁時計）で判定する。

    plan は data_asof より後の情報を使えないので、遅れて生成しても
    情報リークは起きない（picks は決定論的に決まる）。汚れるのは
    「対象日の経過後に生成した」という運用上の事実だけである。それでも
    証拠として厳密に扱う集計からは外せるよう、印を残す。
    backtest/forward/RETROACTIVE_NOTES.md を手で書いていた作業の自動化。

    朝から座る運用なので、対象日の 0 時（JST）を過ぎた時点で「事前」ではない。
    announce.is_late_registration が翌日 0 時を境にしているのは、あちらが
    「登録者が結果を知っている可能性」を見ているためで、基準が異なる。
    """
    now = _now_jst(now)
    d = parse_date(target_date)
    return now >= datetime(d.year, d.month, d.day, tzinfo=JST)


def _write_run_record(record: dict) -> dict:
    with RUNS_LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _run_record(
    target_date: str,
    now: datetime,
    allow_past: bool,
    dispositions: list[dict],
    run_status: str,
    fatal_error: str | None = None,
) -> dict:
    rec = {
        "target_date": target_date,
        "generated_at": now.isoformat(timespec="seconds"),
        "is_late_wallclock": is_late_wallclock(target_date, now),
        "is_dry_run": bool(allow_past),
        "run_status": run_status,
        "n_rules": len(dispositions),
        "counts": {
            s: sum(1 for d in dispositions if d["status"] == s) for s in sorted({d["status"] for d in dispositions})
        },
        "dispositions": dispositions,
    }
    if fatal_error:
        rec["fatal_error"] = fatal_error
    return rec


# plan() が想定内の理由（履歴不足・機種未設置など）で投げる例外。これ以外は
# DB 障害・ディスク障害・実装バグのいずれかであり、「記録したから OK」で
# 先へ進めてはいけない。
_EXPECTED_PLAN_FAILURES = (ValueError,)


def plan_all(target_date: str, allow_past: bool = False, now: datetime | None = None) -> dict:
    """全事前登録ルールを対象日について機械的に plan する。

    どのルールも「回さない」という選択肢を持たない。エントリー日でない・
    履歴が足りない・既に凍結済みといった理由で plan が作られなかった場合も、
    理由付きで RUNS.jsonl に残す。これにより「plan が無い日」は
    *記録された不在* になり、事後的な選り好みと区別できるようになる。

    ルールを部分指定する引数は **意図的に持たない**。一部だけ回した記録も
    n_rules == len(dispositions) を満たしてしまい、「都合の悪いルールを
    外して回す」という、この仕組みが潰したはずの経路がコマンドラインから
    復活するため。個別に動かしたいときは既存の `plan` サブコマンドを使う
    （あちらは RUNS に記録を残さないので、日次カバレッジを詐称できない）。

    Returns:
        RUNS.jsonl に追記した実行記録。
    """
    parse_date(target_date)
    now = _now_jst(now)

    try:
        regs = load_preregs()
    except Exception as exc:
        # 事前登録が壊れている等で1本も処理できなかった。ここで黙って落ちると
        # 「実行しなかった日」と見分けが付かなくなるので、記録してから送出する。
        _write_run_record(_run_record(target_date, now, allow_past, [], "fatal", f"{type(exc).__name__}: {exc}"))
        raise

    dispositions: list[dict] = []
    fatal: Exception | None = None
    for reg in regs:
        entry: dict = {"rule_id": reg.rule_id, "hall": reg.hall}
        integrity = plan_integrity(reg.rule_id, target_date)
        if integrity == "frozen":
            entry["status"] = "already_frozen"
        elif integrity == "orphaned":
            # ファイルはあるが台帳と食い違う。放置すると採点不能な穴になる。
            entry["status"] = "orphaned_plan"
        elif reg.score == "none":
            # フィルタのみのルールは台を確定できない（plan() が拒否する）。
            entry["status"] = "skipped_no_score"
        elif not is_entry_day(reg, target_date):
            entry["status"] = "skipped_not_entry_day"
            entry["entry_days"] = reg.entry_days
        else:
            try:
                obj = plan(reg, target_date, allow_past=allow_past)
                _freeze_plan(obj)
                entry["status"] = "planned"
                entry["data_asof"] = obj["data_asof"]
                entry["picks"] = [p["machine_number"] for p in obj["picks"]]
            except _EXPECTED_PLAN_FAILURES as exc:
                # 想定内。1本の不成立で残りを止めない。
                entry["status"] = "failed"
                entry["error"] = f"{type(exc).__name__}: {exc}"
            except Exception as exc:
                # 想定外。以降のルールも同じ理由で倒れる公算が高いので打ち切り、
                # ここまでの記録を残してから送出する。
                entry["status"] = "fatal"
                entry["error"] = f"{type(exc).__name__}: {exc}"
                fatal = exc
        dispositions.append(entry)
        if fatal is not None:
            break

    if fatal is not None:
        run_status = "fatal"
    elif any(d["status"] in ("failed", "orphaned_plan") for d in dispositions):
        run_status = "incomplete"
    else:
        run_status = "ok"

    rec = _write_run_record(
        _run_record(
            target_date,
            now,
            allow_past,
            dispositions,
            run_status,
            f"{type(fatal).__name__}: {fatal}" if fatal is not None else None,
        )
    )
    if fatal is not None:
        raise fatal
    return rec


def _runs_by_date() -> tuple[dict[str, list[dict]], int]:
    """RUNS.jsonl を対象日ごとに読む。戻り値は (日付→記録リスト, 壊れた行数)。"""
    if not RUNS_LEDGER.exists():
        return {}, 0
    out: dict[str, list[dict]] = {}
    corrupt = 0
    for line in RUNS_LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            # 追記の途中でクラッシュした行。無かったことにはせず数える。
            corrupt += 1
            continue
        out.setdefault(rec["target_date"], []).append(rec)
    return out, corrupt


def audit(start: str, end: str) -> dict:
    """[start, end] の各日について、実行記録の欠落と不整合を洗い出す。

    plan-all は RUNS への追記前にクラッシュすれば記録を残せない。欠測を
    *防ぐ* のは運用側（定時実行）の責務であり、ここが担うのは
    **欠測が必ず見つかる** ことである。「記録が無い日」を数え上げられる
    限り、証拠の欠落は隠れたままにならない。
    """
    d0, d1 = parse_date(start), parse_date(end)
    if d0 > d1:
        raise ValueError("start <= end であること")
    runs, corrupt = _runs_by_date()
    rule_ids = [r.rule_id for r in load_preregs()]

    days: list[dict] = []
    for ts in pd.date_range(d0, d1, freq="D"):
        day = ts.strftime("%Y%m%d")
        recs = runs.get(day, [])
        entry: dict = {"date": day, "n_runs": len(recs)}
        if not recs:
            entry["status"] = "no_run_record"
            days.append(entry)
            continue
        latest = recs[-1]
        covered = {d["rule_id"] for r in recs for d in r["dispositions"]}
        uncovered = [rid for rid in rule_ids if rid not in covered]
        problems = sorted(
            {
                d["rule_id"]
                for r in recs
                for d in r["dispositions"]
                if d["status"] in ("failed", "fatal", "orphaned_plan")
            }
        )
        entry["run_status"] = latest.get("run_status", "unknown")
        entry["is_late_wallclock"] = latest.get("is_late_wallclock")
        if uncovered:
            entry["status"] = "incomplete_coverage"
            entry["uncovered_rules"] = uncovered
        elif problems:
            entry["status"] = "has_problem_rules"
            entry["problem_rules"] = problems
        else:
            entry["status"] = "ok"
        days.append(entry)

    return {
        "range": [start, end],
        "n_registered_rules": len(rule_ids),
        "corrupt_lines": corrupt,
        "counts": {s: sum(1 for d in days if d["status"] == s) for s in sorted({d["status"] for d in days})},
        "days": days,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="フォワードテストの計画作成と採点")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="未来日の選択を凍結する")
    p_plan.add_argument("prereg")
    p_plan.add_argument("--date", required=True, help="YYYYMMDD")
    p_plan.add_argument("--allow-past", action="store_true", help="動作確認用。証拠には使わない")

    # ルールの部分指定オプションは意図的に用意しない（plan_all の docstring 参照）。
    p_all = sub.add_parser("plan-all", help="全ルールを対象日について機械的に凍結する")
    p_all.add_argument("--date", help="YYYYMMDD。省略時は翌日")
    p_all.add_argument("--allow-past", action="store_true", help="動作確認用。証拠には使わない")

    p_audit = sub.add_parser("audit", help="実行記録の欠落と不整合を洗い出す")
    p_audit.add_argument("--from", dest="start", required=True, help="YYYYMMDD")
    p_audit.add_argument("--to", dest="end", required=True, help="YYYYMMDD")

    p_score = sub.add_parser("score", help="凍結済み plan を実績で採点する")
    p_score.add_argument("plan")

    args = p.parse_args(argv)
    FORWARD_DIR.mkdir(parents=True, exist_ok=True)

    if args.cmd == "plan":
        reg = PreRegistration.load(args.prereg)
        obj = plan(reg, args.date, allow_past=args.allow_past)
        try:
            out = _freeze_plan(obj)
        except FileExistsError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        print(f"\n-> 凍結: {out}", file=sys.stderr)
    elif args.cmd == "plan-all":
        target = args.date or (datetime.now(JST) + timedelta(days=1)).strftime("%Y%m%d")
        rec = plan_all(target, allow_past=args.allow_past)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        counts = " / ".join(f"{k}={v}" for k, v in rec["counts"].items())
        print(f"\n-> {target}: {counts}", file=sys.stderr)
        if rec["is_late_wallclock"]:
            print("警告: 対象日が既に始まっている。事前凍結として厳密に扱えない。", file=sys.stderr)
        if rec["run_status"] != "ok":
            # 凍結できなかった／台帳と食い違うルールがある。記録は残っているので
            # 欠測ではないが、放置すると静かに証拠が痩せるので異常終了させる。
            return 1
    elif args.cmd == "audit":
        rep = audit(args.start, args.end)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        counts = " / ".join(f"{k}={v}" for k, v in rep["counts"].items())
        print(f"\n-> {args.start}..{args.end}: {counts}", file=sys.stderr)
        clean = set(rep["counts"]) <= {"ok"} and not rep["corrupt_lines"]
        if not clean:
            return 1
    else:
        path = Path(args.plan)
        obj = score(json.loads(path.read_text(encoding="utf-8")))
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(obj["result"], ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
