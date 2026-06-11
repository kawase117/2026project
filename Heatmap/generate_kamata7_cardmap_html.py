"""Generate a standalone HTML prototype for the Kamata7 floor map.

This prototype intentionally avoids Plotly. It renders each machine as an
absolutely positioned HTML card so we can validate whether the visual shape
matches the requested floor-map style before replacing ``page_17_heatmap``.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pandas as pd

try:
    from Heatmap.coordinate_utils import get_display_columns
except ModuleNotFoundError:
    from coordinate_utils import get_display_columns


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田7.db"
DEFAULT_OUTPUT_PATH = Path(__file__).with_name("kamata7_cardmap_preview.html")
HALL_NAME = "マルハンメガシティ2000-蒲田7"


@dataclass(frozen=True)
class FloorSpec:
    floor: str
    title: str
    coords_path: Path


@dataclass(frozen=True)
class ToneThresholds:
    strong_positive: float
    positive: float
    negative: float
    strong_negative: float


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    formatter: str


FLOOR_SPECS = (
    FloorSpec(
        floor="2F",
        title="蒲田7 2F",
        coords_path=Path(__file__).with_name("2F_floor_coordinates_kamata7.csv"),
    ),
    FloorSpec(
        floor="3F",
        title="蒲田7 3F",
        coords_path=Path(__file__).with_name("3F_floor_coordinates_kamata7.csv"),
    ),
)

METRICS = {
    "avg_diff": MetricSpec("avg_diff", "平均差枚", "{:+.0f}枚"),
    "win_rate": MetricSpec("win_rate", "勝率", "{:.1f}%"),
    "avg_games": MetricSpec("avg_games", "平均G数", "{:.0f}G"),
}


def load_machine_stats(
    db_path: Path,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Return machine-level stats and the covered date range label."""

    if not db_path.exists():
        raise FileNotFoundError(f"DB file not found: {db_path}")

    query = """
        SELECT
            date,
            machine_number,
            machine_name,
            diff_coins_normalized,
            games_normalized
        FROM machine_detailed_results
    """
    clauses: list[str] = []
    params: list[str] = []
    if start_date is not None:
        clauses.append("date >= ?")
        params.append(start_date)
    if end_date is not None:
        clauses.append("date <= ?")
        params.append(end_date)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY date"

    with sqlite3.connect(db_path) as conn:
        raw = pd.read_sql_query(query, conn, params=params)

    if raw.empty:
        raise ValueError("machine_detailed_results is empty for the selected range")

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d")
    date_range_label = f"{raw['date'].min():%Y-%m-%d} 〜 {raw['date'].max():%Y-%m-%d}"

    stats_df = raw.groupby("machine_number").agg(
        machine_name=(
            "machine_name",
            lambda series: _pick_first_nonempty(series, fallback=""),
        ),
        avg_diff=("diff_coins_normalized", "mean"),
        win_rate=("diff_coins_normalized", lambda series: (series > 0).mean() * 100),
        avg_games=("games_normalized", "mean"),
        sample_days=("date", "nunique"),
        total_games=("games_normalized", "sum"),
    )
    stats_df = stats_df.reset_index()
    stats_df["machine_number"] = stats_df["machine_number"].astype(int)
    return stats_df, date_range_label


def load_floor_coordinates(coords_path: Path) -> pd.DataFrame:
    """Load a floor coordinate CSV and normalize drawing columns."""

    if not coords_path.exists():
        raise FileNotFoundError(f"Coordinate file not found: {coords_path}")

    coords_df = pd.read_csv(coords_path, dtype=str)
    for column in ("machine_number", "X", "Y", "display_x", "display_y"):
        if column in coords_df.columns:
            coords_df[column] = pd.to_numeric(coords_df[column], errors="coerce")

    required_columns = {"machine_number"}
    missing = required_columns - set(coords_df.columns)
    if missing:
        raise ValueError(f"Missing required coordinate columns: {sorted(missing)}")

    coords_df = coords_df.dropna(subset=["machine_number"]).copy()
    coords_df["machine_number"] = coords_df["machine_number"].astype(int)
    return coords_df


def build_tone_thresholds(values: pd.Series) -> ToneThresholds:
    """Derive simple thresholds that keep the palette centered around zero."""

    clean = values.dropna()
    if clean.empty:
        return ToneThresholds(0.0, 0.0, 0.0, 0.0)

    q20 = float(clean.quantile(0.20))
    q40 = float(clean.quantile(0.40))
    q60 = float(clean.quantile(0.60))
    q80 = float(clean.quantile(0.80))

    strong_positive = max(250.0, q80)
    positive = max(50.0, q60)
    negative = min(-50.0, q40)
    strong_negative = min(-250.0, q20)

    if strong_negative > negative:
        strong_negative = negative
    if positive < negative:
        positive = max(positive, 0.0)

    return ToneThresholds(
        strong_positive=strong_positive,
        positive=positive,
        negative=negative,
        strong_negative=strong_negative,
    )


def classify_metric(value: float | None, thresholds: ToneThresholds) -> str:
    """Map a metric value to a tone class used by the HTML cards."""

    if value is None or pd.isna(value):
        return "tone-missing"
    if value >= thresholds.strong_positive:
        return "tone-high"
    if value >= thresholds.positive:
        return "tone-mid"
    if value <= thresholds.strong_negative:
        return "tone-low"
    if value <= thresholds.negative:
        return "tone-cool"
    return "tone-neutral"


def format_metric_value(value: float | None, metric_key: str) -> str:
    """Format a metric for display inside the card badge."""

    if value is None or pd.isna(value):
        return "N/A"
    metric = METRICS[metric_key]
    return metric.formatter.format(float(value))


def _safe_text(value: object, fallback: str = "") -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    return text if text else fallback


def shorten_machine_name(value: str | None, max_length: int = 12) -> str:
    """Shorten long machine names so they fit inside the card."""

    cleaned = _safe_text(value, fallback="未設定")
    if cleaned == "未設定":
        return "未設定"
    cleaned = cleaned.replace("　", " ")
    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1]}…"


def build_floor_frame(coords_path: Path, stats_df: pd.DataFrame) -> pd.DataFrame:
    """Join coordinates and stats for one floor."""

    coords_df = load_floor_coordinates(coords_path)
    merged = coords_df.merge(stats_df, on="machine_number", how="left", validate="one_to_one")

    x_col, y_col = get_display_columns(merged.columns)
    if merged[x_col].isna().any() or merged[y_col].isna().any():
        raise ValueError(f"Missing drawing coordinates in {coords_path}")

    merged[x_col] = merged[x_col].astype(int)
    merged[y_col] = merged[y_col].astype(int)
    return merged


def render_machine_card(
    row: pd.Series,
    *,
    metric_key: str,
    thresholds: ToneThresholds,
    x_col: str,
    y_col: str,
) -> str:
    """Render one absolutely positioned machine card."""

    metric_value = row.get(metric_key)
    tone_class = classify_metric(metric_value, thresholds)
    machine_name = shorten_machine_name(row.get("machine_name"), max_length=14)
    machine_number = int(row["machine_number"])
    metric_label = format_metric_value(metric_value, metric_key)
    full_name = _safe_text(row.get("machine_name"))
    full_metric = METRICS[metric_key].label
    title = (
        f"{machine_number} / {full_name} / {full_metric}: {metric_label}"
        if full_name
        else f"{machine_number} / {full_metric}: {metric_label}"
    )

    return f"""
      <article
        class="machine-card {tone_class}"
        style="left: calc(var(--pad) + ({int(row[x_col])} - 1) * var(--slot-x)); top: calc(var(--pad) + ({int(row[y_col])} - 1) * var(--slot-y));"
        title="{escape(title)}"
        aria-label="{escape(title)}"
      >
        <div class="machine-number">{machine_number}</div>
        <div class="machine-name">{escape(machine_name)}</div>
        <div class="machine-metric">{escape(metric_label)}</div>
      </article>
    """


def render_floor_section(
    frame: pd.DataFrame,
    *,
    floor_label: str,
    metric_key: str,
    thresholds: ToneThresholds,
) -> str:
    """Render one floor card with its machine layout."""

    x_col, y_col = get_display_columns(frame.columns)
    max_x = int(frame[x_col].max())
    max_y = int(frame[y_col].max())

    slot_x = 50
    slot_y = 40
    pad = 20
    map_width = pad * 2 + max_x * slot_x
    map_height = pad * 2 + max_y * slot_y

    machine_cards = [
        render_machine_card(
            row,
            metric_key=metric_key,
            thresholds=thresholds,
            x_col=x_col,
            y_col=y_col,
        )
        for _, row in frame.sort_values([x_col, y_col]).iterrows()
    ]

    summary_metric = frame[metric_key].mean()
    summary_win = frame["win_rate"].mean()
    summary_games = frame["avg_games"].mean()
    summary_count = len(frame)
    section_label = str(frame["section"].iloc[0]) if "section" in frame.columns else "-"
    machine_name_mode = _pick_first_nonempty(frame["machine_name"], fallback=HALL_NAME)

    return f"""
      <section class="floor-shell">
        <div class="floor-head">
          <div>
            <div class="floor-kicker">{escape(floor_label)}</div>
            <h2 class="floor-title">{escape(machine_name_mode)} {escape(floor_label)}</h2>
            <p class="floor-subtitle">集計期間: {escape(frame.attrs.get("date_range_label", "-"))} / セクション: {escape(section_label)}</p>
          </div>
          <div class="floor-summary-grid">
            <div class="summary-pill">
              <span>台数</span>
              <strong>{summary_count}</strong>
            </div>
            <div class="summary-pill">
              <span>{escape(METRICS[metric_key].label)}</span>
              <strong>{_format_summary(summary_metric, metric_key)}</strong>
            </div>
            <div class="summary-pill">
              <span>勝率</span>
              <strong>{summary_win:.1f}%</strong>
            </div>
            <div class="summary-pill">
              <span>平均G数</span>
              <strong>{summary_games:.0f}G</strong>
            </div>
          </div>
        </div>

        <div class="floor-map-wrap">
          <div class="floor-map" style="--slot-x: {slot_x}px; --slot-y: {slot_y}px; --pad: {pad}px; width: {map_width}px; height: {map_height}px;">
            <div class="floor-map-grid"></div>
            {''.join(machine_cards)}
          </div>
        </div>
      </section>
    """


def build_html_document(
    floor_sections: list[str],
    *,
    generated_at: str,
    date_range_label: str,
    metric_key: str,
) -> str:
    """Build the final standalone HTML document."""

    metric_label = METRICS[metric_key].label
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(HALL_NAME)} カード型フロアマップ</title>
  <style>
    :root {{
      color-scheme: light;
      --bg-top: #f8fafc;
      --bg-bottom: #eef2ff;
      --ink: #111827;
      --muted: #64748b;
      --panel: rgba(255, 255, 255, 0.88);
      --panel-border: rgba(148, 163, 184, 0.35);
      --shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
      --radius-xl: 28px;
      --radius-lg: 22px;
      --radius-md: 16px;
      --radius-sm: 12px;
      --font-sans: "Noto Sans JP", "Hiragino Sans", "Yu Gothic UI", "Meiryo", sans-serif;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: var(--font-sans);
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 0%, rgba(251, 191, 36, 0.16), transparent 24%),
        radial-gradient(circle at 88% 0%, rgba(99, 102, 241, 0.16), transparent 22%),
        linear-gradient(180deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
    }}

    .shell {{
      max-width: 1920px;
      margin: 0 auto;
      padding: 24px;
    }}

    .hero {{
      position: relative;
      overflow: hidden;
      padding: 28px;
      border-radius: 32px;
      border: 1px solid var(--panel-border);
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}

    .hero::before,
    .hero::after {{
      content: "";
      position: absolute;
      border-radius: 999px;
      pointer-events: none;
      opacity: 0.8;
    }}

    .hero::before {{
      width: 320px;
      height: 320px;
      right: -120px;
      top: -140px;
      background: radial-gradient(circle, rgba(251, 113, 133, 0.18), transparent 65%);
    }}

    .hero::after {{
      width: 260px;
      height: 260px;
      left: -120px;
      bottom: -150px;
      background: radial-gradient(circle, rgba(59, 130, 246, 0.16), transparent 65%);
    }}

    .hero-grid {{
      position: relative;
      z-index: 1;
      display: grid;
      gap: 20px;
      grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.8fr);
      align-items: end;
    }}

    .eyebrow {{
      margin: 0 0 10px;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.3em;
      text-transform: uppercase;
      color: #b45309;
    }}

    .hero h1 {{
      margin: 0;
      font-size: clamp(30px, 3.4vw, 48px);
      line-height: 1.05;
      letter-spacing: -0.04em;
    }}

    .hero-copy {{
      margin: 16px 0 0;
      font-size: 15px;
      line-height: 1.9;
      color: var(--muted);
      max-width: 62ch;
    }}

    .hero-meta {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}

    .meta-card {{
      padding: 14px 16px;
      border-radius: var(--radius-md);
      background: rgba(248, 250, 252, 0.92);
      border: 1px solid rgba(203, 213, 225, 0.8);
    }}

    .meta-card span {{
      display: block;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: #64748b;
    }}

    .meta-card strong {{
      display: block;
      margin-top: 6px;
      font-size: 17px;
      font-weight: 800;
      color: #0f172a;
    }}

    .badges {{
      margin-top: 16px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid rgba(148, 163, 184, 0.32);
      background: rgba(255, 255, 255, 0.82);
      color: #0f172a;
      font-size: 13px;
      font-weight: 700;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }}

    .badge .swatch {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
    }}

    .badge.high .swatch {{ background: #ef4444; }}
    .badge.mid .swatch {{ background: #fca5a5; }}
    .badge.neutral .swatch {{ background: #f8fafc; border: 1px solid #cbd5e1; }}
    .badge.cool .swatch {{ background: #7dd3fc; }}
    .badge.low .swatch {{ background: #2563eb; }}
    .badge.missing .swatch {{ background: #cbd5e1; }}

    .floor-list {{
      margin-top: 24px;
      display: grid;
      gap: 24px;
    }}

    .floor-shell {{
      overflow: hidden;
      border-radius: 30px;
      border: 1px solid var(--panel-border);
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}

    .floor-head {{
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
      align-items: start;
      padding: 24px 24px 18px;
      border-bottom: 1px solid rgba(203, 213, 225, 0.7);
    }}

    .floor-kicker {{
      font-size: 12px;
      font-weight: 900;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: #b45309;
    }}

    .floor-title {{
      margin: 8px 0 0;
      font-size: 24px;
      line-height: 1.15;
      letter-spacing: -0.03em;
    }}

    .floor-subtitle {{
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.7;
    }}

    .floor-summary-grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}

    .summary-pill {{
      padding: 14px 16px;
      border-radius: var(--radius-md);
      background: rgba(248, 250, 252, 0.88);
      border: 1px solid rgba(203, 213, 225, 0.75);
    }}

    .summary-pill span {{
      display: block;
      color: #64748b;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
    }}

    .summary-pill strong {{
      display: block;
      margin-top: 6px;
      font-size: 18px;
      font-weight: 800;
      color: #0f172a;
    }}

    .floor-map-wrap {{
      overflow-x: auto;
      overflow-y: hidden;
      padding: 18px 18px 24px;
    }}

    .floor-map {{
      position: relative;
      border-radius: 26px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.88), rgba(248, 250, 252, 0.96)),
        repeating-linear-gradient(
          0deg,
          rgba(148, 163, 184, 0.06) 0,
          rgba(148, 163, 184, 0.06) 1px,
          transparent 1px,
          transparent var(--slot-y)
        ),
        repeating-linear-gradient(
          90deg,
          rgba(148, 163, 184, 0.06) 0,
          rgba(148, 163, 184, 0.06) 1px,
          transparent 1px,
          transparent var(--slot-x)
        );
      border: 1px solid rgba(203, 213, 225, 0.8);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
    }}

    .floor-map-grid {{
      position: absolute;
      inset: 0;
      border-radius: inherit;
      pointer-events: none;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.1), rgba(255, 255, 255, 0)),
        radial-gradient(circle at 25% 20%, rgba(251, 113, 133, 0.03), transparent 28%),
        radial-gradient(circle at 74% 78%, rgba(96, 165, 250, 0.04), transparent 28%);
    }}

    .machine-card {{
      position: absolute;
      width: calc(var(--slot-x) - 8px);
      height: calc(var(--slot-y) - 8px);
      border-radius: 14px;
      padding: 5px 5px 4px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2px;
      text-align: center;
      line-height: 1.05;
      border: 1px solid transparent;
      box-shadow: 0 10px 18px rgba(15, 23, 42, 0.08);
      overflow: hidden;
      transition: transform 120ms ease, box-shadow 120ms ease;
    }}

    .machine-card:hover {{
      transform: translateY(-1px);
      box-shadow: 0 14px 22px rgba(15, 23, 42, 0.12);
      z-index: 2;
    }}

    .machine-number {{
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.02em;
    }}

    .machine-name {{
      font-size: 8px;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 100%;
    }}

    .machine-metric {{
      margin-top: 2px;
      padding: 2px 5px;
      border-radius: 999px;
      font-size: 8px;
      font-weight: 800;
      letter-spacing: 0.02em;
      background: rgba(255, 255, 255, 0.55);
    }}

    .tone-high {{
      background: linear-gradient(180deg, #fff1f2 0%, #fecdd3 100%);
      border-color: #ef4444;
      color: #7f1d1d;
    }}

    .tone-mid {{
      background: linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%);
      border-color: #fb923c;
      color: #7c2d12;
    }}

    .tone-neutral {{
      background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
      border-color: #cbd5e1;
      color: #0f172a;
    }}

    .tone-cool {{
      background: linear-gradient(180deg, #eff6ff 0%, #bfdbfe 100%);
      border-color: #3b82f6;
      color: #1e3a8a;
    }}

    .tone-low {{
      background: linear-gradient(180deg, #dbeafe 0%, #93c5fd 100%);
      border-color: #2563eb;
      color: #1e3a8a;
    }}

    .tone-missing {{
      background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
      border-color: #cbd5e1;
      color: #475569;
      opacity: 0.82;
    }}

    .footer-note {{
      margin-top: 20px;
      padding: 18px 22px;
      border-radius: 22px;
      border: 1px solid rgba(203, 213, 225, 0.8);
      background: rgba(255, 255, 255, 0.8);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.8;
    }}

    @media (max-width: 1100px) {{
      .hero-grid,
      .floor-head {{
        grid-template-columns: 1fr;
      }}

      .hero-meta,
      .floor-summary-grid {{
        grid-template-columns: 1fr 1fr;
      }}
    }}

    @media (max-width: 720px) {{
      .shell {{
        padding: 12px;
      }}

      .hero,
      .floor-shell {{
        border-radius: 24px;
      }}

      .hero,
      .floor-head {{
        padding: 18px;
      }}

      .floor-map-wrap {{
        padding: 14px;
      }}

      .hero-meta,
      .floor-summary-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="hero-grid">
          <div>
            <p class="eyebrow">Heatmap Prototype</p>
            <h1>{escape(HALL_NAME)} カード型フロアマップ</h1>
            <p class="hero-copy">
            Plotly のマス目ではなく、台ごとのカードをフロア上に絶対配置する試作です。
            2F/3F の複雑な形状が崩れずに表現できるかを確認するため、まず静的HTMLとして出力します。
            </p>
          <div class="badges">
            <span class="badge high"><span class="swatch"></span>強プラス</span>
            <span class="badge mid"><span class="swatch"></span>弱プラス</span>
            <span class="badge neutral"><span class="swatch"></span>中立</span>
            <span class="badge cool"><span class="swatch"></span>弱マイナス</span>
            <span class="badge low"><span class="swatch"></span>強マイナス</span>
            <span class="badge missing"><span class="swatch"></span>欠損</span>
          </div>
        </div>

        <div class="hero-meta">
          <div class="meta-card">
            <span>Hall</span>
            <strong>{escape(HALL_NAME)}</strong>
          </div>
          <div class="meta-card">
            <span>Generated</span>
            <strong>{escape(generated_at)}</strong>
          </div>
          <div class="meta-card">
            <span>Date Range</span>
            <strong>{escape(date_range_label)}</strong>
          </div>
          <div class="meta-card">
            <span>Metric</span>
            <strong>{escape(metric_label)}</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="floor-list">
      {''.join(floor_sections)}
    </section>

    <section class="footer-note">
      このHTMLは試作です。page_17_heatmap へ移す前に、蒲田7の2F/3Fでカードの位置、文字量、色の粒度が妥当かを確認してください。
    </section>
  </main>
</body>
</html>
"""


def build_kamata7_cardmap_html(
    *,
    output_path: Path | None = None,
    metric_key: str = "avg_diff",
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Build the prototype HTML and optionally persist it."""

    if metric_key not in METRICS:
        raise ValueError(f"Unsupported metric_key: {metric_key}")

    stats_df, date_range_label = load_machine_stats(
        DB_PATH,
        start_date=start_date,
        end_date=end_date,
    )

    floor_sections: list[str] = []
    for spec in FLOOR_SPECS:
        frame = build_floor_frame(spec.coords_path, stats_df)
        frame.attrs["date_range_label"] = date_range_label
        thresholds = build_tone_thresholds(frame[metric_key])
        floor_sections.append(
            render_floor_section(
                frame,
                floor_label=spec.floor,
                metric_key=metric_key,
                thresholds=thresholds,
            )
        )

    html = build_html_document(
        floor_sections,
        generated_at=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        date_range_label=date_range_label,
        metric_key=metric_key,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    return html


def _format_summary(value: float | None, metric_key: str) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return METRICS[metric_key].formatter.format(float(value))


def _pick_first_nonempty(series: pd.Series, *, fallback: str) -> str:
    cleaned = series.dropna().astype(str)
    cleaned = cleaned[cleaned.str.strip() != ""]
    if cleaned.empty:
        return fallback
    try:
        return cleaned.mode().iat[0]
    except Exception:
        return cleaned.iat[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Kamata7 card-map HTML prototype")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output HTML file path",
    )
    parser.add_argument(
        "--metric",
        choices=sorted(METRICS),
        default="avg_diff",
        help="Metric used for card coloring and badge display",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Optional start date in YYYYMMDD format",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Optional end date in YYYYMMDD format",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_kamata7_cardmap_html(
        output_path=args.output,
        metric_key=args.metric,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
