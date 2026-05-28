import pandas as pd

from ml.last_digit.post_rerank import (
    build_confidence_band,
    choose_operational_pick,
    mark_avoid_candidates,
)


def test_confidence_band_high():
    assert build_confidence_band(0.50) == "high"


def test_confidence_band_medium():
    assert build_confidence_band(0.20) == "medium"


def test_confidence_band_low():
    assert build_confidence_band(0.05) == "low"


def test_confidence_band_undefined():
    assert build_confidence_band(0.0005) == "undefined"


def test_confidence_band_boundaries():
    assert build_confidence_band(0.30) == "high"
    assert build_confidence_band(0.10) == "medium"
    assert build_confidence_band(0.099) == "low"
    assert build_confidence_band(0.001) == "low"
    assert build_confidence_band(0.000999) == "undefined"


def test_mark_avoid_candidates_flags_bottom_k():
    df = pd.DataFrame({
        "last_digit": [str(i) for i in range(10)],
        "pred": [float(i) for i in range(10)],
    })
    out = mark_avoid_candidates(df, avoid_k=3)
    avoided = set(out.loc[out["is_avoid_candidate"] == 1, "last_digit"])
    assert avoided == {"0", "1", "2"}


def test_mark_avoid_candidates_does_not_change_ranking():
    df = pd.DataFrame({
        "last_digit": ["6", "8", "0"],
        "pred": [0.9, 0.7, 0.1],
    })
    out = mark_avoid_candidates(df, avoid_k=1)
    assert list(out["pred"]) == [0.9, 0.7, 0.1]


def test_mark_avoid_candidates_k0_flags_nothing():
    df = pd.DataFrame({
        "last_digit": ["1", "2", "3"],
        "pred": [0.9, 0.5, 0.1],
    })
    out = mark_avoid_candidates(df, avoid_k=0)
    assert out["is_avoid_candidate"].sum() == 0


def test_choose_operational_pick_default_top1():
    tail, source = choose_operational_pick(top1_tail="8", top2_tail="3", confidence_band="low")
    assert tail == "8"
    assert source == "top1_default"


def test_choose_operational_pick_undefined_switches_to_top2():
    tail, source = choose_operational_pick(top1_tail="8", top2_tail="3", confidence_band="undefined")
    assert tail == "3"
    assert source == "top2_on_undefined"
