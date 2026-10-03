"""AT機の監査(backtest/at_rb_audit.py)と、bonus_specsの事前分布・AT判別の追加部分のテスト。合成データのみ。"""

import csv

import pandas as pd

from backtest import at_rb_audit as audit
from backtest import bonus_specs as bs


def _write_master(path, rows):
    fields = ["machine_name", "canonical_machine_name", "game_type", "notes"] + [
        f"at_initial_setting{s}" for s in range(1, 7)
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def test_load_at_hit_specs_reads_per_setting_and_range(tmp_path):
    master = tmp_path / "master.csv"
    _write_master(
        master,
        [
            {
                "machine_name": "機種A",
                "canonical_machine_name": "機種A",
                "game_type": "AT",
                "at_initial_setting1": "1/400",
                "at_initial_setting6": "1/200",
            },
            {
                "machine_name": "機種B",
                "canonical_machine_name": "機種B",
                "game_type": "AT",
                "notes": "AT初当り:1/350.2〜1/256.3 天井:999G",
            },
            {
                "machine_name": "機種C",
                "canonical_machine_name": "機種C",
                "game_type": "ノーマル",
                "notes": "AT初当り:1/300〜1/200",
            },
            {"machine_name": "機種D", "canonical_machine_name": "機種D", "game_type": "AT"},
        ],
    )
    specs = bs.load_at_hit_specs(master)
    assert set(specs) == {bs.normalize("機種A"), bs.normalize("機種B")}
    assert specs[bs.normalize("機種A")]["per"] == {1: 1 / 400, 6: 1 / 200}
    low, high = specs[bs.normalize("機種B")]["rng"]
    assert abs(low - 1 / 350.2) < 1e-12 and abs(high - 1 / 256.3) < 1e-12


def test_column_in_range_uses_margin():
    bounds = (1 / 400, 1 / 200)
    assert audit.column_in_range(1 / 300, bounds)
    assert not audit.column_in_range(1 / 450, bounds)  # 既定の余裕(5%)では範囲外
    assert audit.column_in_range(1 / 450, bounds, margin=0.15)
    assert not audit.column_in_range(1 / 600, bounds)
    assert not audit.column_in_range(1 / 100, bounds)


def test_dispersion_ratio_is_one_for_poisson_like_counts():
    games = pd.Series([3000.0] * 6)
    counts = pd.Series([9, 11, 10, 10, 9, 11])
    assert 0.0 <= audit.dispersion_ratio(counts, games) < 1.0
    clumped = pd.Series([0, 0, 0, 60, 0, 0])
    assert audit.dispersion_ratio(clumped, games) > 10


def test_audit_picks_single_column_in_range_and_flags_ambiguous():
    specs = {bs.normalize("機種A"): {"name": "機種A", "per": {1: 1 / 400, 6: 1 / 250}, "rng": None}}
    games = [3000.0] * 400
    # rbがスペック範囲(1/400〜1/250)に入り、bbは範囲外(1/100)。台日300以上。
    days = pd.DataFrame(
        {"machine_name": ["機種A"] * 400, "g": games, "bb": [30] * 400, "rb": [9, 10, 8, 11] * 100, "hall": ["h"] * 400}
    )
    result = audit.audit(days, specs)
    row = result.iloc[0]
    assert row["verdict"] == "A" and row["column"] == "rb" and row["hall"] == "h"
    # bbもrbも範囲内なら列を特定できないのでB
    both = days.assign(bb=[10] * 400)
    assert audit.audit(both, specs).iloc[0]["verdict"] == "B"
    # 台日が少なければAにしない
    few = days.head(100)
    assert audit.audit(few, specs).iloc[0]["verdict"] == "B"


def test_audit_treats_bb_rb_sum_as_same_column_when_bb_is_always_zero():
    specs = {bs.normalize("機種A"): {"name": "機種A", "per": {1: 1 / 400, 6: 1 / 250}, "rng": None}}
    days = pd.DataFrame(
        {
            "machine_name": ["機種A"] * 400,
            "g": [3000.0] * 400,
            "bb": [0] * 400,
            "rb": [9, 10, 8, 11] * 100,
            "hall": ["h"] * 400,
        }
    )
    row = audit.audit(days, specs).iloc[0]
    assert row["verdict"] == "A" and row["column"] == "rb"  # bb+rbはrbと同じ値なので、列が2つ範囲に入った扱いにしない


def test_audit_is_per_hall_and_flags_inconsistent_halls():
    specs = {bs.normalize("機種A"): {"name": "機種A", "per": {1: 1 / 400, 6: 1 / 250}, "rng": None}}
    frames = []
    # 4ホールのうち3ホールはrbがスペック範囲内(約1/300)、1ホールは範囲外(約1/600)
    for hall, rb in (("h1", 10), ("h2", 10), ("h3", 10), ("h4", 5)):
        frames.append(
            pd.DataFrame(
                {
                    "machine_name": ["機種A"] * 400,
                    "g": [3000.0] * 400,
                    "bb": [30] * 400,
                    "rb": [rb] * 400,
                    "hall": [hall] * 400,
                }
            )
        )
    result = audit.audit(pd.concat(frames, ignore_index=True), specs).set_index("hall")
    assert result.loc["h1", "verdict"] == "A" and result.loc["h2", "verdict"] == "A"
    assert result.loc["h4", "verdict"] == "X"  # このホールのrbは範囲外。全ホールの平均では範囲内に見えてしまう
    # ホール間の最大÷最小(2倍)が大きいので、不整合の印が付く
    assert bool(result.loc["h1", "across_inconsistent"]) is True and result.loc["h1", "across_ratio"] == 2.0


def test_posterior_prior_shifts_weight_to_low_settings():
    spec = {
        "settings": {
            s: {"bb_probability": None, "rb_probability": p, "combined_probability": None}
            for s, p in {1: 1 / 428, 2: 1 / 410, 5: 1 / 366, 6: 1 / 312}.items()
        }
    }
    uniform = bs.posterior(spec, 3000, None, 9)
    realistic = bs.posterior(spec, 3000, None, 9, prior=bs.REALISTIC_PRIOR)
    assert abs(sum(realistic.values()) - 1) < 1e-9
    assert sum(v for s, v in uniform.items() if s >= 5) > sum(v for s, v in realistic.items() if s >= 5)
    # 既定(prior未指定)は従来どおり一様
    assert bs.posterior(spec, 3000, None, 9) == uniform


def test_apply_at_audit_sets_at_markers_without_touching_judgeable(tmp_path):
    master = tmp_path / "master.csv"
    _write_master(
        master,
        [
            {
                "machine_name": "機種A",
                "canonical_machine_name": "機種A",
                "game_type": "AT",
                "notes": "AT初当り:1/400〜1/250",
            },
            {
                "machine_name": "機種B",
                "canonical_machine_name": "機種B",
                "game_type": "AT",
                "notes": "AT初当り:1/400〜1/250",
            },
        ],
    )
    audit_csv = tmp_path / "audit.csv"
    with open(audit_csv, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["machine", "hall", "verdict", "column"])
        writer.writeheader()
        writer.writerow({"machine": "機種A", "hall": "ホール1", "verdict": "A", "column": "bb"})
        writer.writerow({"machine": "機種B", "hall": "ホール1", "verdict": "B", "column": "bb,rb"})
        writer.writerow({"machine": "機種B", "hall": "ホール2", "verdict": "A", "column": "rb"})

    def fresh():
        return {
            bs.normalize(n): {"family_name": n, "category": "AT", "settings": {}, "judgeable": False, "source": "1geki"}
            for n in ("機種A", "機種B")
        }

    # ホール間のばらつきが大きい(across_inconsistent)機種は、Aでも使わない
    skip_csv = tmp_path / "audit_skip.csv"
    with open(skip_csv, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["machine", "hall", "verdict", "column", "across_inconsistent"])
        writer.writeheader()
        writer.writerow(
            {"machine": "機種A", "hall": "ホール1", "verdict": "A", "column": "bb", "across_inconsistent": "True"}
        )
        writer.writerow(
            {"machine": "機種B", "hall": "ホール1", "verdict": "A", "column": "rb", "across_inconsistent": "False"}
        )
    skipped = {
        bs.normalize(n): {"family_name": n, "category": "AT", "settings": {}, "judgeable": False, "source": "1geki"}
        for n in ("機種A", "機種B")
    }
    bs._apply_at_audit(skipped, master, skip_csv, hall="ホール1")
    assert (
        "at_judgeable" not in skipped[bs.normalize("機種A")] and skipped[bs.normalize("機種B")]["at_judgeable"] is True
    )
    # ホール未指定なら、AT機の判別は有効にしない(bb/rbの意味はホールで違う)
    none = fresh()
    bs._apply_at_audit(none, master, audit_csv)
    assert not any(s.get("at_judgeable") for s in none.values())
    # 別ホールの行は使わない
    other = fresh()
    bs._apply_at_audit(other, master, audit_csv, hall="ホール2")
    assert "at_judgeable" not in other[bs.normalize("機種A")] and other[bs.normalize("機種B")]["at_column"] == "rb"
    specs = fresh()
    bs._apply_at_audit(specs, master, audit_csv, hall="ホール1")
    a, b = specs[bs.normalize("機種A")], specs[bs.normalize("機種B")]
    assert a["at_judgeable"] is True and a["at_column"] == "bb"
    assert a["judgeable"] is False  # 既存の判定は変えない
    assert sorted(a["settings"]) == [1, 2, 3, 4, 5, 6]
    assert a["settings"][1]["bb_probability"] < a["settings"][6]["bb_probability"]
    assert a["settings"][1]["rb_probability"] is None
    assert "at_judgeable" not in b and b["settings"] == {}
    # AT初当りがbb列の機種は、bbとrbを両方渡しても、bbだけで事後確率が出る
    # 3000Gで14回(1/214)は設定6側(1/250)に最も近いので最尤は6。rbの99回は使われない
    post = bs.posterior(a, 3000, 14, 99)
    assert post and max(post, key=post.get) == 6
    assert post == bs.posterior(a, 3000, 14, 0)
