from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Heatmap.coordinate_utils import find_floor_csvs, get_display_columns
from Heatmap.heatmap_common import HALL_CARD_CONFIG
from Heatmap.generate_kamata7_cardmap_html import (
    HTML2CANVAS_PATH,
    abbreviate_machine_name,
    build_floor_frame,
    load_machine_stats,
    sanitize_filename,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Heatmap" / "exports"
DEFAULT_HALLS = ["kamata7", "kamata1", "mitoya"]

HALLS: dict[str, dict[str, str]] = {
    "kamata7": {
        "hall_name": "\u30de\u30eb\u30cf\u30f3\u30e1\u30ac\u30b7\u30c6\u30a32000-\u84b2\u75307",
        "db_file": "\u30de\u30eb\u30cf\u30f3\u30e1\u30ac\u30b7\u30c6\u30a32000-\u84b2\u75307.db",
    },
    "kamata1": {
        "hall_name": "\u30de\u30eb\u30cf\u30f3\u30e1\u30ac\u30b7\u30c6\u30a32000-\u84b2\u75301",
        "db_file": "\u30de\u30eb\u30cf\u30f3\u30e1\u30ac\u30b7\u30c6\u30a32000-\u84b2\u75301.db",
    },
    "mitoya": {
        "hall_name": "\u307f\u3068\u3084\u5927\u68ee\u753a\u5e97",
        "db_file": "\u307f\u3068\u3084\u5927\u68ee\u753a\u5e97.db",
    },
}


@dataclass(frozen=True)
class AvgDiffStyle:
    class_name: str
    color: str
    label: str


@dataclass(frozen=True)
class WinRateStyle:
    class_name: str
    border_css: str
    label: str


def classify_avg_diff(avg_diff: float | None) -> AvgDiffStyle:
    if avg_diff is None or pd.isna(avg_diff):
        return AvgDiffStyle("tone-na", "#ECEFF1", "N/A")
    value = float(avg_diff)
    if value <= -1000:
        return AvgDiffStyle("tone-strong-negative", "#D32F2F", "\u5e73\u5747\u5dee\u679a <= -1000")
    if value <= -500:
        return AvgDiffStyle("tone-negative", "#EF9A9A", "\u5e73\u5747\u5dee\u679a <= -500")
    if value <= 0:
        return AvgDiffStyle("tone-neutral", "#BDBDBD", "\u5e73\u5747\u5dee\u679a <= 0")
    if value <= 500:
        return AvgDiffStyle("tone-positive-soft", "#A5D6A7", "\u5e73\u5747\u5dee\u679a <= +500")
    if value <= 1000:
        return AvgDiffStyle("tone-positive", "#4CAF50", "\u5e73\u5747\u5dee\u679a <= +1000")
    if value <= 2000:
        return AvgDiffStyle("tone-strong-positive", "#2E7D32", "\u5e73\u5747\u5dee\u679a <= +2000")
    return AvgDiffStyle("tone-gold", "#FFD700", "\u5e73\u5747\u5dee\u679a > +2000")


def classify_win_rate_border(win_rate: float | None) -> WinRateStyle:
    if win_rate is None or pd.isna(win_rate):
        return WinRateStyle("border-na", "1px solid #B0BEC5", "\u52dd\u7387 N/A")
    value = float(win_rate)
    if value >= 70:
        return WinRateStyle("border-gold", "3px solid #FFD700", "\u52dd\u7387 >= 70%")
    if value >= 50:
        return WinRateStyle("border-green", "2px solid #4CAF50", "\u52dd\u7387 >= 50%")
    if value >= 30:
        return WinRateStyle("border-muted", "1px solid #E0E0E0", "\u52dd\u7387 >= 30%")
    return WinRateStyle("border-danger", "2px dashed #D32F2F", "\u52dd\u7387 < 30%")


def _format_avg_diff(avg_diff: float | None) -> str:
    if avg_diff is None or pd.isna(avg_diff):
        return "N/A"
    return f"{float(avg_diff):+,.0f}\u679a"


def _format_win_rate(win_rate: float | None) -> str:
    if win_rate is None or pd.isna(win_rate):
        return "N/A"
    return f"{float(win_rate):.1f}%"


def _format_games(avg_games: float | None) -> str:
    if avg_games is None or pd.isna(avg_games):
        return "N/A"
    return f"{float(avg_games):.0f}G"


def _format_sample_days(sample_days: float | None) -> str:
    if sample_days is None or pd.isna(sample_days):
        return "n=0"
    return f"n={int(sample_days)}"


def render_candidate_card(
    row: pd.Series,
    *,
    x_col: str,
    y_col: str,
) -> str:
    avg_diff_style = classify_avg_diff(row.get("avg_diff"))
    win_rate_style = classify_win_rate_border(row.get("win_rate"))
    machine_number = int(row["machine_number"])
    machine_name = abbreviate_machine_name(row.get("machine_name"), max_length=4)
    full_name = str(row.get("machine_name") or "").strip() or "\u672a\u8a2d\u5b9a"
    avg_diff_label = _format_avg_diff(row.get("avg_diff"))
    win_rate_label = _format_win_rate(row.get("win_rate"))
    avg_games_label = _format_games(row.get("avg_games"))
    sample_days_label = _format_sample_days(row.get("sample_days"))
    title = (
        f"{machine_number} / {full_name} / \u5e73\u5747\u5dee\u679a: {avg_diff_label} / "
        f"\u52dd\u7387: {win_rate_label} / {sample_days_label} / \u5e73\u5747G\u6570: {avg_games_label}"
    )
    display_x = int(row[x_col])
    display_y = int(row[y_col])
    classes = [
        "candidate-card",
        avg_diff_style.class_name,
        win_rate_style.class_name,
    ]
    if avg_diff_style.class_name == "tone-na" or win_rate_style.class_name == "border-na":
        classes.append("candidate-card--missing")

    return f"""
      <article
        class="{' '.join(classes)}"
        style="left: calc(var(--pad) + ({display_x} - 1) * var(--slot-x)); top: calc(var(--pad) + ({display_y} - 1) * var(--slot-y)); background: {avg_diff_style.color}; border: {win_rate_style.border_css};"
        title="{html.escape(title)}"
        aria-label="{html.escape(title)}"
      >
        <div class="candidate-card__number">{machine_number}</div>
        <div class="candidate-card__name">{html.escape(machine_name)}</div>
        <div class="candidate-card__meta">
          <span class="candidate-card__metric">{html.escape(avg_diff_label)}</span>
          <span class="candidate-card__metric">{html.escape(win_rate_label)}</span>
        </div>
        <div class="candidate-card__footer">
          <span>{html.escape(sample_days_label)}</span>
          <span>{html.escape(avg_games_label)}</span>
        </div>
      </article>
    """


def render_floor_section(
    frame: pd.DataFrame,
    *,
    hall_key: str,
    hall_name: str,
    floor_label: str,
    dd: int,
) -> str:
    card_config = HALL_CARD_CONFIG.get(hall_name, {})
    x_col, y_col = get_display_columns(frame.columns)
    max_x = int(frame[x_col].max())
    max_y = int(frame[y_col].max())
    slot_x = int(card_config.get("slot_x", 40))
    slot_y = int(card_config.get("slot_y", 28))
    pad = int(card_config.get("pad", 10))
    fit_mode = str(card_config.get("fit_mode", "contain"))

    rendered_cards = []
    for _, row in frame.sort_values([y_col, x_col]).iterrows():
        rendered_cards.append(render_candidate_card(row, x_col=x_col, y_col=y_col))

    legend_html = """
      <div class="legend">
        <div class="legend-item"><span class="legend-swatch" style="background:#D32F2F;"></span>\u5e73\u5747\u5dee\u679a <= -1000</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#EF9A9A;"></span>\u5e73\u5747\u5dee\u679a <= -500</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#BDBDBD;"></span>\u5e73\u5747\u5dee\u679a <= 0</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#A5D6A7;"></span>\u5e73\u5747\u5dee\u679a <= +500</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#4CAF50;"></span>\u5e73\u5747\u5dee\u679a <= +1000</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#2E7D32;"></span>\u5e73\u5747\u5dee\u679a <= +2000</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#FFD700;"></span>\u5e73\u5747\u5dee\u679a > +2000</div>
      </div>
      <div class="legend">
        <div class="legend-item"><span class="legend-border legend-border--gold"></span>\u52dd\u7387 >= 70%</div>
        <div class="legend-item"><span class="legend-border legend-border--green"></span>\u52dd\u7387 >= 50%</div>
        <div class="legend-item"><span class="legend-border legend-border--muted"></span>\u52dd\u7387 >= 30%</div>
        <div class="legend-item"><span class="legend-border legend-border--danger"></span>\u52dd\u7387 < 30%</div>
      </div>
    """

    summary = frame[["avg_diff", "win_rate", "sample_days", "avg_games"]].copy()
    avg_diff = summary["avg_diff"].dropna().mean()
    win_rate = summary["win_rate"].dropna().mean()
    sample_days = summary["sample_days"].dropna().sum()
    avg_games = summary["avg_games"].dropna().mean()
    summary_html = (
        f'<div class="section-summary">'
        f'<span>\u5e73\u5747\u5dee\u679a: {html.escape(_format_avg_diff(avg_diff))}</span>'
        f'<span>\u5e73\u5747\u52dd\u7387: {html.escape(_format_win_rate(win_rate))}</span>'
        f'<span>\u30b5\u30f3\u30d7\u30eb\u65e5\u6570: n={int(sample_days) if pd.notna(sample_days) else 0}</span>'
        f'<span>\u5e73\u5747G\u6570: {html.escape(_format_games(avg_games))}</span>'
        f"</div>"
    )

    board_width = max_x * slot_x + pad * 2
    board_height = max_y * slot_y + pad * 2
    section_id = sanitize_filename(f"{hall_key}_{floor_label}")
    floor_name = html.escape(floor_label or "\u30d5\u30ed\u30a2")
    download_name = f"dd{dd}_{hall_key}"
    if floor_label:
        download_name = f"{download_name}_{sanitize_filename(floor_label)}"
    download_name = f"{download_name}.png"
    return f"""
      <section class="floor-section floor-section--{sanitize_filename(hall_key)}">
        <header class="floor-header">
          <div>
            <div class="eyebrow">DD{dd} \u5019\u88dc\u53f0\u30de\u30c3\u30d7</div>
            <h1>{html.escape(hall_name)} {floor_name}</h1>
          </div>
          <div class="header-actions">
            <button class="export-png-btn" type="button" data-target="{section_id}" data-download="{html.escape(download_name)}">Download PNG</button>
          </div>
        </header>
        {summary_html}
        {legend_html}
        <div class="floor-map-shell {'floor-map-shell--scroll' if fit_mode == 'scroll' else 'floor-map-shell--contain'}">
          <div
            id="{section_id}"
            class="floor-map"
            style="--slot-x: {slot_x}px; --slot-y: {slot_y}px; --pad: {pad}px; width: {board_width}px; height: {board_height}px;"
          >
            {''.join(rendered_cards)}
          </div>
        </div>
      </section>
    """


def build_candidate_html_document(
    *,
    hall_name: str,
    floor_label: str,
    dd: int,
    section_html: str,
    filter_label: str,
) -> str:
    html2canvas_source = HTML2CANVAS_PATH.read_text(encoding="utf-8")
    title = f"DD{dd} \u5019\u88dc\u53f0\u30de\u30c3\u30d7 \u2014 {hall_name} {floor_label}"
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7fb;
      --surface: #ffffff;
      --text: #17212b;
      --muted: #64748b;
      --line: #d7dee8;
      --shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
      color: var(--text);
      background: var(--bg);
    }}
    .page {{
      max-width: 1680px;
      margin: 0 auto;
      padding: 20px;
    }}
    .meta-bar {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    .meta-pill {{
      background: rgba(255, 255, 255, 0.8);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
    }}
    .floor-section {{
      background: var(--surface);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
      border-radius: 8px;
      padding: 18px;
    }}
    .floor-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 10px;
    }}
    .eyebrow {{
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0;
      text-transform: uppercase;
      margin-bottom: 4px;
    }}
    h1 {{
      margin: 0;
      font-size: 26px;
      line-height: 1.2;
    }}
    .header-actions {{
      flex: 0 0 auto;
    }}
    .export-png-btn {{
      appearance: none;
      border: 1px solid #0f172a;
      background: #0f172a;
      color: #fff;
      border-radius: 6px;
      padding: 10px 14px;
      font: inherit;
      cursor: pointer;
    }}
    .section-summary {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 10px;
    }}
    .legend {{
      display: flex;
      gap: 10px 16px;
      flex-wrap: wrap;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }}
    .legend-swatch {{
      width: 12px;
      height: 12px;
      border: 1px solid rgba(15, 23, 42, 0.15);
      border-radius: 2px;
      display: inline-block;
    }}
    .legend-border {{
      width: 16px;
      height: 12px;
      display: inline-block;
      border-radius: 2px;
      background: #fff;
    }}
    .legend-border--gold {{ border: 3px solid #FFD700; }}
    .legend-border--green {{ border: 2px solid #4CAF50; }}
    .legend-border--muted {{ border: 1px solid #E0E0E0; }}
    .legend-border--danger {{ border: 2px dashed #D32F2F; }}
    .floor-map-shell {{
      overflow: auto;
      padding-bottom: 4px;
    }}
    .floor-map-shell--contain {{
      display: flex;
      justify-content: center;
    }}
    .floor-map {{
      position: relative;
      min-width: 100%;
      background:
        linear-gradient(90deg, rgba(15, 23, 42, 0.03) 1px, transparent 1px) 0 0 / 40px 40px,
        linear-gradient(rgba(15, 23, 42, 0.03) 1px, transparent 1px) 0 0 / 40px 40px,
        #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .candidate-card {{
      position: absolute;
      width: calc(var(--slot-x) - 4px);
      height: calc(var(--slot-y) - 4px);
      border-radius: 4px;
      padding: 3px 4px;
      overflow: hidden;
      color: #102030;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 2px;
    }}
    .candidate-card--missing {{
      opacity: 0.6;
      filter: grayscale(0.2);
    }}
    .candidate-card__number {{
      font-size: 12px;
      font-weight: 700;
      line-height: 1;
    }}
    .candidate-card__name {{
      font-size: 9px;
      line-height: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .candidate-card__meta,
    .candidate-card__footer {{
      display: flex;
      justify-content: space-between;
      gap: 4px;
      font-size: 9px;
      line-height: 1;
    }}
    .candidate-card__metric {{
      white-space: nowrap;
    }}
    .candidate-card__footer {{
      color: rgba(16, 32, 48, 0.8);
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="meta-bar">
      <div class="meta-pill">\u5bfe\u8c61\u30db\u30fc\u30eb: {html.escape(hall_name)}</div>
      <div class="meta-pill">\u5bfe\u8c61\u30d5\u30ed\u30a2: {html.escape(floor_label)}</div>
      <div class="meta-pill">\u30d5\u30a3\u30eb\u30bf: {html.escape(filter_label)}</div>
      <div class="meta-pill">DD{dd}</div>
    </div>
    {section_html}
  </div>
  <script>{html2canvas_source}</script>
  <script>
    document.addEventListener("click", async (event) => {{
      const button = event.target.closest(".export-png-btn");
      if (!button) return;
      const targetId = button.getAttribute("data-target");
      const target = document.getElementById(targetId);
      if (!target || typeof html2canvas !== "function") return;

      button.disabled = true;
      const originalText = button.textContent;
      button.textContent = "Exporting...";
      try {{
        const canvas = await html2canvas(target, {{
          backgroundColor: "#ffffff",
          scale: 2,
          useCORS: true,
        }});
        const link = document.createElement("a");
        link.download = button.getAttribute("data-download") || "candidate-map.png";
        link.href = canvas.toDataURL("image/png");
        link.click();
      }} finally {{
        button.disabled = false;
        button.textContent = originalText;
      }}
    }});
  </script>
</body>
</html>
"""


def _resolve_hall_db_path(project_root: Path, hall_key: str) -> Path:
    return project_root / "db" / HALLS[hall_key]["db_file"]


def _resolve_floor_specs(project_root: Path, hall_name: str) -> list[dict[str, str]]:
    return find_floor_csvs(hall_name, str(project_root))


def export_dd_candidates(
    *,
    dd: int,
    halls: Iterable[str],
    output_dir: Path,
    project_root: Path = PROJECT_ROOT,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for hall_key in halls:
        if hall_key not in HALLS:
            raise KeyError(f"Unknown hall key: {hall_key}")

        hall = HALLS[hall_key]
        hall_name = hall["hall_name"]
        db_path = _resolve_hall_db_path(project_root, hall_key)
        stats_df, date_range_label, filter_label = load_machine_stats(
            db_path,
            day_of_months=[dd],
        )
        floor_specs = _resolve_floor_specs(project_root, hall_name)
        if not floor_specs:
            raise ValueError(f"No coordinate CSVs found for {hall_name}")

        include_floor_suffix = len(floor_specs) > 1
        for floor_spec in floor_specs:
            coords_path = Path(floor_spec["path"])
            floor_label = floor_spec["floor"]
            card_config = HALL_CARD_CONFIG.get(hall_name, {})
            frame = build_floor_frame(
                coords_path,
                stats_df,
                exclude_machine_numbers=card_config.get("exclude_machine_numbers", ()),
            )
            section_html = render_floor_section(
                frame,
                hall_key=hall_key,
                hall_name=hall_name,
                floor_label=floor_label,
                dd=dd,
            )
            document = build_candidate_html_document(
                hall_name=hall_name,
                floor_label=floor_label,
                dd=dd,
                section_html=section_html,
                filter_label=f"{filter_label} / {date_range_label}",
            )
            file_parts = [f"dd{dd}", hall_key]
            if include_floor_suffix:
                file_parts.append(floor_label)
            output_path = output_dir / f"{sanitize_filename('_'.join(file_parts))}.html"
            output_path.write_text(document, encoding="utf-8")
            written.append(output_path)
            print(f"[OK] wrote {output_path}")

    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export DD candidate heatmap HTML files.")
    parser.add_argument("--dd", type=int, required=True, help="Target day of month (1-31).")
    parser.add_argument(
        "--halls",
        nargs="+",
        choices=sorted(HALLS.keys()),
        default=DEFAULT_HALLS,
        help="Target halls to export.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for HTML files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.dd <= 31:
        raise ValueError("--dd must be between 1 and 31")

    export_dd_candidates(
        dd=args.dd,
        halls=args.halls,
        output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
