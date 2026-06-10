"""Generate a standalone HTML report that shows Kamata7 2F and 3F together."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

try:
    from Heatmap.coordinate_utils import get_display_columns
except ModuleNotFoundError:
    from coordinate_utils import get_display_columns


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_OUTPUT_PATH = Path(__file__).with_name("kamata7_2f_3f_heatmap.html")
HALL_NAME = "マルハンメガシティ2000-蒲田7"

FLOOR_CONFIGS = {
    "2F": {
        "coords_path": Path(__file__).with_name("2F_floor_coordinates_kamata7.csv"),
        "title": "蒲田7 2F",
    },
    "3F": {
        "coords_path": Path(__file__).with_name("3F_floor_coordinates_kamata7.csv"),
        "title": "蒲田7 3F",
    },
}


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    colorscale: str
    zmin: float
    zmax: float
    zmid: float | None
    format_string: str


METRICS: dict[str, MetricSpec] = {
    "win_rate": MetricSpec("win_rate", "勝率(%)", "RdYlGn", 0.0, 100.0, None, "{:.1f}%"),
    "avg_diff": MetricSpec("avg_diff", "平均差枚", "RdYlGn", 0.0, 0.0, 0.0, "{:.0f}枚"),
    "avg_games": MetricSpec("avg_games", "平均G数", "Blues", 0.0, 0.0, None, "{:.0f}G"),
}


def build_kamata7_dual_html(
    *,
    output_path: Path | None = None,
    metric_key: str = "win_rate",
) -> str:
    """Return the HTML document and optionally write it to disk."""

    stats_df, date_range_label = _load_machine_stats()
    floor_frames = {
        floor: _load_floor_frame(config["coords_path"], floor)
        for floor, config in FLOOR_CONFIGS.items()
    }
    if metric_key not in METRICS:
        raise ValueError(f"Unsupported metric_key: {metric_key}")
    metric = METRICS[metric_key]

    floor_cards = []
    for floor, frame in floor_frames.items():
        merged = frame.merge(stats_df, on="machine_number", how="left")
        floor_cards.append(
            _render_floor_summary_card(
                floor,
                merged,
                date_range_label,
                metric_label=metric.label,
                metric_key=metric.key,
            )
        )

    if metric.key in {"avg_diff", "avg_games"}:
        zmin = float(stats_df[metric.key].min())
        zmax = float(stats_df[metric.key].max())
        if metric.key == "avg_diff":
            limit = max(abs(zmin), abs(zmax))
            zmin, zmax = -limit, limit
    else:
        zmin, zmax = metric.zmin, metric.zmax

    figures = []
    for floor, frame in floor_frames.items():
        merged = frame.merge(stats_df, on="machine_number", how="left")
        figures.append(
            _build_heatmap_figure(
                floor=floor,
                title=f"{FLOOR_CONFIGS[floor]['title']} / {metric.label}",
                data=merged,
                metric=metric,
                zmin=zmin,
                zmax=zmax,
            )
        )

    html = _render_page(
        floor_cards=floor_cards,
        metric_section=_render_metric_section(
            metric_label=metric.label,
            figures=figures,
        ),
        generated_at=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        date_range_label=date_range_label,
        metric_label=metric.label,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    return html


def _load_machine_stats() -> tuple[pd.DataFrame, str]:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"DB file not found: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        raw = pd.read_sql_query(
            """
            SELECT date, machine_number, diff_coins_normalized, games_normalized
            FROM machine_detailed_results
            """,
            conn,
        )

    if raw.empty:
        raise ValueError("machine_detailed_results is empty")

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d")
    date_range_label = f"{raw['date'].min():%Y-%m-%d} 〜 {raw['date'].max():%Y-%m-%d}"

    stats_df = raw.groupby("machine_number").agg(
        avg_diff=("diff_coins_normalized", "mean"),
        win_rate=("diff_coins_normalized", lambda series: (series > 0).mean() * 100),
        avg_games=("games_normalized", "mean"),
    )
    stats_df = stats_df.reset_index()
    stats_df["machine_number"] = stats_df["machine_number"].astype(int)
    return stats_df, date_range_label


def _load_floor_frame(coords_path: Path, floor: str) -> pd.DataFrame:
    coords_df = pd.read_csv(coords_path, dtype=str)
    for column in ("machine_number", "X", "Y", "display_x", "display_y"):
        if column in coords_df.columns:
            coords_df[column] = pd.to_numeric(coords_df[column], errors="coerce")

    coords_df["machine_number"] = coords_df["machine_number"].astype(int)
    coords_df["floor"] = floor
    return coords_df


def _build_heatmap_figure(
    *,
    floor: str,
    title: str,
    data: pd.DataFrame,
    metric: MetricSpec,
    zmin: float,
    zmax: float,
) -> go.Figure:
    x_axis_col, y_axis_col = get_display_columns(data.columns)
    max_x = int(data[x_axis_col].max())
    max_y = int(data[y_axis_col].max())

    z_mat = np.full((max_y, max_x), np.nan)
    machine_numbers = np.full((max_y, max_x), "", dtype=object)
    metric_values = np.full((max_y, max_x), "", dtype=object)

    for _, row in data.iterrows():
        x_index = int(row[x_axis_col]) - 1
        y_index = int(row[y_axis_col]) - 1
        machine_numbers[y_index, x_index] = str(int(row["machine_number"]))

        value = row[metric.key]
        if pd.notna(value):
            z_mat[y_index, x_index] = float(value)
            metric_values[y_index, x_index] = metric.format_string.format(float(value))

    hover_label = metric.label
    figure = go.Figure(
        data=go.Heatmap(
            z=z_mat,
            x=list(range(1, max_x + 1)),
            y=list(range(1, max_y + 1)),
            colorscale=metric.colorscale,
            customdata=np.stack([machine_numbers, metric_values], axis=-1),
            hovertemplate=(
                "<b>台番号: %{customdata[0]}</b><br>"
                f"{escape(hover_label)}: %{{customdata[1]}}<br>"
                "X=%{x}, Y=%{y}<extra></extra>"
            ),
            zmin=zmin,
            zmax=zmax,
            zmid=metric.zmid,
            xgap=0.5,
            ygap=0.5,
        )
    )
    figure.update_traces(
        colorbar=dict(
            title=dict(text=metric.label, side="right"),
            thickness=16,
            len=0.72,
        )
    )
    figure.update_layout(
        title=dict(text=title, x=0.5, xanchor="center", font=dict(size=18)),
        height=680,
        hovermode="closest",
        yaxis=dict(
            autorange="reversed",
            side="left",
            showgrid=True,
            gridwidth=0.5,
            gridcolor="rgba(148, 163, 184, 0.18)",
        ),
        xaxis=dict(
            showgrid=True,
            gridwidth=0.5,
            gridcolor="rgba(148, 163, 184, 0.18)",
        ),
        font=dict(family="Arial, sans-serif", size=11, color="#0f172a"),
        margin=dict(l=50, r=90, t=70, b=50),
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="white",
    )
    figure.update_yaxes(scaleanchor="x", scaleratio=1)
    figure.update_xaxes(scaleanchor="y", scaleratio=1)
    return figure


def _render_floor_summary_card(
    floor: str,
    data: pd.DataFrame,
    date_range_label: str,
    *,
    metric_label: str,
    metric_key: str,
) -> str:
    summary_value = data[metric_key].mean()
    max_value = data[metric_key].max()
    return f"""
      <section class="rounded-3xl border border-slate-200 bg-white/90 p-6 shadow-sm shadow-slate-200/60">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.22em] text-amber-700">{escape(floor)}</p>
            <h3 class="mt-2 text-2xl font-semibold text-slate-900">{escape(HALL_NAME)}</h3>
            <p class="mt-2 text-sm leading-6 text-slate-600">集計期間: {escape(date_range_label)}</p>
          </div>
          <div class="rounded-2xl bg-amber-50 px-4 py-3 text-right">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-amber-700">Machines</p>
            <p class="text-2xl font-bold text-amber-900">{len(data)}</p>
          </div>
        </div>
        <div class="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-2xl bg-slate-50 p-3">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">平均{escape(metric_label)}</p>
            <p class="mt-1 text-lg font-semibold text-slate-900">{summary_value:.1f}</p>
          </div>
          <div class="rounded-2xl bg-slate-50 p-3">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">最高{escape(metric_label)}</p>
            <p class="mt-1 text-lg font-semibold text-slate-900">{max_value:.1f}</p>
          </div>
        </div>
      </section>
    """


def _render_metric_section(*, metric_label: str, figures: list[go.Figure]) -> str:
    figure_html = []
    for figure in figures:
        figure_html.append(
            pio.to_html(
                figure,
                full_html=False,
                include_plotlyjs=False,
                config={"responsive": True, "displaylogo": False},
                default_width="100%",
                default_height="100%",
            )
        )

    return f"""
      <section class="rounded-3xl border border-slate-200 bg-white/90 p-6 shadow-sm shadow-slate-200/60">
        <div class="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">Metric</p>
            <h3 class="mt-2 text-2xl font-semibold text-slate-900">{escape(metric_label)}</h3>
          </div>
          <p class="text-sm text-slate-500">2F と 3F を同じ指標・同じ期間で横並び表示</p>
        </div>
        <div class="mt-6 grid gap-6 lg:grid-cols-2">
          {''.join(
              f'<div class="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 p-2">{html}</div>'
              for html in figure_html
          )}
        </div>
      </section>
    """


def _render_page(
    *,
    floor_cards: list[str],
    metric_section: str,
    generated_at: str,
    date_range_label: str,
    metric_label: str,
) -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(HALL_NAME)} 2F / 3F 同時ヒートマップ</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
  <style>
    body {{
      background:
        radial-gradient(circle at top left, rgba(251, 191, 36, 0.16), transparent 28%),
        radial-gradient(circle at top right, rgba(148, 163, 184, 0.22), transparent 28%),
        linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
    }}
  </style>
</head>
<body class="text-slate-900">
  <main class="mx-auto max-w-[1800px] px-4 py-6 sm:px-6 lg:px-8">
    <section class="rounded-[2rem] border border-slate-200 bg-white/90 p-6 shadow-xl shadow-slate-200/40 sm:p-8">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div class="max-w-3xl">
          <p class="text-xs font-semibold uppercase tracking-[0.3em] text-amber-700">Heatmap Report</p>
          <h1 class="mt-3 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">
            {escape(HALL_NAME)} 2F / 3F 同時ヒートマップ
          </h1>
          <p class="mt-3 text-base leading-7 text-slate-600">
            2F と 3F を同一指標・同一期間で並べて比較できる静的 HTML レポートです。
          </p>
        </div>
        <div class="grid gap-3 sm:grid-cols-2 lg:min-w-[360px]">
          <div class="rounded-2xl bg-slate-50 p-4">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Hall</p>
            <p class="mt-1 text-lg font-semibold text-slate-900">{escape(HALL_NAME)}</p>
          </div>
          <div class="rounded-2xl bg-slate-50 p-4">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Generated</p>
            <p class="mt-1 text-lg font-semibold text-slate-900">{escape(generated_at)}</p>
          </div>
          <div class="rounded-2xl bg-slate-50 p-4 sm:col-span-2">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Date Range</p>
            <p class="mt-1 text-lg font-semibold text-slate-900">{escape(date_range_label)}</p>
          </div>
        </div>
      </div>
      <div class="mt-6 flex flex-wrap gap-3">
        <span class="rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white shadow-sm shadow-amber-200">{escape(metric_label)}</span>
      </div>
    </section>

    <section class="mt-6 grid gap-6 xl:grid-cols-2">
      {''.join(floor_cards)}
    </section>

    <section class="mt-6">
      {metric_section}
    </section>
  </main>
</body>
</html>
"""


def main() -> int:
    build_kamata7_dual_html(output_path=DEFAULT_OUTPUT_PATH)
    print(f"Wrote {DEFAULT_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
