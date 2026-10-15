"""ホール別・機種別の設定事前: 分解、estimateへの反映、事前なしの扱い。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from backtest.bonus_specs import find_spec, load_specs
from scraper.realtime.estimate import estimate
from scraper.realtime.hall_prior import decompose, smooth, spec_key
from scraper.realtime.schema import SnapshotRow

NOW = datetime(2026, 10, 15, 20, tzinfo=ZoneInfo("Asia/Tokyo"))
MODEL = "マイジャグラーV"
HALL = "楽園蒲田店"


def row(games=5000, rb=24, hall=HALL):
    return SnapshotRow(
        hall=hall,
        observed_at=NOW.isoformat(),
        source_updated_at=None,
        unit=1,
        model=MODEL,
        model_raw=MODEL,
        games=games,
        rb=rb,
    )


def low_prior(specs):
    settings = [s for s, v in find_spec(MODEL, specs)["settings"].items() if v.get("rb_probability")]
    weights = {s: (0.4 if s <= 2 else 0.1) for s in settings}
    total = sum(weights.values())
    return {s: w / total for s, w in weights.items()}


def test_decompose_recovers_known_mixture():
    rng = np.random.default_rng(0)
    rb_prob = {1: 1 / 410, 2: 1 / 386, 3: 1 / 336, 4: 1 / 290, 5: 1 / 269, 6: 1 / 229}
    truth = np.array([0.1, 0.2, 0.3, 0.2, 0.1, 0.1])
    settings = rng.choice(6, size=4000, p=truth)
    games = np.full(4000, 5000.0)
    rb = rng.poisson(games * np.array(list(rb_prob.values()))[settings])
    est = decompose(games, rb.astype(float), rb_prob)
    # 隣り合う設定は分けにくいので、1〜2 / 3〜4 / 5〜6 のまとまりで見る
    groups = [sum(est[s] for s in g) for g in ((1, 2), (3, 4), (5, 6))]
    assert np.allclose(groups, [0.3, 0.5, 0.2], atol=0.08)


def test_smooth_keeps_every_setting_positive():
    smoothed = smooth({1: 1.0, 2: 0.0})
    assert smoothed[2] > 0 and abs(sum(smoothed.values()) - 1) < 1e-9


def test_prior_applied_flag_and_no_prior_bucket(tmp_path):
    from scraper.realtime.rank import build_ranking

    specs = load_specs()
    prior = {HALL: {spec_key(MODEL, specs): low_prior(specs)}}
    assert estimate(row(), specs=specs, audit={})["prior_applied"] is None
    assert estimate(row(), specs=specs, audit={}, hall_prior=prior)["prior_applied"] is True
    assert estimate(row(hall="ヒロキ西口店"), specs=specs, audit={}, hall_prior=prior)["prior_applied"] is False
    rows = [row(), row(hall="ヒロキ西口店")]
    data = build_ranking(
        rows, db_dir=tmp_path, specs_by_hall={HALL: specs, "ヒロキ西口店": specs}, audit={}, hall_prior=prior
    )
    assert [r["hall"] for r in data["ranked"]] == [HALL]
    assert [r["hall"] for r in data["no_prior"]] == ["ヒロキ西口店"]
    # 事前を渡さなければ従来どおり全部ranked
    plain = build_ranking(rows, db_dir=tmp_path, specs_by_hall={HALL: specs, "ヒロキ西口店": specs}, audit={})
    assert len(plain["ranked"]) == 2 and plain["no_prior"] == []


def test_four_setting_machine_needs_fewer_machine_days(tmp_path):
    import sqlite3

    from scraper.realtime.hall_prior import estimate_hall

    con = sqlite3.connect(tmp_path / "テスト店.db")
    con.execute(
        "create table machine_detailed_results (date text, machine_name text, games_normalized int, rb_count int)"
    )
    rng = np.random.default_rng(1)
    rows = []
    for i in range(200):  # 200台日: 4設定機は作る(150以上)、6設定機は作らない(300未満)
        date = f"2026{9 + i // 90:02d}{i % 28 + 1:02d}"
        rows.append((date, "新ハナビ", 3000, int(rng.poisson(3000 / 380))))
        rows.append((date, "マイジャグラーV", 5000, int(rng.poisson(5000 / 350))))
    con.executemany("insert into machine_detailed_results values (?,?,?,?)", rows)
    con.commit()
    con.close()
    keys = estimate_hall("テスト店", db_dir=tmp_path, days=365, as_of="20261231")
    assert spec_key("新ハナビ") in keys
    assert spec_key("マイジャグラーV") not in keys


def test_low_hall_prior_lowers_p_high_and_missing_prior_is_uniform():
    specs = load_specs()
    uniform = estimate(row(), specs=specs, audit={})
    prior = {HALL: {spec_key(MODEL, specs): low_prior(specs)}}
    with_prior = estimate(row(), specs=specs, audit={}, hall_prior=prior)
    assert with_prior["p_high"] < uniform["p_high"]
    # 事前の無いホールは一様と同じ値で、注記が付く
    other = estimate(row(hall="ヒロキ西口店"), specs=specs, audit={}, hall_prior=prior)
    assert abs(other["p_high"] - uniform["p_high"]) < 1e-12
    assert any("ホール別事前なし" in n for n in other["notes"])
    assert not any("ホール別事前なし" in n for n in with_prior["notes"])
