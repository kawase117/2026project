"""差枚の打ち切り検出（backtest/censoring.py）のテスト。

実 DB を読む検定は **必ず両端を閉じた窓** で行う。start_date だけ指定すると
新しい日付が入るたびに件数が変わり、データ追加でテストが落ちる。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from backtest.censoring import (
    CENSOR_BOUNDS,
    REGULATORY_MAX_DIFF,
    add_censor_flags,
    bounds_for,
    censoring_summary,
    detect_bounds,
    max_understatement_hi,
    warning_text,
)

DB_DIR = Path(__file__).resolve().parents[2] / "db"

# 打ち切り検証に使う固定窓。両端とも閉じる。
WINDOW = ("20250101", "20260812")


def _load(hall: str) -> pd.DataFrame:
    path = DB_DIR / f"{hall}.db"
    if not path.exists():
        pytest.skip(f"DB が無い: {path}")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return pd.read_sql(
            "SELECT date, machine_name, diff_coins_normalized, games_normalized "
            "FROM machine_detailed_results WHERE date >= ? AND date <= ?",
            conn,
            params=WINDOW,
        )


# --- ロジック単体（DB 非依存） -------------------------------------------------


def _frame(values: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "machine_name": ["A"] * len(values),
            "diff_coins_normalized": values,
            "games_normalized": [5000] * len(values),
        }
    )


def test_bounds_for_unknown_hall_is_none():
    assert bounds_for("存在しないホール") is None


def test_add_censor_flags_creates_columns_even_without_censoring():
    df = _frame([100, 200])
    add_censor_flags(df, "存在しないホール")
    assert not df["censored_hi"].any()
    assert not df["censored_lo"].any()


def test_add_censor_flags_marks_both_bounds():
    lo, hi = CENSOR_BOUNDS["楽園蒲田店"]
    df = _frame([lo, hi, 0, hi - 1])
    add_censor_flags(df, "楽園蒲田店")
    assert df["censored_lo"].tolist() == [True, False, False, False]
    assert df["censored_hi"].tolist() == [False, True, False, False]


def test_censoring_summary_without_flags_is_zero():
    s = censoring_summary(_frame([1, 2, 3]))
    assert s == {"n_censored_hi": 0, "n_censored_lo": 0, "machines_hi": [], "machines_lo": []}


def test_warning_text_is_none_when_clean():
    assert warning_text(censoring_summary(_frame([1, 2])), "楽園蒲田店") is None


def test_max_understatement_hi_matches_regulatory_cap():
    _, hi = CENSOR_BOUNDS["楽園蒲田店"]
    assert max_understatement_hi("楽園蒲田店") == REGULATORY_MAX_DIFF - hi


def test_max_understatement_hi_none_when_not_censored():
    assert max_understatement_hi("存在しないホール") is None


def test_warning_text_mentions_direction_of_bias():
    lo, hi = CENSOR_BOUNDS["楽園蒲田店"]
    df = _frame([hi, lo])
    add_censor_flags(df, "楽園蒲田店")
    msg = warning_text(censoring_summary(df), "楽園蒲田店", context="20260812")
    assert msg is not None
    assert "下界" in msg  # 右打ち切り → 過小評価
    assert "過大評価" in msg  # 左打ち切り → 過大評価


def test_detect_bounds_ignores_zero_game_rows():
    # 休止台（games=0）は差枚 0 が大量に並ぶが打ち切りではない。
    df = _frame([0] * 50 + [100, 200, 300])
    df.loc[:49, "games_normalized"] = 0
    assert detect_bounds(df) == {"lo": None, "hi": None, "n_rows": 3}


def test_detect_bounds_finds_pile_up():
    # 端に 20 行、その隣は 1 行 → 打ち切りと判定されるべき。
    df = _frame([9999] * 20 + [500, 600, 700])
    assert detect_bounds(df)["hi"] == {"value": 9999, "count": 20, "neighbor_count": 1}


# --- 実 DB に対する検算 --------------------------------------------------------


def test_rakuen_bounds_match_frozen_constant():
    """楽園の打ち切り境界が CENSOR_BOUNDS と一致すること。

    ana-slo 側が軸レンジを変えたらここが落ちる。落ちたら定数を更新する。
    """
    df = _load("楽園蒲田店")
    got = detect_bounds(df)
    lo, hi = CENSOR_BOUNDS["楽園蒲田店"]
    assert got["lo"] is not None and got["hi"] is not None, "打ち切りが検出されなくなった"
    assert got["lo"]["value"] == lo
    assert got["hi"]["value"] == hi


def test_rakuen_values_are_pixel_quantized():
    """値が 431 ピクセルのグラフ読み取りであること（打ち切りの根拠）。

    隣接ユニーク値の差が 47/48 の 2 種類しか無い = 等間隔サンプリング。
    実測値ならこんな刻みにはならない。
    """
    df = _load("楽園蒲田店")
    d = df[df["games_normalized"] > 0]
    steps = set(d["diff_coins_normalized"].drop_duplicates().sort_values().diff().dropna())
    assert steps <= {47.0, 48.0, 95.0, 96.0}, f"想定外の刻み: {sorted(steps)}"


def test_kamata7_is_not_censored():
    """打ち切りが楽園固有であることの対照。蒲田7 は端に積み上がらない。"""
    got = detect_bounds(_load("マルハンメガシティ2000-蒲田7"))
    assert got["lo"] is None
    assert got["hi"] is None


def test_only_registered_halls_are_censored():
    """CENSOR_BOUNDS に載っていないホールで打ち切りが出ていないこと。

    新しいホールを追加したとき、打ち切りに気づかず素通りするのを防ぐ。
    """
    found = {}
    for path in sorted(DB_DIR.glob("*.db")):
        hall = path.stem
        if path.stat().st_size < 1_000_000 or hall in CENSOR_BOUNDS:
            continue
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            tables = pd.read_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='machine_detailed_results'",
                conn,
            )
            if tables.empty:
                continue
            df = pd.read_sql(
                "SELECT diff_coins_normalized, games_normalized FROM machine_detailed_results "
                "WHERE date >= ? AND date <= ?",
                conn,
                params=WINDOW,
            )
        got = detect_bounds(df)
        if got["lo"] or got["hi"]:
            found[hall] = got
    assert not found, f"未登録ホールで打ち切りを検出: {found}"


# --- audit_censoring（採点済み予告の再点検） ------------------------------------


def test_audit_censoring_flags_known_rakuen_cases():
    """2026-08-11・08-12 の楽園蒲田店 model_named claim は、打ち切りが無ければ
    閾値に届いていた可能性があると判定されるべき（本セッションで手動確認済み）。
    2026-08-07 の北斗の拳は不足分が見誤り幅を超えているので reclassify されない。
    """
    from backtest.announce import audit_censoring

    announce_dir = Path(__file__).resolve().parents[2] / "backtest" / "announce"
    if not any(announce_dir.glob("*.json")):
        pytest.skip("backtest/announce/ に予告ファイルが無い")

    res = audit_censoring("楽園蒲田店")
    by_id = {r["announce_id"]: r for r in res}

    if "rakuen__20260811__kawasakislot" not in by_id:
        pytest.skip("既知の楽園予告ファイルが無い環境（別ブランチ・別チェックアウト）")

    assert by_id["rakuen__20260811__kawasakislot"]["reclassify_as_indeterminate"] is True
    assert by_id["rakuen__20260812__kawasakislot"]["reclassify_as_indeterminate"] is True
    if "rakuen__20260807__kawasakislot" in by_id:
        assert by_id["rakuen__20260807__kawasakislot"]["reclassify_as_indeterminate"] is False


def test_audit_censoring_does_not_write_files():
    """読み取り専用であること。採点済み結果ファイルの mtime が変わらない。"""
    from backtest.announce import audit_censoring

    announce_dir = Path(__file__).resolve().parents[2] / "backtest" / "announce"
    files = list(announce_dir.glob("*.json"))
    if not files:
        pytest.skip("backtest/announce/ に予告ファイルが無い")

    before = {f: f.stat().st_mtime for f in files}
    audit_censoring("楽園蒲田店")
    after = {f: f.stat().st_mtime for f in files}
    assert before == after
