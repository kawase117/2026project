"""
蒲田7 角番×DD 分析: セクションサイズ分割 vs LR分割の効果比較・交互作用分析・物理検証

実装内容:
  1. フロア座標から角番ごとのX座標（左右）を推定
  2. LR分割（左右半分）を機械割で評価
  3. セクションサイズ分割との効果定量比較（F値）
  4. 3軸交互作用分析（セクションサイズ × LR × セグメント）
  5. 物理検証：角番の実際のX座標と分割方法の相関確認
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd
from scipy import stats

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.analysis.kamata_kakuban_section_residual_eda import (
    DEFAULT_MIN_GAMES_ANALYSIS,
    DEFAULT_MIN_SECTION_SIZE,
    _bh_adjust,
    _df_to_markdown,
    _section_size_group,
    infer_hall_name,
)
from ml.analysis.kamata_corner_mirror_analysis import _build_merged_frame

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def _resolve_default_db7() -> Path:
    candidates = [
        path
        for path in (PROJECT_ROOT / "db").glob("*蒲田7*.db")
        if path.is_file() and path.stat().st_size > 0
    ]
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]
    return PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"

DEFAULT_DB_7 = _resolve_default_db7()
DEFAULT_COORDS_7_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
DEFAULT_COORDS_7_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "analysis" / "results" / "kamata7_kakuban_section_lr_interaction"
DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MIN_CELL_GAMES = 100
FULL_KAKUBAN_MIN = 1
FULL_KAKUBAN_MAX = 13
VISUAL_KAKUBAN_MIN = 5
VISUAL_KAKUBAN_MAX = 11
SECTION_SIZE_ORDER = ("small", "medium", "large")
SEGMENT_NAMES = ("2F", "3F", "AT")


def _format_number(value: object, digits: int = 2) -> str:
    if pd.isna(value):
        return "nan"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _table_md(df: pd.DataFrame) -> str:
    if df.empty:
        return "No rows."
    return _df_to_markdown(df)


def _calc_pay_rate(games_sum: pd.Series, diff_sum: pd.Series) -> pd.Series:
    denom = pd.to_numeric(games_sum, errors="coerce") * 3
    denom = denom.replace(0, np.nan)
    return ((denom + pd.to_numeric(diff_sum, errors="coerce")) / denom) * 100


def _attach_section_size_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "section" not in out.columns:
        out["section"] = "unknown"
    out["section"] = out["section"].fillna("unknown").astype(str)
    section_machine_count = out.groupby("section", dropna=False)["machine_number"].transform("nunique")
    out["section_machine_count"] = pd.to_numeric(section_machine_count, errors="coerce").astype("Int64")
    out["section_size"] = out["section_machine_count"]
    out["section_size_group"] = out["section_size"].map(_section_size_group)
    return out


class FloorLayout(NamedTuple):
    """フロア座標データ: 角番ごとのX座標情報"""
    kakuban: int
    x_coord: float
    y_coord: float
    section: str


def load_floor_coordinates(coords_path: Path) -> dict[int, FloorLayout]:
    """フロア座標CSVを読み込んで、kakuban -> FloorLayout のマッピングを作成"""
    if not coords_path.exists():
        print(f"Warning: Floor coordinates not found: {coords_path}")
        return {}

    df = pd.read_csv(coords_path)
    layout = {}

    for _, row in df.iterrows():
        kakuban = int(row.get("kakuban", row.get("rank_from_min", 0)))
        if kakuban in [0, None]:
            continue
        layout[kakuban] = FloorLayout(
            kakuban=kakuban,
            x_coord=float(row.get("X", row.get("x", 0))),
            y_coord=float(row.get("Y", row.get("y", 0))),
            section=str(row.get("section", ""))
        )

    return layout


def add_lr_split(frame: pd.DataFrame, layout: dict, _: dict) -> pd.DataFrame:
    """
    フロア座標を使ってLR分割を推定
    LR: 島内でX座標中央値より左=L, 右=R
    """
    out = frame.copy()
    out["lr_split"] = "Unknown"

    if not layout or out.empty:
        return out

    # rank_from_min または kakuban カラムを使用
    kakuban_col = "rank_from_min" if "rank_from_min" in out.columns else "kakuban"
    if kakuban_col not in out.columns:
        return out

    # section ごとにLR分割を計算
    for section in out["section"].unique():
        if pd.isna(section):
            continue

        section_data = out[out["section"] == section]
        if section_data.empty:
            continue

        # セクション内の kakuban ごとのX座標を取得
        x_coords = []
        kakuban_list = []
        for kakuban in section_data[kakuban_col].unique():
            if kakuban in layout:
                x_coords.append(layout[kakuban].x_coord)
                kakuban_list.append(kakuban)

        if not x_coords:
            continue

        x_median = np.median(x_coords)

        # LR分割を割り当て
        for kakuban in kakuban_list:
            x = layout[kakuban].x_coord
            lr = "L" if x < x_median else "R"
            mask = (out["section"] == section) & (out[kakuban_col] == kakuban)
            out.loc[mask, "lr_split"] = lr

    return out


def calc_f_value_for_split_strategy(df: pd.DataFrame, strategy_col: str, segment: str) -> float:
    """
    分割戦略（セクションサイズ or LR）の説明度をF値で計算

    H0: グループ間に有意な機械割差なし
    """
    if df.empty or strategy_col not in df.columns:
        return np.nan

    df_valid = df[df["pay_rate"].notna()].copy()
    if df_valid.empty:
        return np.nan

    # グループ内・グループ間の分散を計算
    groups = [g["pay_rate"].values for _, g in df_valid.groupby(strategy_col)]
    if len(groups) < 2 or any(len(g) < 2 for g in groups):
        return np.nan

    try:
        f_stat, p_val = stats.f_oneway(*groups)
        return f_stat
    except:
        return np.nan


def _build_floor_frames(
    *,
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
    min_games: int = DEFAULT_MIN_GAMES_ANALYSIS,
) -> dict[str, pd.DataFrame]:
    """フロア別データフレームを構築"""
    hall_name_2f = infer_hall_name(coords_2f, floor="2F")
    hall_name_3f = infer_hall_name(coords_3f, floor="3F")

    frame_2f = _build_merged_frame(
        db_path=db_path,
        coords_path=coords_2f,
        hall_name=hall_name_2f,
        floor="2F",
        min_games=min_games,
    )
    frame_3f = _build_merged_frame(
        db_path=db_path,
        coords_path=coords_3f,
        hall_name=hall_name_3f,
        floor="3F",
        min_games=min_games,
    )

    frame_2f = _attach_section_size_metadata(frame_2f)
    frame_3f = _attach_section_size_metadata(frame_3f)

    return {"2F": frame_2f, "3F": frame_3f}


def _normalize_segment_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """セグメントフレームを正規化"""
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["dd"] = out["date"].dt.day.astype("Int64")
    out["rank_from_min"] = pd.to_numeric(out["rank_from_min"], errors="coerce").astype("Int64")
    if "section_machine_count" not in out.columns:
        out["section_machine_count"] = pd.to_numeric(out.get("section_size"), errors="coerce").astype("Int64")
    if "section_size" not in out.columns or out["section_size"].isna().all():
        out["section_size"] = out["section_machine_count"]
    out["section_size"] = pd.to_numeric(out["section_size"], errors="coerce").astype("Int64")
    if "section_size_group" not in out.columns:
        out["section_size_group"] = pd.Series(pd.NA, index=out.index, dtype="string")
    out["section_size_group"] = out["section_size_group"].astype("string")
    missing_group = out["section_size_group"].isna() | out["section_size_group"].eq("<NA>")
    if missing_group.any():
        out.loc[missing_group, "section_size_group"] = out.loc[missing_group, "section_size"].map(_section_size_group)
    return out


def _build_segment_views(floor_frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """フロア別フレームからセグメント別ビューを構築"""
    frames = {
        "2F": _normalize_segment_frame(floor_frames.get("2F", pd.DataFrame()).copy()),
        "3F": _normalize_segment_frame(floor_frames.get("3F", pd.DataFrame()).copy()),
    }

    # ATは machine_type_segment == "N" を抽出
    at_parts = []
    for floor in ("2F", "3F"):
        frame = floor_frames.get(floor, pd.DataFrame())
        if frame.empty:
            continue
        if "machine_type_segment" in frame.columns:
            at_parts.append(frame[frame["machine_type_segment"].eq("N")].copy())

    frames["AT"] = _normalize_segment_frame(pd.concat(at_parts, ignore_index=True)) if at_parts else pd.DataFrame()
    return frames


def analyze_section_vs_lr(
    db_path: Path,
    coords_2f: Path,
    coords_3f: Path,
    output_dir: Path,
) -> None:
    """メイン分析処理"""
    print("[Phase 1-2] Load floor data...")
    floor_frames = _build_floor_frames(
        db_path=db_path,
        coords_2f=coords_2f,
        coords_3f=coords_3f,
    )

    print("[Phase 1-3] Build segment views...")
    segments = _build_segment_views(floor_frames)

    # 各セグメントで pay_rate を計算
    for seg in SEGMENT_NAMES:
        seg_frame = segments[seg]
        if seg_frame.empty:
            continue
        seg_frame["pay_rate"] = _calc_pay_rate(
            seg_frame["games_normalized"],
            seg_frame["diff_coins_normalized"]
        )
        segments[seg] = seg_frame

    print("[Phase 2] Load floor coordinates...")
    layout_2f = load_floor_coordinates(coords_2f)
    layout_3f = load_floor_coordinates(coords_3f)

    print("[Phase 3] Add LR split...")
    # セグメントごとに正しいレイアウトでLR分割を追加
    layout_map = {"2F": layout_2f, "3F": layout_3f, "AT": layout_2f}
    for seg in SEGMENT_NAMES:
        if segments[seg].empty:
            continue
        layout = layout_map.get(seg, {})
        segments[seg] = add_lr_split(segments[seg].copy(), layout, {})

    # 2. DD × セクションサイズ × LR の3軸集計
    print("[Phase 4] Aggregate by DD × SectionSize × LR...")
    results_3axis = []
    for seg_name, seg_data in segments.items():
        if seg_data.empty:
            continue

        # DD列の存在確認
        if "dd" not in seg_data.columns:
            print(f"Warning: 'dd' column not found in {seg_name} segment")
            continue

        for dd in range(1, 32):
            dd_data = seg_data[seg_data["dd"] == dd]
            if dd_data.empty:
                continue

            for section_size in SECTION_SIZE_ORDER:
                size_data = dd_data[dd_data["section_size_group"] == section_size]
                if size_data.empty:
                    continue

                for lr in ["L", "R"]:
                    lr_data = size_data[size_data["lr_split"] == lr]
                    if lr_data.empty:
                        continue

                    games_sum = lr_data["games_normalized"].sum()
                    diff_sum = lr_data["diff_coins_normalized"].sum()
                    pay_rate = _calc_pay_rate(pd.Series([games_sum]), pd.Series([diff_sum])).iloc[0]

                    results_3axis.append({
                        "dd": dd,
                        "segment": seg_name,
                        "section_size": section_size,
                        "lr": lr,
                        "games": games_sum,
                        "pay_rate": pay_rate,
                        "n_machines": lr_data["machine_number"].nunique() if "machine_number" in lr_data.columns else 0,
                    })

    df_3axis = pd.DataFrame(results_3axis)

    # 3. 効果定量比較（F値）
    print("[Phase 5] Calculate F-values for section_size vs LR...")
    f_values = {}

    for seg_name in SEGMENT_NAMES:
        seg_data = segments[seg_name]
        seg_3axis = df_3axis[df_3axis["segment"] == seg_name].copy()

        # セクションサイズの説明度
        f_section = calc_f_value_for_split_strategy(seg_data, "section_size_group", seg_name)

        # LRの説明度
        f_lr = calc_f_value_for_split_strategy(seg_data, "lr_split", seg_name)

        f_values[seg_name] = {
            "section_size_f": f_section,
            "lr_f": f_lr,
            "section_size_better": f_section > f_lr if not (np.isnan(f_section) or np.isnan(f_lr)) else None,
        }

    df_f_values = pd.DataFrame(f_values).T

    # 4. 交互作用分析（3軸）- DD固定で section_size × LR × segment
    print("[Phase 6] Analyze interaction effects...")
    interaction_results = []

    for dd in range(1, 32):
        dd_3axis = df_3axis[df_3axis["dd"] == dd]
        if dd_3axis.empty:
            continue

        for seg_name in SEGMENT_NAMES:
            seg_3axis = dd_3axis[dd_3axis["segment"] == seg_name]
            if seg_3axis.empty:
                continue

            # セクションサイズ × LR の交互作用
            pivot = seg_3axis.pivot_table(
                index="section_size",
                columns="lr",
                values="pay_rate",
                aggfunc="first"
            )

            if pivot.empty or pivot.shape != (3, 2):
                continue

            # 交互作用：main effect からのズレ
            for section_size in SECTION_SIZE_ORDER:
                for lr in ["L", "R"]:
                    if section_size not in pivot.index or lr not in pivot.columns:
                        continue

                    observed = pivot.loc[section_size, lr]
                    if pd.isna(observed):
                        continue

                    # 主効果の平均
                    section_effect = seg_3axis[seg_3axis["section_size"] == section_size]["pay_rate"].mean()
                    lr_effect = seg_3axis[seg_3axis["lr"] == lr]["pay_rate"].mean()
                    grand_mean = seg_3axis["pay_rate"].mean()

                    # 交互作用 = observed - (section_effect + lr_effect - grand_mean)
                    expected = section_effect + lr_effect - grand_mean
                    interaction = observed - expected

                    interaction_results.append({
                        "dd": dd,
                        "segment": seg_name,
                        "section_size": section_size,
                        "lr": lr,
                        "observed_pay_rate": observed,
                        "expected_pay_rate": expected,
                        "interaction_effect": interaction,
                    })

    df_interaction = pd.DataFrame(interaction_results)

    # 5. 物理検証：角番のX座標と分割方法の相関
    print("[Phase 7] Physical verification...")
    physical_validation = []

    layout_map = {"2F": layout_2f, "3F": layout_3f, "AT": layout_2f}

    for seg_name in SEGMENT_NAMES:
        layout = layout_map.get(seg_name, {})
        if not layout:
            continue

        seg_data = segments[seg_name]
        if seg_data.empty:
            continue

        # kakuban カラムを決定
        kakuban_col = "rank_from_min" if "rank_from_min" in seg_data.columns else "kakuban"
        if kakuban_col not in seg_data.columns:
            continue

        for section in seg_data["section"].unique():
            if pd.isna(section):
                continue

            section_data = seg_data[seg_data["section"] == section]
            if section_data.empty:
                continue

            for kakuban in section_data[kakuban_col].unique():
                if kakuban not in layout:
                    continue

                kakuban_data = section_data[section_data[kakuban_col] == kakuban]
                if kakuban_data.empty:
                    continue

                x_coord = layout[kakuban].x_coord

                # その角番の分類
                section_size_group = kakuban_data["section_size_group"].iloc[0]
                lr_split = kakuban_data["lr_split"].iloc[0]
                pay_rate_val = kakuban_data["pay_rate"].iloc[0] if "pay_rate" in kakuban_data.columns else np.nan

                physical_validation.append({
                    "segment": seg_name,
                    "section": section,
                    "kakuban": kakuban,
                    "x_coord": x_coord,
                    "section_size_group": section_size_group,
                    "lr_split": lr_split,
                    "avg_pay_rate": pay_rate_val,
                })

    df_physical = pd.DataFrame(physical_validation)

    # 出力
    print("[Phase 8] Writing output files...")

    df_3axis.to_csv(output_dir / "kamata7_3axis_aggregation.csv", index=False)
    df_f_values.to_csv(output_dir / "kamata7_f_values_comparison.csv")
    df_interaction.to_csv(output_dir / "kamata7_interaction_analysis.csv", index=False)
    df_physical.to_csv(output_dir / "kamata7_physical_validation.csv", index=False)

    # レポート作成
    report = _generate_report(df_3axis, df_f_values, df_interaction, df_physical)
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    print(f"[OK] Output written to {output_dir}/")


def _generate_report(df_3axis, df_f_values, df_interaction, df_physical) -> str:
    """レポート生成"""
    lines = [
        "# 蒲田7 セクションサイズ vs LR分割 分析レポート",
        "",
        "## 1. F値比較（分割戦略の説明度）",
        "",
        _table_md(df_f_values.reset_index().rename(columns={"index": "segment"})),
        "",
        "## 2. 3軸集計（DD × セクションサイズ × LR）",
        "",
        f"Total rows: {len(df_3axis)}",
        "",
        _table_md(df_3axis.head(20)),
        "",
        "## 3. 交互作用分析",
        "",
        f"Interaction effects: {len(df_interaction)} combinations",
        "",
        "### Top 10 Positive Interactions",
        _table_md(df_interaction.nlargest(10, "interaction_effect")[
            ["dd", "segment", "section_size", "lr", "interaction_effect"]
        ]),
        "",
        "### Top 10 Negative Interactions",
        _table_md(df_interaction.nsmallest(10, "interaction_effect")[
            ["dd", "segment", "section_size", "lr", "interaction_effect"]
        ]),
        "",
        "## 4. 物理検証（角番X座標との相関）",
        "",
        f"Physical validation points: {len(df_physical)}",
        "",
        _table_md(df_physical.head(20)),
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Kakuban section/LR analysis")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_7, help="Database path")
    parser.add_argument("--coords-2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords-3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)

    args = parser.parse_args()

    analyze_section_vs_lr(
        args.db,
        args.coords_2f,
        args.coords_3f,
        args.output,
    )


if __name__ == "__main__":
    main()
