"""Generate a standalone HTML prototype for the Kamata7 floor map.

This prototype avoids Plotly and renders each machine as an absolutely
positioned HTML card. The goal is to validate whether the floor shape and
card readability are good enough to replace the current heatmap view.
"""

from __future__ import annotations

import argparse
import sqlite3
import re
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
    """Load machine-level stats and the covered date range label."""

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
    raw = raw.sort_values(["machine_number", "date"])
    date_range_label = f"{raw['date'].min():%Y-%m-%d} 〜 {raw['date'].max():%Y-%m-%d}"

    stats_df = raw.groupby("machine_number").agg(
        machine_name=("machine_name", lambda s: _pick_last_nonempty(s, fallback="")),
        latest_date=("date", "max"),
        avg_diff=("diff_coins_normalized", "mean"),
        win_rate=("diff_coins_normalized", lambda s: (s > 0).mean() * 100),
        avg_games=("games_normalized", "mean"),
        sample_days=("date", "nunique"),
        total_games=("games_normalized", "sum"),
    )
    stats_df = stats_df.reset_index()
    stats_df["machine_number"] = stats_df["machine_number"].astype(int)
    return stats_df, date_range_label


def load_floor_coordinates(coords_path: Path) -> pd.DataFrame:
    """Load and normalize a floor coordinate CSV."""

    if not coords_path.exists():
        raise FileNotFoundError(f"Coordinate file not found: {coords_path}")

    coords_df = pd.read_csv(coords_path, dtype=str)
    for column in ("machine_number", "X", "Y", "display_x", "display_y"):
        if column in coords_df.columns:
            coords_df[column] = pd.to_numeric(coords_df[column], errors="coerce")

    if "machine_number" not in coords_df.columns:
        raise ValueError(f"Missing required coordinate columns in {coords_path}")

    coords_df = coords_df.dropna(subset=["machine_number"]).copy()
    coords_df["machine_number"] = coords_df["machine_number"].astype(int)
    return coords_df


def build_tone_thresholds(values: pd.Series) -> ToneThresholds:
    """Derive palette thresholds from the current floor's metric values."""

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
    """Map a metric value to a tone class."""

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


def classify_games(value: float | None, thresholds: tuple[float, float, float]) -> str:
    """Map games volume to a border class."""

    if value is None or pd.isna(value):
        return "games-missing"
    high, mid, low = thresholds
    if value >= high:
        return "games-high"
    if value >= mid:
        return "games-mid"
    if value >= low:
        return "games-low"
    return "games-missing"


def format_metric_value(value: float | None, metric_key: str) -> str:
    """Format a metric for the title tooltip."""

    if value is None or pd.isna(value):
        return "N/A"
    return METRICS[metric_key].formatter.format(float(value))


def _safe_text(value: object, fallback: str = "") -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _pick_last_nonempty(series: pd.Series, *, fallback: str) -> str:
    cleaned = series.dropna().astype(str)
    cleaned = cleaned[cleaned.str.strip() != ""]
    if cleaned.empty:
        return fallback
    return cleaned.iat[-1]


def abbreviate_machine_name(value: str | None, max_length: int = 12) -> str:
    """Derive a compact machine label suitable for tiny floor cards."""

    cleaned = _safe_text(value, fallback="未設定")
    if cleaned == "未設定":
        return cleaned
    cleaned = cleaned.replace("　", " ")

    for prefix in ("スマスロ", "パチスロ", "e ", "ｅ ", "L ", "S "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]

    replacements = (
        ("炎炎ノ消防隊", "炎炎"),
        ("炎炎の消防隊", "炎炎"),
        ("甲鉄城のカバネリ 海門(うなと)決戦", "カバネリ"),
        ("甲鉄城のカバネリ", "カバネリ"),
        ("からくりサーカス", "からくり"),
        ("モンキーターンV", "モンキー"),
        ("モンキーターン", "モンキー"),
        ("L ToLOVEるダークネス", "ToLOVEる"),
        ("To LOVEる", "ToLOVEる"),
        ("東京喰種", "喰種"),
        ("リゼロ", "Re:ゼロ"),
        ("Re:ゼロから始める異世界生活", "Re:ゼロ"),
        ("この素晴らしい世界に祝福を!", "このすば"),
        ("押忍!番長", "番長"),
        ("甲鉄城のカバネリ海門決戦", "カバネリ"),
    )
    for source, target in replacements:
        if source in cleaned:
            cleaned = cleaned.replace(source, target)

    cleaned = re.sub(r"\s+(?:ライト|スマスロ|L|S)$", "", cleaned)

    if len(cleaned) <= max_length:
        return cleaned
    return f"{cleaned[: max_length - 1]}…"


def summarize_games_thresholds(values: pd.Series) -> tuple[float, float, float]:
    """Return rough thresholds for border coloring based on avg games."""

    clean = values.dropna()
    if clean.empty:
        return (0.0, 0.0, 0.0)
    high = float(clean.quantile(0.75))
    mid = float(clean.quantile(0.50))
    low = float(clean.quantile(0.25))
    return high, mid, low


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
    games_thresholds: tuple[float, float, float],
    x_col: str,
    y_col: str,
) -> str:
    """Render one absolutely positioned machine card."""

    metric_value = row.get(metric_key)
    tone_class = classify_metric(metric_value, thresholds)
    games_class = classify_games(row.get("avg_games"), games_thresholds)
    machine_name = abbreviate_machine_name(row.get("machine_name"), max_length=11)
    machine_number = int(row["machine_number"])
    metric_label = format_metric_value(metric_value, metric_key)
    full_name = _safe_text(row.get("machine_name"))
    latest_date = row.get("latest_date")
    latest_date_label = (
        pd.Timestamp(latest_date).strftime("%Y-%m-%d") if pd.notna(latest_date) else "-"
    )
    title = (
        f"{machine_number} / {full_name} / latest={latest_date_label} / {METRICS[metric_key].label}: {metric_label}"
        if full_name
        else f"{machine_number} / latest={latest_date_label} / {METRICS[metric_key].label}: {metric_label}"
    )

    return f"""
      <article
        class="machine-card {tone_class} {games_class}"
        style="left: calc(var(--pad) + ({int(row[x_col])} - 1) * var(--slot-x)); top: calc(var(--pad) + ({int(row[y_col])} - 1) * var(--slot-y));"
        title="{escape(title)}"
        aria-label="{escape(title)}"
      >
        <div class="machine-number">{machine_number}</div>
        <div class="machine-name">{escape(machine_name)}</div>
      </article>
    """


def render_floor_section(
    frame: pd.DataFrame,
    *,
    floor_label: str,
    floor_title: str,
    metric_key: str,
    thresholds: ToneThresholds,
) -> str:
    """Render one floor panel."""

    x_col, y_col = get_display_columns(frame.columns)
    max_x = int(frame[x_col].max())
    max_y = int(frame[y_col].max())

    slot_x = 32
    slot_y = 26
    pad = 10
    map_width = pad * 2 + max_x * slot_x
    map_height = pad * 2 + max_y * slot_y

    games_thresholds = summarize_games_thresholds(frame["avg_games"])
    machine_cards = [
        render_machine_card(
            row,
            metric_key=metric_key,
            thresholds=thresholds,
            games_thresholds=games_thresholds,
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
    date_range_label = _safe_text(frame.attrs.get("date_range_label"), fallback="-")

    return f"""
      <section class="floor-shell" data-floor-panel="{escape(floor_label)}">
        <div class="floor-head">
          <div>
            <div class="floor-kicker">{escape(floor_label)}</div>
            <h2 class="floor-title">{escape(floor_title)}</h2>
            <p class="floor-subtitle">集計期間: {escape(date_range_label)} / セクション: {escape(section_label)}</p>
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

        <div class="floor-map-viewport" style="--base-map-width: {map_width}px; --base-map-height: {map_height}px;">
          <div class="floor-map" style="--slot-x: {slot_x}px; --slot-y: {slot_y}px; --pad: {pad}px; width: {map_width}px; height: {map_height}px;">
            <div class="floor-map-grid"></div>
            {''.join(machine_cards)}
          </div>
        </div>
      </section>
    """


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


def build_html_document(
    floor_sections: list[dict[str, str]],
    *,
    generated_at: str,
    date_range_label: str,
    metric_key: str,
) -> str:
    """Build the final standalone HTML document."""

    metric_label = METRICS[metric_key].label
    nav_buttons = []
    floor_panels = []
    for index, section in enumerate(floor_sections):
        active_class = " is-active" if index == 0 else ""
        floor_label = section["floor"]
        nav_buttons.append(
            f'<button class="floor-tab{active_class}" type="button" data-floor-tab="{escape(floor_label)}">{escape(floor_label)}</button>'
        )
        floor_panels.append(
            f'<div class="floor-panel{active_class}" data-floor-panel="{escape(floor_label)}"{" hidden" if index != 0 else ""}>{section["html"]}</div>'
        )

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
      --panel: rgba(255, 255, 255, 0.90);
      --panel-border: rgba(148, 163, 184, 0.32);
      --shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
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
      padding: 16px;
    }}

    .hero {{
      position: relative;
      overflow: hidden;
      padding: 20px;
      border-radius: 28px;
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
      width: 280px;
      height: 280px;
      right: -120px;
      top: -140px;
      background: radial-gradient(circle, rgba(251, 113, 133, 0.18), transparent 65%);
    }}

    .hero::after {{
      width: 240px;
      height: 240px;
      left: -120px;
      bottom: -150px;
      background: radial-gradient(circle, rgba(59, 130, 246, 0.16), transparent 65%);
    }}

    .hero-grid {{
      position: relative;
      z-index: 1;
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.8fr);
      align-items: end;
    }}

    .eyebrow {{
      margin: 0 0 8px;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.3em;
      text-transform: uppercase;
      color: #b45309;
    }}

    .hero h1 {{
      margin: 0;
      font-size: clamp(28px, 3vw, 42px);
      line-height: 1.05;
      letter-spacing: -0.04em;
    }}

    .hero-copy {{
      margin: 12px 0 0;
      font-size: 14px;
      line-height: 1.8;
      color: var(--muted);
      max-width: 64ch;
    }}

    .hero-meta {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}

    .meta-card {{
      padding: 12px 14px;
      border-radius: 16px;
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
      font-size: 16px;
      font-weight: 800;
      color: #0f172a;
    }}

    .badges {{
      margin-top: 14px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(148, 163, 184, 0.32);
      background: rgba(255, 255, 255, 0.86);
      color: #0f172a;
      font-size: 12px;
      font-weight: 700;
    }}

    .badge .swatch {{
      width: 10px;
      height: 10px;
      border-radius: 999px;
    }}

    .badge.high .swatch {{ background: #ef4444; }}
    .badge.mid .swatch {{ background: #fca5a5; }}
    .badge.neutral .swatch {{ background: #f8fafc; border: 1px solid #cbd5e1; }}
    .badge.cool .swatch {{ background: #7dd3fc; }}
    .badge.low .swatch {{ background: #2563eb; }}
    .badge.missing .swatch {{ background: #cbd5e1; }}

    .floor-switcher {{
      margin-top: 16px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}

    .floor-tab {{
      appearance: none;
      border: 1px solid rgba(148, 163, 184, 0.35);
      background: rgba(255, 255, 255, 0.82);
      color: #0f172a;
      border-radius: 999px;
      padding: 10px 16px;
      font: inherit;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
      transition: transform 120ms ease, background 120ms ease, border-color 120ms ease;
    }}

    .floor-tab:hover {{
      transform: translateY(-1px);
    }}

    .floor-tab.is-active {{
      background: linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%);
      border-color: #f59e0b;
      color: #7c2d12;
    }}

    .floor-panels {{
      margin-top: 14px;
    }}

    .floor-panel[hidden] {{
      display: none;
    }}

    .floor-shell {{
      overflow: hidden;
      border-radius: 26px;
      border: 1px solid var(--panel-border);
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}

    .floor-head {{
      display: grid;
      gap: 14px;
      grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
      align-items: start;
      padding: 18px 18px 14px;
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
      font-size: 22px;
      line-height: 1.15;
      letter-spacing: -0.03em;
    }}

    .floor-subtitle {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }}

    .floor-summary-grid {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}

    .summary-pill {{
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(248, 250, 252, 0.9);
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
      margin-top: 5px;
      font-size: 17px;
      font-weight: 800;
      color: #0f172a;
    }}

    .floor-map-viewport {{
      position: relative;
      width: 100%;
      overflow: hidden;
      padding: 10px 10px 14px;
    }}

    .floor-map {{
      position: relative;
      border-radius: 8px;
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
      transform-origin: top left;
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
      width: calc(var(--slot-x) - 2px);
      height: calc(var(--slot-y) - 2px);
      border-radius: 3px;
      padding: 1px 2px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 0;
      text-align: center;
      line-height: 1;
      border: 1px solid transparent;
      box-shadow: 0 6px 10px rgba(15, 23, 42, 0.06);
      overflow: hidden;
      transition: transform 120ms ease, box-shadow 120ms ease;
    }}

    .machine-card:hover {{
      transform: translateY(-1px);
      box-shadow: 0 10px 18px rgba(15, 23, 42, 0.1);
      z-index: 2;
    }}

    .machine-number {{
      font-size: 10px;
      font-weight: 900;
      letter-spacing: 0.02em;
    }}

    .machine-name {{
      font-size: 9px;
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 100%;
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

    .games-high {{
        border-color: #0f172a;
        box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.2), 0 6px 10px rgba(15, 23, 42, 0.06);
    }}

    .games-mid {{
        border-color: #2563eb;
    }}

    .games-low {{
        border-color: #60a5fa;
    }}

    .games-missing {{
        border-color: #cbd5e1;
    }}

    .footer-note {{
      margin-top: 16px;
      padding: 16px 18px;
      border-radius: 18px;
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
        padding: 10px;
      }}

      .hero,
      .floor-shell {{
        border-radius: 20px;
      }}

      .hero,
      .floor-head {{
        padding: 14px;
      }}

      .floor-map-viewport {{
        padding: 10px;
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
            Plotly のマス目ではなく、台ごとのカードをフロア上に並べる試作です。
            カードの角丸を抑え、最新日の機種名を使い、タブ切り替えで1フロアずつ全体表示できるようにしました。
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

    <div class="floor-switcher" role="tablist" aria-label="floor selector">
      {''.join(nav_buttons)}
    </div>

    <div class="floor-panels">
      {''.join(floor_panels)}
    </div>

    <section class="footer-note">
      このHTMLは試作です。`page_17_heatmap` へ移す前に、蒲田7の2F/3Fでカードの位置、機種名の可読性、色の粒度が妥当かを確認してください。
    </section>
  </main>

  <script>
    (() => {{
      const tabs = Array.from(document.querySelectorAll('[data-floor-tab]'));
      const panels = Array.from(document.querySelectorAll('[data-floor-panel]'));

      function fitActiveMap() {{
        const activePanel = panels.find((panel) => !panel.hasAttribute('hidden'));
        if (!activePanel) {{
          return;
        }}
        const viewport = activePanel.querySelector('.floor-map-viewport');
        const map = activePanel.querySelector('.floor-map');
        if (!viewport || !map) {{
          return;
        }}

        const baseWidth = Number(
          viewport.style.getPropertyValue('--base-map-width').replace('px', '')
        );
        const baseHeight = Number(
          viewport.style.getPropertyValue('--base-map-height').replace('px', '')
        );
        if (!baseWidth || !baseHeight) {{
          return;
        }}

        const availableWidth = Math.max(0, viewport.clientWidth - 4);
        const availableHeight = Math.max(
          240,
          window.innerHeight - activePanel.getBoundingClientRect().top - 40
        );
        const scale = Math.min(
          1,
          availableWidth / baseWidth,
          availableHeight / baseHeight
        );
        map.style.transform = `scale(${{scale}})`;
        viewport.style.height = `${{Math.ceil(baseHeight * scale)}}px`;
      }}

      function activateFloor(floor) {{
        tabs.forEach((tab) => {{
          const isActive = tab.dataset.floorTab === floor;
          tab.classList.toggle('is-active', isActive);
          tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
        }});

        panels.forEach((panel) => {{
          const isActive = panel.dataset.floorPanel === floor;
          panel.hidden = !isActive;
          panel.classList.toggle('is-active', isActive);
        }});

        requestAnimationFrame(fitActiveMap);
      }}

      tabs.forEach((tab) => {{
        tab.addEventListener('click', () => activateFloor(tab.dataset.floorTab));
      }});

      window.addEventListener('resize', fitActiveMap);
      activateFloor(tabs[0]?.dataset.floorTab ?? '');
    }})();
  </script>
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
    """Build the prototype HTML and optionally write it to disk."""

    if metric_key not in METRICS:
        raise ValueError(f"Unsupported metric_key: {metric_key}")

    stats_df, date_range_label = load_machine_stats(
        DB_PATH,
        start_date=start_date,
        end_date=end_date,
    )

    floor_sections: list[dict[str, str]] = []
    for spec in FLOOR_SPECS:
        frame = build_floor_frame(spec.coords_path, stats_df)
        frame.attrs["date_range_label"] = date_range_label
        thresholds = build_tone_thresholds(frame[metric_key])
        floor_sections.append(
            {
                "floor": spec.floor,
                "title": spec.title,
                "html": render_floor_section(
                    frame,
                    floor_label=spec.floor,
                    floor_title=spec.title,
                    metric_key=metric_key,
                    thresholds=thresholds,
                ),
            }
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
