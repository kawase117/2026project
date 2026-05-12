"""Shared helpers for structured experiment result bundles and HTML reports."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    """Write JSON with UTF-8 and stable indentation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_text(path: Path, text: str) -> None:
    """Write text with UTF-8, creating parents when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_run_payload(
    log_data: dict[str, Any],
    *,
    primary_metric: str = "auc",
    decision: str = "unreviewed",
    baseline_run_id: str | None = None,
    changed_factors: list[str] | None = None,
    fixed_factors: dict[str, Any] | None = None,
    data_context: dict[str, Any] | None = None,
    retest_if: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Convert the legacy flat experiment log into the structured run payload."""
    metrics = log_data.get("metrics", {})
    primary_value = metrics.get(primary_metric)

    result_payload = {
        "primary_metric": primary_metric,
        "primary_value": primary_value,
        "metrics": metrics,
    }

    return {
        **log_data,
        "status": "completed",
        "decision": decision,
        "question": log_data.get("hypothesis", ""),
        "baseline_run_id": baseline_run_id,
        "changed_factors": changed_factors or [],
        "fixed_factors": fixed_factors or {},
        "data": data_context or {},
        "result": result_payload,
        "conclusion": log_data.get("interpretation", ""),
        "retest_if": retest_if or [],
        "tags": tags or [],
    }


def render_run_summary_html(run_data: dict[str, Any]) -> str:
    """
    Render a fixed-structure human-facing HTML summary for one experiment run.

    Section order is always:
    1. Question (hero)
    2. What Changed
    3. What was Fixed
    4. Data / Split
    5. Metrics
    6. Interpretation
    7. Conclusion
    8. Do Not Retry Unless
    9. Next Candidate
    10. Tags

    This structure ensures readers quickly find decision-critical information.
    """
    metrics = run_data.get("result", {}).get("metrics", {})
    primary_metric = run_data.get("result", {}).get("primary_metric", "auc")
    primary_value = run_data.get("result", {}).get("primary_value")
    baseline_value = run_data.get("result", {}).get("baseline_value")
    delta = run_data.get("result", {}).get("delta")

    metric_rows = "".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(_format_value(value))}</td></tr>"
        for key, value in metrics.items()
        if not isinstance(value, dict)
    )

    changed_factors = _render_list(run_data.get("changed_factors", []))
    retest_if = _render_list(run_data.get("retest_if", []))
    tags = _render_list(run_data.get("tags", []))
    fixed_rows = _render_mapping_rows(run_data.get("fixed_factors", {}))
    data_rows = _render_mapping_rows(run_data.get("data", {}))

    title = escape(run_data.get("experiment_id", "experiment"))
    question = escape(run_data.get("question", ""))
    conclusion = escape(run_data.get("conclusion", ""))
    next_step = escape(run_data.get("next_step", ""))
    interpretation = escape(run_data.get("interpretation", ""))
    decision = escape(run_data.get("decision", "unreviewed"))
    timestamp = escape(run_data.get("timestamp", ""))
    phase = escape(str(run_data.get("phase", "")))
    task = escape(str(run_data.get("task", "")))
    groupby_strategy = escape(str(run_data.get("groupby_strategy", "")))
    ml_model = escape(str(run_data.get("ml_model", "")))
    primary_value_text = escape(_format_value(primary_value))
    baseline_value_text = escape(_format_value(baseline_value)) if baseline_value is not None else "-"
    delta_text = escape(_format_value(delta)) if delta is not None else "-"

    body = f"""
    <section class="hero">
      <p class="eyebrow">Experiment Summary</p>
      <h1>{title}</h1>
      <p class="lede">{question}</p>
      <div class="meta-grid">
        <div><span>Phase</span><strong>{phase}</strong></div>
        <div><span>Task</span><strong>{task}</strong></div>
        <div><span>Grouping</span><strong>{groupby_strategy}</strong></div>
        <div><span>Model</span><strong>{ml_model}</strong></div>
        <div><span>Decision</span><strong>{decision}</strong></div>
        <div><span>{escape(primary_metric.upper())}</span><strong>{primary_value_text}</strong></div>
      </div>
      <p class="timestamp">{timestamp}</p>
    </section>

    <section class="two-col">
      <div>
        <h2>2. What Changed</h2>
        {changed_factors}
      </div>
      <div>
        <h2>3. What Was Fixed</h2>
        <table>{fixed_rows}</table>
      </div>
    </section>

    <section class="two-col">
      <div>
        <h2>4. Data &amp; Split</h2>
        <table>{data_rows}</table>
      </div>
      <div>
        <h2>5. Metrics</h2>
        <table>
          <tr><th>Metric</th><td>Value</td></tr>
          <tr><th>Baseline</th><td>{baseline_value_text}</td></tr>
          <tr><th>Candidate</th><td>{primary_value_text}</td></tr>
          <tr><th>Delta</th><td>{delta_text}</td></tr>
          {metric_rows}
        </table>
      </div>
    </section>

    <section>
      <h2>6. Interpretation</h2>
      <p>{interpretation}</p>
    </section>

    <section>
      <h2>7. Conclusion</h2>
      <p>{conclusion}</p>
    </section>

    <section>
      <h2>8. Do Not Retry Unless</h2>
      {retest_if}
    </section>

    <section>
      <h2>9. Next Candidate</h2>
      <p>{next_step}</p>
    </section>

    <section>
      <h2>10. Tags</h2>
      {tags}
    </section>
    """
    return render_html_page(title=run_data.get("experiment_id", "Experiment Summary"), body=body)


def render_html_page(*, title: str, body: str) -> str:
    """Render a styled standalone HTML page."""
    safe_title = escape(title)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --panel: #fffaf2;
      --ink: #1f2933;
      --muted: #5f6c7b;
      --line: #d8cfc1;
      --accent: #b85c38;
      --accent-soft: #f4d8c6;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Hiragino Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #f8dfc8 0, transparent 28%),
        linear-gradient(180deg, #fbf6ef 0%, #f1e8db 100%);
    }}
    main {{
      max-width: 1040px;
      margin: 0 auto;
      padding: 40px 20px 72px;
    }}
    section {{
      background: rgba(255, 250, 242, 0.96);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 24px;
      margin-bottom: 18px;
      box-shadow: 0 12px 30px rgba(87, 63, 33, 0.08);
    }}
    .hero {{
      border-top: 6px solid var(--accent);
    }}
    .eyebrow {{
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    h1, h2 {{
      margin: 0 0 12px;
      line-height: 1.2;
    }}
    h1 {{
      font-size: 32px;
    }}
    h2 {{
      font-size: 20px;
    }}
    p {{
      margin: 0 0 12px;
      line-height: 1.7;
    }}
    .lede {{
      font-size: 18px;
      color: var(--muted);
    }}
    .timestamp {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
    }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
      margin-top: 20px;
    }}
    .meta-grid div {{
      background: var(--accent-soft);
      border-radius: 14px;
      padding: 12px 14px;
    }}
    .meta-grid span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }}
    .meta-grid strong {{
      font-size: 18px;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 12px;
      overflow: hidden;
    }}
    th, td {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid #eee3d2;
      vertical-align: top;
    }}
    th {{
      width: 38%;
      color: var(--muted);
      font-weight: 600;
    }}
    ul {{
      margin: 0;
      padding-left: 18px;
    }}
    code {{
      font-family: Consolas, monospace;
      background: #f5ede4;
      padding: 1px 6px;
      border-radius: 999px;
    }}
    @media (max-width: 720px) {{
      main {{
        padding: 18px 12px 40px;
      }}
      section {{
        padding: 18px;
        border-radius: 16px;
      }}
      h1 {{
        font-size: 26px;
      }}
    }}
  </style>
</head>
<body>
  <main>
    {body}
  </main>
</body>
</html>
"""


def update_index_jsonl(index_path: Path, record: dict[str, Any], *, key: str = "experiment_id") -> None:
    """Upsert a JSONL record using the provided key."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.append(json.loads(line))

    seen = False
    for idx, item in enumerate(existing):
        if item.get(key) == record.get(key):
            existing[idx] = record
            seen = True
            break

    if not seen:
        existing.append(record)

    lines = "\n".join(json.dumps(item, ensure_ascii=False) for item in existing)
    write_text(index_path, lines + ("\n" if lines else ""))


def build_index_record(run_payload: dict[str, Any], run_json_path: Path, results_dir: Path) -> dict[str, Any]:
    """Create a compact index entry for fast search/filter."""
    result = run_payload.get("result", {})
    rel_path = run_json_path.relative_to(results_dir).as_posix()
    return {
        "experiment_id": run_payload.get("experiment_id"),
        "timestamp": run_payload.get("timestamp"),
        "phase": run_payload.get("phase"),
        "task": run_payload.get("task"),
        "groupby_strategy": run_payload.get("groupby_strategy"),
        "ml_model": run_payload.get("ml_model"),
        "decision": run_payload.get("decision"),
        "primary_metric": result.get("primary_metric"),
        "primary_value": result.get("primary_value"),
        "path": rel_path,
        "tags": run_payload.get("tags", []),
    }


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    if value is None:
        return "-"
    return str(value)


def _render_list(values: list[Any]) -> str:
    if not values:
        return "<p>None</p>"
    items = "".join(f"<li>{escape(_format_value(value))}</li>" for value in values)
    return f"<ul>{items}</ul>"


def _render_mapping_rows(mapping: dict[str, Any]) -> str:
    if not mapping:
        return "<tr><th>Value</th><td>-</td></tr>"
    return "".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(_format_value(value))}</td></tr>"
        for key, value in mapping.items()
    )
