from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("2025-01-01", "2025-03-01", freq="7D")

    spec = [
        {
            "machine_number": 3008,
            "machine_name": "A-3008",
            "floor": "3F",
            "side": "L",
            "seg": "N",
            "section": "3001-3016",
            "rank_from_min": 8,
            "rank_from_max": 9,
            "kakuban": 8,
        },
        {
            "machine_number": 3009,
            "machine_name": "A-3009",
            "floor": "3F",
            "side": "L",
            "seg": "N",
            "section": "3001-3016",
            "rank_from_min": 9,
            "rank_from_max": 8,
            "kakuban": 9,
        },
        {
            "machine_number": 3018,
            "machine_name": "A-3018",
            "floor": "3F",
            "side": "L",
            "seg": "N",
            "section": "3017-3032",
            "rank_from_min": 1,
            "rank_from_max": 2,
            "kakuban": 1,
        },
        {
            "machine_number": 3019,
            "machine_name": "A-3019",
            "floor": "3F",
            "side": "L",
            "seg": "N",
            "section": "3017-3032",
            "rank_from_min": 2,
            "rank_from_max": 1,
            "kakuban": 2,
        },
        {
            "machine_number": 3028,
            "machine_name": "A-3028",
            "floor": "3F",
            "side": "L",
            "seg": "N",
            "section": "3017-3032",
            "rank_from_min": 3,
            "rank_from_max": 4,
            "kakuban": 3,
        },
        {
            "machine_number": 3029,
            "machine_name": "A-3029",
            "floor": "3F",
            "side": "L",
            "seg": "N",
            "section": "3017-3032",
            "rank_from_min": 4,
            "rank_from_max": 3,
            "kakuban": 4,
        },
        {
            "machine_number": 2201,
            "machine_name": "B-2201",
            "floor": "2F",
            "side": "L",
            "seg": "N",
            "section": "2201-2216",
            "rank_from_min": 5,
            "rank_from_max": 12,
            "kakuban": 5,
        },
        {
            "machine_number": 2202,
            "machine_name": "B-2202",
            "floor": "2F",
            "side": "L",
            "seg": "N",
            "section": "2201-2216",
            "rank_from_min": 6,
            "rank_from_max": 11,
            "kakuban": 6,
        },
        {
            "machine_number": 3309,
            "machine_name": "C-3309",
            "floor": "3F",
            "side": "R",
            "seg": "A",
            "section": "3301-3312",
            "rank_from_min": 9,
            "rank_from_max": 4,
            "kakuban": 9,
        },
        {
            "machine_number": 3310,
            "machine_name": "C-3310",
            "floor": "3F",
            "side": "R",
            "seg": "A",
            "section": "3301-3312",
            "rank_from_min": 10,
            "rank_from_max": 3,
            "kakuban": 10,
        },
        {
            "machine_number": 3301,
            "machine_name": "C-3301",
            "floor": "3F",
            "side": "R",
            "seg": "A",
            "section": "3301-3312",
            "rank_from_min": 1,
            "rank_from_max": 12,
            "kakuban": 1,
        },
        {
            "machine_number": 3302,
            "machine_name": "C-3302",
            "floor": "3F",
            "side": "R",
            "seg": "A",
            "section": "3301-3312",
            "rank_from_min": 2,
            "rank_from_max": 11,
            "kakuban": 2,
        },
        {
            "machine_number": 3209,
            "machine_name": "A-3209",
            "floor": "3F",
            "side": "L",
            "seg": "A",
            "section": "3201-3212",
            "rank_from_min": 9,
            "rank_from_max": 4,
            "kakuban": 9,
        },
        {
            "machine_number": 3210,
            "machine_name": "A-3210",
            "floor": "3F",
            "side": "L",
            "seg": "A",
            "section": "3201-3212",
            "rank_from_min": 10,
            "rank_from_max": 3,
            "kakuban": 10,
        },
        {
            "machine_number": 3201,
            "machine_name": "A-3201",
            "floor": "3F",
            "side": "L",
            "seg": "A",
            "section": "3201-3212",
            "rank_from_min": 1,
            "rank_from_max": 12,
            "kakuban": 1,
        },
        {
            "machine_number": 3202,
            "machine_name": "A-3202",
            "floor": "3F",
            "side": "L",
            "seg": "A",
            "section": "3201-3212",
            "rank_from_min": 2,
            "rank_from_max": 11,
            "kakuban": 2,
        },
        {
            "machine_number": 1111,
            "machine_name": "Z-1111",
            "floor": "2F",
            "side": "R",
            "seg": "N",
            "section": "1111-1122",
            "rank_from_min": 1,
            "rank_from_max": 1,
            "kakuban": 1,
        },
        {
            "machine_number": 2222,
            "machine_name": "Z-2222",
            "floor": "2F",
            "side": "R",
            "seg": "N",
            "section": "2222-2233",
            "rank_from_min": 2,
            "rank_from_max": 2,
            "kakuban": 2,
        },
    ]

    for date in dates:
        weekday = date.day_name()
        dd = int(date.strftime("%d"))
        for item in spec:
            diff = 10.0
            if item["machine_number"] in {3008, 3009}:
                diff = 120.0 if item["machine_number"] == 3008 else 110.0
                if weekday == "Saturday":
                    diff += 30.0
            elif item["machine_number"] in {3018, 3019}:
                diff = 20.0
            elif item["machine_number"] in {2201, 2202}:
                diff = 70.0 if weekday == "Saturday" else 5.0
            elif item["machine_number"] in {3309, 3310}:
                if 19 <= dd <= 24:
                    diff = 140.0 if item["machine_number"] == 3309 else 90.0
                else:
                    diff = 15.0
            elif item["machine_number"] in {1111, 2222}:
                diff = 95.0 if item["machine_number"] == 1111 else 85.0
            rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "machine_number": item["machine_number"],
                    "machine_name": item["machine_name"],
                    "floor": item["floor"],
                    "side": item["side"],
                    "seg": item["seg"],
                    "section": item["section"],
                    "rank_from_min": item["rank_from_min"],
                    "rank_from_max": item["rank_from_max"],
                    "kakuban": item["kakuban"],
                    "machine_digit": str(item["machine_number"] % 10),
                    "games": 1600,
                    "diff": diff,
                }
            )
    return pd.DataFrame(rows)


def test_step1_digit_top2_share() -> None:
    from eda import kamata7_machine_dependency_audit as audit

    artifacts = audit.build_all_artifacts(_make_frame())
    step1 = artifacts["step1_digit_dependency"]
    summary = step1.loc[step1["row_type"].astype(str) == "summary"]
    d8 = summary.loc[summary["target"].eq("d8")].iloc[0]
    assert d8["segment"] == "3F_L_N"
    assert float(d8["top2_share"]) > 50.0
    assert pd.notna(d8["excluded_p"])


def test_step3_kakuban_per_segment() -> None:
    from eda import kamata7_machine_dependency_audit as audit

    artifacts = audit.build_all_artifacts(_make_frame())
    step3 = artifacts["step3_kakuban_dependency"]
    summary = step3.loc[step3["row_type"].astype(str) == "summary"]
    assert set(summary["segment"].astype(str)) == {"2F_L_N", "2F_R_N", "3F_L_A", "3F_L_N", "3F_R_A", "3F_R_N"}
    target = summary.loc[summary["segment"].eq("3F_L_A")].iloc[0]
    assert target["target"] == "5-11 vs 1-3"
    assert pd.notna(target["top2_share"])


def test_step6_summary_all_axes() -> None:
    from eda import kamata7_machine_dependency_audit as audit

    artifacts = audit.build_all_artifacts(_make_frame())
    summary = artifacts["step6_summary"]
    assert list(summary.columns) == ["axis", "segment", "target", "top2_share", "original_p", "excluded_p", "verdict"]
    assert set(summary["axis"].astype(str)) == {
        "digit_d8",
        "digit_d9",
        "saturday_at",
        "kakuban_mid",
        "dd_kakuban",
        "zorome",
    }


def test_report_creates_files(tmp_path: Path) -> None:
    from eda import kamata7_machine_dependency_audit as audit

    artifacts = audit.build_all_artifacts(_make_frame())
    outdir = tmp_path / "kamata7_machine_dependency"
    outdir.mkdir(parents=True, exist_ok=True)
    audit._write_csv(artifacts["step1_digit_dependency"], outdir / "step1_digit_dependency.csv")
    audit._write_csv(artifacts["step2_saturday_dependency"], outdir / "step2_saturday_dependency.csv")
    audit._write_csv(artifacts["step3_kakuban_dependency"], outdir / "step3_kakuban_dependency.csv")
    audit._write_csv(artifacts["step4_dd_kakuban_dependency"], outdir / "step4_dd_kakuban_dependency.csv")
    audit._write_csv(artifacts["step5_zorome_dependency"], outdir / "step5_zorome_dependency.csv")
    audit._write_csv(artifacts["step6_summary"], outdir / "step6_summary.csv")
    audit._write_text(outdir / "report.md", audit.build_report(artifacts))

    for name in [
        "step1_digit_dependency.csv",
        "step2_saturday_dependency.csv",
        "step3_kakuban_dependency.csv",
        "step4_dd_kakuban_dependency.csv",
        "step5_zorome_dependency.csv",
        "step6_summary.csv",
        "report.md",
    ]:
        assert (outdir / name).exists()
