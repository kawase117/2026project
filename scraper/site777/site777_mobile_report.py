from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_html(result: dict[str, Any]) -> str:
    payload = {
        "generatedAt": result.get("generated_at"),
        "sourceCompletedAt": result.get("source_completed_at"),
        "graphMinGames": result.get("graph_min_games"),
        "machineCount": result.get("machine_count"),
        "eligibleCount": result.get("graph_eligible_count"),
        "reusedCount": result.get("graph_reused_count", 0),
        "sourceTimeStatus": result.get("source_time_status", {}),
        "reference": result.get("reference", {"enabled": False}),
        "models": result.get("models", []),
        "tails": result.get("tails", []),
        "corners": result.get("corners", []),
        "threeMachineRuns": result.get("three_machine_runs", []),
        "positiveBlocks": result.get("positive_blocks", []),
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    serialized = serialized.replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="color-scheme" content="dark">
  <link rel="icon" href="data:,">
  <title>楽園蒲田 スロット速報</title>
  <style>
    :root {{
      --bg: #0b0e14; --panel: #151a23; --panel2: #1c2330; --text: #f5f7fb;
      --muted: #9aa6b6; --line: #2a3445; --accent: #60a5fa; --good: #45d483;
      --bad: #fb7185; --warn: #fbbf24; --radius: 16px;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: system-ui,-apple-system,"Segoe UI",sans-serif; }}
    .app {{ width: min(100%, 760px); margin: 0 auto; padding: 18px 14px 80px; }}
    header {{ padding: 8px 2px 14px; }}
    h1 {{ margin: 0 0 6px; font-size: clamp(22px,6vw,30px); letter-spacing: .01em; }}
    .sub {{ color: var(--muted); font-size: 13px; line-height: 1.55; }}
    .summary {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin: 14px 0; }}
    .summary div {{ background: var(--panel); border: 1px solid var(--line); border-radius: 13px; padding: 10px 8px; text-align: center; }}
    .summary strong {{ display: block; font-size: 19px; }}
    .summary span {{ color: var(--muted); font-size: 11px; }}
    .sticky {{ position: sticky; top: 0; z-index: 10; margin: 0 -14px 14px; padding: 8px 14px 12px; background: rgba(11,14,20,.94); backdrop-filter: blur(10px); }}
    .tabs {{ display: grid; grid-template-columns: repeat(5,1fr); gap: 6px; margin-bottom: 9px; }}
    button, select, input {{ font: inherit; }}
    .tab {{ border: 1px solid var(--line); border-radius: 12px; padding: 10px 4px; background: var(--panel); color: var(--muted); font-weight: 700; }}
    .tab.active {{ color: #07111f; background: var(--accent); border-color: var(--accent); }}
    .filters {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; }}
    select, input {{ width: 100%; min-height: 44px; color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 0 12px; }}
    #toggleAll {{ min-height: 44px; color: var(--text); background: var(--panel2); border: 1px solid var(--line); border-radius: 12px; padding: 0 14px; white-space: nowrap; }}
    #search {{ margin-top: 8px; }}
    .section-head {{ display: flex; align-items: end; justify-content: space-between; gap: 12px; margin: 6px 2px 10px; }}
    .section-head h2 {{ margin: 0; font-size: 18px; }}
    #count {{ color: var(--muted); font-size: 12px; }}
    .cards {{ display: grid; gap: 10px; }}
    .card {{ background: linear-gradient(145deg,var(--panel),#111720); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }}
    .card summary {{ list-style: none; padding: 14px; cursor: pointer; }}
    .card summary::-webkit-details-marker {{ display: none; }}
    .topline {{ display: grid; grid-template-columns: 36px 1fr auto; gap: 10px; align-items: center; }}
    .rank {{ width: 36px; height: 36px; display: grid; place-items: center; border-radius: 11px; background: var(--panel2); color: var(--accent); font-weight: 900; }}
    .name {{ min-width: 0; font-size: 15px; font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; }}
    .primary {{ text-align: right; font-size: 18px; font-weight: 900; white-space: nowrap; }}
    .primary.good, .good {{ color: var(--good); }} .primary.bad, .bad {{ color: var(--bad); }}
    .name small {{ color: var(--muted); font-size: 11px; font-weight: 600; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 11px; }}
    .chip {{ padding: 5px 8px; border-radius: 999px; background: var(--panel2); color: #c9d2df; font-size: 11px; }}
    .detail {{ border-top: 1px solid var(--line); padding: 12px 14px 14px; }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(2,1fr); gap: 8px; }}
    .metric {{ background: rgba(255,255,255,.025); border-radius: 10px; padding: 9px; }}
    .metric span {{ display: block; color: var(--muted); font-size: 11px; }}
    .metric strong {{ font-size: 14px; }}
    .time {{ margin-top: 10px; color: var(--muted); font-size: 10px; line-height: 1.45; overflow-wrap: anywhere; }}
    .machine-row {{ display: grid; grid-template-columns: 44px 1fr auto; gap: 8px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line); font-size: 12px; }}
    .machine-row:last-child {{ border-bottom: 0; }}
    .machine-row b {{ color: var(--accent); }} .machine-row em {{ color: var(--muted); font-style: normal; overflow-wrap: anywhere; }}
    .empty {{ color: var(--muted); text-align: center; padding: 34px 10px; }}
    .note {{ margin-top: 16px; padding: 12px; border: 1px solid #5b4a20; background: #211b0c; color: #f6d98b; border-radius: 12px; font-size: 12px; line-height: 1.55; }}
    @media (min-width: 620px) {{ .cards {{ grid-template-columns: repeat(2,1fr); }} .card summary {{ min-height: 154px; }} }}
  </style>
</head>
<body>
<main class="app">
  <header>
    <h1>楽園蒲田 スロット速報</h1>
    <div class="sub" id="timestamp"></div>
    <div class="summary">
      <div><strong id="machineCount">--</strong><span>全台</span></div>
      <div><strong id="eligibleCount">--</strong><span>差枚対象</span></div>
      <div><strong id="threshold">--</strong><span>しきい値</span></div>
    </div>
  </header>
  <div class="sticky">
    <div class="tabs">
      <button class="tab active" data-scope="main">機種</button>
      <button class="tab" data-scope="single">一台機種</button>
      <button class="tab" data-scope="tail">末尾</button>
      <button class="tab" data-scope="corner">角</button>
      <button class="tab" data-scope="three">3台並び</button>
    </div>
    <div class="filters">
      <select id="metric" aria-label="ランキング指標"></select>
      <button id="toggleAll">上位10件</button>
    </div>
    <input id="search" type="search" placeholder="機種名を検索" aria-label="機種名を検索">
  </div>
  <div class="section-head"><h2 id="heading">機種ランキング</h2><span id="count"></span></div>
  <section id="cards" class="cards"></section>
  <div class="note" id="qualityNote"></div>
</main>
<script id="report-data" type="application/json">{serialized}</script>
<script>
  const data = JSON.parse(document.getElementById('report-data').textContent);
  const metrics = {{
    average_diff: ['平均差枚','枚',true], win_rate: ['勝率','%',true],
    average_games: ['平均G','G',true], bb_probability: ['BB確率','',false],
    rb_probability: ['RB確率','',false], combined_probability: ['合成確率','',false],
    average_highest_payout: ['平均最高出玉','枚',true],
    high_rotation_high_diff_score: ['3台総合','点',true],
    block_score: ['連続ブロック','点',true]
  }};
  const metricSets = {{
    main: ['average_diff','win_rate','average_games','rb_probability','bb_probability','combined_probability','average_highest_payout'],
    single: ['average_diff','win_rate','average_games','rb_probability','bb_probability','combined_probability','average_highest_payout'],
    tail: ['average_diff','win_rate','average_highest_payout'],
    corner: ['average_diff','win_rate','average_games','average_highest_payout'],
    three: ['high_rotation_high_diff_score','block_score','average_diff','average_games','average_highest_payout']
  }};
  const noDiffDefaults = {{
    main: 'average_games', single: 'average_games', tail: 'average_highest_payout',
    corner: 'average_games', three: 'average_games'
  }};
  const defaultMetric = nextScope => Number(data.eligibleCount || 0) > 0
    ? metricSets[nextScope][0]
    : noDiffDefaults[nextScope];
  let scope = 'main', metric = defaultMetric('main'), showAll = false;
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
  const num = (v,d=0) => v == null ? '--' : Number(v).toLocaleString('ja-JP',{{maximumFractionDigits:d}});
  const dateTime = value => {{
    if (!value) return '不明';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ja-JP',{{timeZone:'Asia/Tokyo',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}});
  }};
  const fmt = (key,v) => {{
    if (v == null) return '--';
    if (key === 'win_rate') return `${{(v*100).toFixed(1)}}%`;
    if (key.includes('probability')) return `1/${{num(v,1)}}`;
    return `${{num(v,1)}}${{metrics[key][1] ? ' '+metrics[key][1] : ''}}`;
  }};
  const diffClass = (key,v) => key === 'average_diff' && v != null ? (v > 0 ? 'good' : v < 0 ? 'bad' : '') : '';
  function options() {{
    el('metric').innerHTML = metricSets[scope].map(k => `<option value="${{k}}">${{metrics[k][0]}}</option>`).join('');
    if (!metricSets[scope].includes(metric)) metric = metricSets[scope][0];
    el('metric').value = metric;
  }}
  function rows() {{
    const source = scope === 'tail' ? data.tails : scope === 'corner' ? data.corners : scope === 'three' ? (metric === 'block_score' ? data.positiveBlocks : data.threeMachineRuns) : data.models.filter(x => scope === 'main' ? x.machine_count > 1 : x.machine_count === 1);
    const query = el('search').value.trim().toLowerCase();
    return source.filter(x => x[metric] != null && (scope !== 'three' || metric !== 'high_rotation_high_diff_score' || x.total_diff > 0) && (!query || String(x.model_name ?? x.tail ?? `${{x.start_machine}}-${{x.end_machine}} ${{x.model_label}}`).toLowerCase().includes(query)))
      .sort((a,b) => metrics[metric][2] ? b[metric]-a[metric] : a[metric]-b[metric]);
  }}
  function modelCard(row, rank) {{
    const name = row.model_name;
    const category = row.machine_category ? `<span class="chip">区分 ${{esc(row.machine_category.toUpperCase())}}</span>` : `<span class="chip">マスター未対応</span>`;
    return `<details class="card"><summary><div class="topline"><span class="rank">${{rank}}</span><span class="name">${{esc(name)}}</span><span class="primary ${{diffClass(metric,row[metric])}}">${{fmt(metric,row[metric])}}</span></div>
      <div class="chips"><span class="chip">平均差枚 ${{fmt('average_diff',row.average_diff)}}</span><span class="chip">平均G ${{fmt('average_games',row.average_games)}}</span><span class="chip">勝率 ${{fmt('win_rate',row.win_rate)}}</span><span class="chip">差枚対象 ${{row.graph_eligible_count}}台</span><span class="chip">再利用 ${{row.graph_reused_count || 0}}台</span>${{category}}</div></summary>
      <div class="detail"><div class="detail-grid"><div class="metric"><span>設置台数</span><strong>${{row.machine_count}}台</strong></div><div class="metric"><span>差枚有効台</span><strong>${{row.diff_valid_count}}台</strong></div><div class="metric"><span>BB確率</span><strong>${{fmt('bb_probability',row.bb_probability)}}</strong></div><div class="metric"><span>RB確率</span><strong>${{fmt('rb_probability',row.rb_probability)}}</strong></div><div class="metric"><span>合成確率</span><strong>${{fmt('combined_probability',row.combined_probability)}}</strong></div><div class="metric"><span>平均最高出玉</span><strong>${{fmt('average_highest_payout',row.average_highest_payout)}}</strong></div><div class="metric"><span>OCR 中/低</span><strong>${{row.medium_confidence_count || 0}} / ${{row.low_confidence_count || 0}}台</strong></div><div class="metric"><span>最高出玉再利用</span><strong>${{row.highest_reused ? 'あり' : 'なし'}}</strong></div></div><div class="time">最大グラフ遅れ ${{row.max_graph_age_minutes ?? '--'}}分<br>${{esc(row.update_time)}}</div></div></details>`;
  }}
  function tailCard(row, rank) {{
    return `<details class="card"><summary><div class="topline"><span class="rank">${{rank}}</span><span class="name">末尾 ${{esc(row.tail)}}</span><span class="primary ${{diffClass(metric,row[metric])}}">${{fmt(metric,row[metric])}}</span></div>
      <div class="chips"><span class="chip">平均差枚 ${{fmt('average_diff',row.average_diff)}}</span><span class="chip">勝率 ${{fmt('win_rate',row.win_rate)}}</span><span class="chip">対象 ${{row.graph_eligible_count}}台</span><span class="chip">全 ${{row.machine_count}}台</span></div></summary>
      <div class="detail"><div class="detail-grid"><div class="metric"><span>平均G</span><strong>${{fmt('average_games',row.average_games)}}</strong></div><div class="metric"><span>平均最高出玉</span><strong>${{fmt('average_highest_payout',row.average_highest_payout)}}</strong></div><div class="metric"><span>勝ち台</span><strong>${{row.win_count}}台</strong></div><div class="metric"><span>差枚有効台</span><strong>${{row.diff_valid_count}}台</strong></div></div><div class="time">グラフ ${{esc(row.graph_update_time || '不明')}}</div></div></details>`;
  }}
  function cornerCard(row, rank) {{
    return `<details class="card"><summary><div class="topline"><span class="rank">${{rank}}</span><span class="name">${{esc(row.corner_label)}}</span><span class="primary ${{diffClass(metric,row[metric])}}">${{fmt(metric,row[metric])}}</span></div>
      <div class="chips"><span class="chip">平均差枚 ${{fmt('average_diff',row.average_diff)}}</span><span class="chip">平均G ${{fmt('average_games',row.average_games)}}</span><span class="chip">勝率 ${{fmt('win_rate',row.win_rate)}}</span><span class="chip">差枚対象 ${{row.graph_eligible_count}}台</span></div></summary>
      <div class="detail"><div class="detail-grid"><div class="metric"><span>全台数</span><strong>${{row.machine_count}}台</strong></div><div class="metric"><span>有効差枚台</span><strong>${{row.diff_valid_count}}台</strong></div><div class="metric"><span>勝ち台</span><strong>${{row.win_count}}台</strong></div><div class="metric"><span>平均最高出玉</span><strong>${{fmt('average_highest_payout',row.average_highest_payout)}}</strong></div><div class="metric"><span>BB確率</span><strong>${{fmt('bb_probability',row.bb_probability)}}</strong></div><div class="metric"><span>RB確率</span><strong>${{fmt('rb_probability',row.rb_probability)}}</strong></div></div></div></details>`;
  }}
  function threeCard(row, rank) {{
    const details = row.machines.map(machine => `<div class="machine-row"><b>${{esc(machine.machine_number)}}</b><em>${{esc(machine.model_name)}}</em><span class="${{machine.latest_diff > 0 ? 'good' : machine.latest_diff < 0 ? 'bad' : ''}}">${{num(machine.games)}}G / 最高 ${{num(machine.highest_payout)}}枚 / 差枚 ${{machine.latest_diff > 0 ? '+' : ''}}${{num(machine.latest_diff)}}枚</span></div>`).join('');
    const score = row.block_score ?? row.high_rotation_high_diff_score;
    const quality = `再利用 ${{row.graph_reused_count || 0}}台 / OCR低 ${{row.low_confidence_count || 0}}台・中 ${{row.medium_confidence_count || 0}}台 / 最大遅れ ${{row.max_graph_age_minutes ?? '--'}}分`;
    const section = row.section ? `<span class="chip">島 ${{esc(row.section)}}</span>` : '';
    return `<details class="card"><summary><div class="topline"><span class="rank">${{rank}}</span><span class="name">${{esc(row.start_machine)}}～${{esc(row.end_machine)}}${{row.machine_count ? `（${{row.machine_count}}台）` : ''}}<br><small>${{esc(row.model_label)}}</small></span><span class="primary ${{diffClass(metric,row[metric])}}">${{fmt(metric,row[metric])}}</span></div>
      <div class="chips"><span class="chip">平均差枚 ${{fmt('average_diff',row.average_diff)}}</span><span class="chip">平均G ${{fmt('average_games',row.average_games)}}</span><span class="chip">平均最高出玉 ${{fmt('average_highest_payout',row.average_highest_payout)}}</span><span class="chip">合計差枚 ${{row.total_diff > 0 ? '+' : ''}}${{num(row.total_diff)}}枚</span><span class="chip">勝率 ${{fmt('win_rate',row.win_rate)}}</span><span class="chip">再利用 ${{row.graph_reused_count || 0}}台</span>${{section}}</div></summary>
      <div class="detail">${{details}}<div class="detail-grid" style="margin-top:10px"><div class="metric"><span>合計G</span><strong>${{num(row.total_games)}}G</strong></div><div class="metric"><span>平均最高出玉</span><strong>${{fmt('average_highest_payout',row.average_highest_payout)}}</strong></div><div class="metric"><span>総合点</span><strong>${{num(score,1)}}点</strong></div></div><div class="time">品質 ${{esc(quality)}}<br>グラフ ${{esc(row.graph_update_time || '不明')}}</div></div></details>`;
  }}
  function render() {{
    const all = rows(), shown = showAll ? all : all.slice(0,10);
    el('heading').textContent = scope === 'main' ? '機種ランキング' : scope === 'single' ? '一台機種ランキング' : scope === 'tail' ? '末尾ランキング' : scope === 'corner' ? '角番号ランキング' : metric === 'block_score' ? '連続好調ブロック' : '3台並びランキング';
    el('count').textContent = `${{shown.length}} / ${{all.length}}件`;
    el('search').style.display = ['tail','corner'].includes(scope) ? 'none' : 'block';
    el('search').placeholder = scope === 'three' ? '台番号・機種名を検索' : '機種名を検索';
    el('search').setAttribute('aria-label', el('search').placeholder);
    el('toggleAll').textContent = showAll ? '上位10件に戻す' : 'すべて表示';
    el('cards').innerHTML = shown.length ? shown.map((row,i) => scope === 'tail' ? tailCard(row,i+1) : scope === 'corner' ? cornerCard(row,i+1) : scope === 'three' ? threeCard(row,i+1) : modelCard(row,i+1)).join('') : '<div class="empty">該当データがありません</div>';
  }}
  document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active',x===button)); scope=button.dataset.scope; metric=defaultMetric(scope); showAll=false; options(); render();
  }}));
  el('metric').addEventListener('change', e => {{ metric=e.target.value; render(); }});
  el('toggleAll').addEventListener('click', () => {{ showAll=!showAll; render(); }});
  el('search').addEventListener('input', render);
  el('timestamp').textContent = `一覧完了 ${{dateTime(data.sourceCompletedAt)}} / 作成 ${{dateTime(data.generatedAt)}}`;
  el('machineCount').textContent = num(data.machineCount); el('eligibleCount').textContent = num(data.eligibleCount); el('threshold').textContent = `${{num(data.graphMinGames)}}G`;
  const layoutText = data.reference?.layout_matches ? ` 配置参照 ${{num(data.reference.layout_matches)}}台、3台並びは物理座標順です。` : '';
  const qualityText = Number(data.eligibleCount || 0) > 0
    ? `差枚対象 ${{num(data.eligibleCount)}}台のうち前回グラフ再利用 ${{num(data.reusedCount)}}台。カード内にOCR信頼度と取得時刻差を表示します。平均差枚と勝率はしきい値以上のみ、平均G・確率・最高出玉は全台集計です。`
    : `現在、${{num(data.graphMinGames)}}G以上の差枚対象台はありません。差枚・勝率ランキングは未表示ですが、平均G・確率・最高出玉は取得済みの全台データで表示しています。`;
  const timeText = data.sourceTimeStatus?.note ? ` ${{data.sourceTimeStatus.note}}` : '';
  el('qualityNote').textContent = `${{qualityText}}${{timeText}}${{layoutText}}`;
  options(); render();
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a mobile Site Seven report.")
    script_dir = Path(__file__).resolve().parent
    output_dir = script_dir / "output"
    parser.add_argument("--input", type=Path, default=output_dir / "site777_analysis_filtered.json")
    parser.add_argument("--output", type=Path, default=output_dir / "site777_mobile_report.html")
    args = parser.parse_args()
    result = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if result.get("diff_valid_count") != result.get("graph_eligible_count"):
        raise SystemExit("差枚対象台が未完了のためモバイルレポートを生成しません")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_html(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "models": result.get("model_count"),
                "machines": result.get("machine_count"),
                "eligible": result.get("graph_eligible_count"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
