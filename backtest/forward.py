"""フォワードテスト: 未来日の選択を事前に凍結し、後から答え合わせする。

バックテストと決定的に違う点:
    バックテストは「過去データから見つけた仮説を過去データで確認する」自己参照から
    逃れられない。フォワードテストは、選択を **データが存在しない時点で** 確定させる。
    ここで出た結果だけが instinct の status を unverified から confirmed/refuted に
    動かす資格を持つ。

運用:
    1. 前日夜に plan を実行 → 台リストが JSON に凍結される（result は null）
    2. 当日は凍結された台にだけ座る。リストを見て選び直さない
    3. データ反映後に score を実行 → 同じファイルの result 欄が埋まる
       すでに result が入っているファイルは上書きしない（やり直しの禁止）

使い方:
    venv\\Scripts\\python.exe -m backtest.forward plan backtest/prereg/xxx.json --date 20260801
    venv\\Scripts\\python.exe -m backtest.forward score backtest/forward/xxx__20260801.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from backtest.prereg import PreRegistration
from backtest.run_backtest import (
    apply_eligibility,
    load_frame,
    restrict_to_current_machine,
    score_history,
)

FORWARD_DIR = Path(__file__).resolve().parent / "forward"
PREREG_DIR = Path(__file__).resolve().parent / "prereg"
# plan 本体のダイジェストを追記専用で記録する台帳。plan JSON 自体が
# 書き換えられても、ここと突き合わせれば改ざんが検出できる。
LEDGER = FORWARD_DIR / "LEDGER.jsonl"


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

    counts = hist.groupby("machine_number").size()
    usable = counts[counts >= reg.min_history_days].index
    scores = score_history(hist[hist["machine_number"].isin(usable)], reg.score).dropna()
    if scores.empty:
        raise ValueError("min_history_days を満たす台がない")

    top = scores.sort_values(ascending=False).head(reg.top_n)
    names = hist.drop_duplicates("machine_number").set_index("machine_number")["machine_name"].to_dict()

    return {
        "rule_id": reg.rule_id,
        "hall": reg.hall,
        "freeze_hash": reg.freeze_hash(),
        "target_date": target_date,
        "data_asof": db_max,
        "lookback_window": [str(lo.date()), str(d0.date())],
        "score": reg.score,
        "success_criterion": reg.success_criterion,
        "is_dry_run": bool(allow_past),
        "picks": [
            {
                "machine_number": int(mn),
                "machine_name": names.get(mn, ""),
                "score": round(float(sc), 6),
                "history_days": int(counts[mn]),
            }
            for mn, sc in top.items()
        ],
        "result": None,
    }


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
    }
    return plan_obj


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="フォワードテストの計画作成と採点")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="未来日の選択を凍結する")
    p_plan.add_argument("prereg")
    p_plan.add_argument("--date", required=True, help="YYYYMMDD")
    p_plan.add_argument("--allow-past", action="store_true", help="動作確認用。証拠には使わない")

    p_score = sub.add_parser("score", help="凍結済み plan を実績で採点する")
    p_score.add_argument("plan")

    args = p.parse_args(argv)
    FORWARD_DIR.mkdir(parents=True, exist_ok=True)

    if args.cmd == "plan":
        reg = PreRegistration.load(args.prereg)
        obj = plan(reg, args.date, allow_past=args.allow_past)
        out = FORWARD_DIR / f"{reg.rule_id}__{args.date}.json"
        if out.exists():
            raise SystemExit(f"既に存在する: {out}（作り直しは禁止）")
        obj["plan_digest"] = plan_digest(obj)
        out.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _append_ledger(obj)
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        print(f"\n-> 凍結: {out}", file=sys.stderr)
    else:
        path = Path(args.plan)
        obj = score(json.loads(path.read_text(encoding="utf-8")))
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(obj["result"], ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
