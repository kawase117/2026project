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
    assert audit.column_in_range(1 / 450, bounds)  # 下側+15%以内
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
    assert row["verdict"] == "A" and row["column"] == "rb"
    # bbもrbも範囲内なら列を特定できないのでB
    both = days.assign(bb=[10] * 400)
    assert audit.audit(both, specs).iloc[0]["verdict"] == "B"
    # 台日が少なければAにしない
    few = days.head(100)
    assert audit.audit(few, specs).iloc[0]["verdict"] == "B"


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
        writer = csv.DictWriter(handle, fieldnames=["machine", "verdict", "column"])
        writer.writeheader()
        writer.writerow({"machine": "機種A", "verdict": "A", "column": "bb"})
        writer.writerow({"machine": "機種B", "verdict": "B", "column": "bb,rb"})
    specs = {
        bs.normalize(n): {"family_name": n, "category": "AT", "settings": {}, "judgeable": False, "source": "1geki"}
        for n in ("機種A", "機種B")
    }
    bs._apply_at_audit(specs, master, audit_csv)
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
