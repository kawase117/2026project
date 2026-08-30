from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from statistics import mean


def probability(games: int | None, count: int | None) -> float | None:
    if games is None or count is None or games < 0 or count <= 0:
        return None
    return games / count


def build_analysis(source: dict) -> dict:
    machines = source.get("machines", [])
    details = source.get("details", {})
    enriched: list[dict] = []
    for machine in machines:
        row = dict(machine)
        detail = details.get(machine["machine_number"])
        row["detail_status"] = "取得" if detail else "未取得"
        if detail:
            row.update({key: value for key, value in detail.items() if key not in {"machine_number", "history"}})
            row["history_count"] = len(detail.get("history", []))
        else:
            row["history_count"] = 0
        games = row.get("games")
        row["combined_probability"] = row.get("combined_probability") or probability(
            games, (row.get("bb_count") or 0) + (row.get("rb_count") or 0)
        )
        row["bb_probability"] = row.get("bb_probability") or probability(games, row.get("bb_count"))
        row["rb_probability"] = row.get("rb_probability") or probability(games, row.get("rb_count"))
        enriched.append(row)

    by_model: dict[str, list[dict]] = defaultdict(list)
    by_tail: dict[str, list[dict]] = defaultdict(list)
    for row in enriched:
        by_model[row["machine_name"]].append(row)
        by_tail[row["machine_number"][-1]].append(row)

    def aggregate(label: str, rows: list[dict]) -> dict:
        detailed = [row for row in rows if row.get("games") is not None]
        diff_rows = [row for row in rows if row.get("latest_diff_estimated") is not None]
        total_games = sum(row["games"] for row in detailed)
        total_bb = sum(row.get("bb_count") or 0 for row in detailed)
        total_rb = sum(row.get("rb_count") or 0 for row in detailed)
        return {
            "label": label,
            "machine_count": len(rows),
            "detail_count": len(detailed),
            "total_games": total_games if detailed else None,
            "average_games": mean(row["games"] for row in detailed) if detailed else None,
            "total_bb": total_bb,
            "total_rb": total_rb,
            "bb_probability": probability(total_games, total_bb),
            "rb_probability": probability(total_games, total_rb),
            "combined_probability": probability(total_games, total_bb + total_rb),
            "average_diff_estimated": mean(row["latest_diff_estimated"] for row in diff_rows) if diff_rows else None,
            "win_rate_estimated": mean(row["latest_diff_estimated"] > 0 for row in diff_rows) if diff_rows else None,
            "average_max_payout": mean(row["max_payout"] for row in detailed if row.get("max_payout") is not None)
            if any(row.get("max_payout") is not None for row in detailed)
            else None,
        }

    models = [aggregate(name, rows) for name, rows in by_model.items()]
    tails = [aggregate(tail, rows) for tail, rows in sorted(by_tail.items())]
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": source.get("mode"),
        "business_date": source.get("business_date"),
        "observed_at": source.get("observed_at"),
        "hall_name": source.get("hall_name"),
        "machine_count": len(enriched),
        "detail_count": sum(row["detail_status"] == "取得" for row in enriched),
        "reused_detail_count": source.get("reused_detail_count", 0),
        "request_count": source.get("request_count"),
        "complete": bool(source.get("complete")),
        "failures": source.get("failures", []),
        "machines": enriched,
        "models": models,
        "tails": tails,
    }


def build_html(analysis: dict) -> str:
    serialized = json.dumps(analysis, ensure_ascii=False).replace("</", "<\\/")
    hall_name = escape(analysis.get("hall_name") or "DMM台データ")
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><link rel="icon" href="data:,">
<title>{hall_name} スロット速報</title>
<style>
:root{{--bg:#080b10;--panel:#121823;--panel2:#1a2230;--line:#2a3547;--text:#edf2f8;--muted:#91a0b4;--accent:#66d9ef;--good:#56e39f;--bad:#ff6b7a}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}}
.app{{max-width:960px;margin:auto;padding:14px}}h1{{font-size:21px;margin:6px 0}}.sub,.note{{color:var(--muted);font-size:12px;line-height:1.55}}
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin:13px 0}}.summary div{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 5px;text-align:center}}.summary strong{{display:block;font-size:19px;color:var(--accent)}}.summary span{{font-size:10px;color:var(--muted)}}
.sticky{{position:sticky;top:0;z-index:5;background:rgba(8,11,16,.96);padding:8px 0}}.tabs{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}}button,select,input{{font:inherit}}button,select,input{{min-height:43px;border:1px solid var(--line);border-radius:11px;background:var(--panel);color:var(--text);padding:0 10px}}button.active{{background:var(--accent);color:#061018;border-color:var(--accent);font-weight:800}}.filters{{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin-top:7px}}#search{{width:100%;margin-top:7px}}
.status{{margin:10px 0;padding:10px;border-radius:10px;background:#172031;border:1px solid var(--line)}}.status.bad{{background:#30151b;border-color:#7b303c;color:#ffd5da}}
.cards{{display:grid;gap:9px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:13px;overflow:hidden}}summary{{list-style:none;padding:12px;cursor:pointer}}summary::-webkit-details-marker{{display:none}}.top{{display:grid;grid-template-columns:46px 1fr auto;gap:8px;align-items:center}}.unit{{color:var(--accent);font-weight:900}}.name{{font-weight:750;overflow-wrap:anywhere}}.value{{font-weight:900;text-align:right}}.good{{color:var(--good)}}.bad{{color:var(--bad)}}.chips{{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}}.chip{{font-size:10px;color:#c8d2df;background:var(--panel2);border-radius:999px;padding:5px 7px}}.detail{{border-top:1px solid var(--line);padding:10px 12px}}.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}}.metric{{background:var(--panel2);padding:8px;border-radius:9px}}.metric span{{display:block;color:var(--muted);font-size:10px}}.metric strong{{font-size:14px}}.graph{{display:block;margin-top:10px;text-align:center;color:var(--accent)}}
@media(min-width:700px){{.cards{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main class="app">
<h1>{hall_name} スロット速報</h1><div class="sub" id="sub"></div>
<div class="summary"><div><strong id="machineCount">--</strong><span>全台</span></div><div><strong id="detailCount">--</strong><span>詳細</span></div><div><strong id="mode">--</strong><span>モード</span></div><div><strong id="requests">--</strong><span>HTTP</span></div></div>
<div id="status" class="status"></div>
<div class="sticky"><div class="tabs"><button class="active" data-scope="machines">台別</button><button data-scope="models">機種別</button><button data-scope="tails">末尾別</button></div><div class="filters"><select id="metric"></select><button id="toggle">上位20件</button></div><input id="search" type="search" placeholder="台番号・機種名を検索"></div>
<section id="cards" class="cards"></section><p class="note">差枚は公開SVGグラフの軸と終点からの推定値です。サイト表示値そのものではありません。Quickでは詳細未取得台の累計G・最大持ち玉・推定差枚は表示されません。</p>
</main><script id="data" type="application/json">{serialized}</script><script>
const data=JSON.parse(document.getElementById('data').textContent);let scope='machines',metric='games',showAll=false;
const E=id=>document.getElementById(id),num=(v,d=0)=>v==null?'--':Number(v).toLocaleString('ja-JP',{{maximumFractionDigits:d}}),prob=v=>v==null?'--':`1/${{num(v,1)}}`,pct=v=>v==null?'--':`${{(100*v).toFixed(1)}}%`,esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])),dt=v=>{{let d=new Date(v);return Number.isNaN(d.getTime())?String(v??'不明'):d.toLocaleString('ja-JP',{{timeZone:'Asia/Tokyo',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}})}};
const sets={{machines:[['games','累計G'],['latest_diff_estimated','推定差枚'],['max_payout','最大持ち玉'],['rb_probability','RB確率'],['bb_probability','BB確率'],['bb_count','BB回数'],['rb_count','RB回数']],models:[['average_games','平均G'],['average_diff_estimated','平均推定差枚'],['win_rate_estimated','推定勝率'],['rb_probability','RB確率'],['bb_probability','BB確率'],['average_max_payout','平均最大持ち玉']],tails:[['average_games','平均G'],['average_diff_estimated','平均推定差枚'],['win_rate_estimated','推定勝率'],['rb_probability','RB確率'],['bb_probability','BB確率']]}};
const lowBetter=k=>k.includes('probability'),format=(k,v)=>k.includes('probability')?prob(v):k.includes('rate')?pct(v):num(v,1),cls=(k,v)=>k.includes('diff')&&v!=null?(v>0?'good':v<0?'bad':''):'';
function options(){{E('metric').innerHTML=sets[scope].map(x=>`<option value="${{x[0]}}">${{x[1]}}</option>`).join('');if(!sets[scope].some(x=>x[0]===metric))metric=sets[scope][0][0];E('metric').value=metric}}
function rows(){{let rows=data[scope].filter(x=>x[metric]!=null),q=E('search').value.trim().toLowerCase();rows=rows.filter(x=>!q||String(x.machine_number??x.label).toLowerCase().includes(q)||String(x.machine_name??'').toLowerCase().includes(q));return rows.sort((a,b)=>lowBetter(metric)?a[metric]-b[metric]:b[metric]-a[metric])}}
function card(x,i){{if(scope==='machines'){{let graph=x.graph_path?`<a class="graph" href="${{esc(x.graph_path)}}">当日スランプグラフを開く</a>`:'';return `<details class="card"><summary><div class="top"><span class="unit">${{esc(x.machine_number)}}</span><span class="name">${{esc(x.machine_name)}}</span><span class="value ${{cls(metric,x[metric])}}">${{format(metric,x[metric])}}</span></div><div class="chips"><span class="chip">${{num(x.games)}}G</span><span class="chip">BB ${{num(x.bb_count)}}</span><span class="chip">RB ${{num(x.rb_count)}}</span><span class="chip">現在 ${{num(x.current_start)}}</span><span class="chip">詳細 ${{x.detail_status}}</span></div></summary><div class="detail"><div class="grid"><div class="metric"><span>推定差枚</span><strong class="${{cls('diff',x.latest_diff_estimated)}}">${{num(x.latest_diff_estimated)}}枚</strong></div><div class="metric"><span>最大持ち玉</span><strong>${{num(x.max_payout)}}枚</strong></div><div class="metric"><span>合成</span><strong>${{prob(x.combined_probability)}}</strong></div><div class="metric"><span>履歴件数</span><strong>${{num(x.history_count)}}件</strong></div></div>${{graph}}</div></details>`}}return `<details class="card"><summary><div class="top"><span class="unit">${{i}}</span><span class="name">${{scope==='tails'?'末尾 '+esc(x.label):esc(x.label)}}</span><span class="value ${{cls(metric,x[metric])}}">${{format(metric,x[metric])}}</span></div><div class="chips"><span class="chip">${{x.machine_count}}台</span><span class="chip">詳細 ${{x.detail_count}}台</span><span class="chip">平均G ${{num(x.average_games)}}</span><span class="chip">推定勝率 ${{pct(x.win_rate_estimated)}}</span></div></summary></details>`}}
function render(){{let all=rows(),shown=showAll?all:all.slice(0,20);E('toggle').textContent=showAll?'上位20件に戻す':'すべて表示';E('cards').innerHTML=shown.length?shown.map((x,i)=>card(x,i+1)).join(''):'<div class="status">該当データがありません</div>'}}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('active',x===b));scope=b.dataset.scope;metric=sets[scope][0][0];showAll=false;options();render()}});E('metric').onchange=e=>{{metric=e.target.value;render()}};E('toggle').onclick=()=>{{showAll=!showAll;render()}};E('search').oninput=render;
E('machineCount').textContent=num(data.machine_count);E('detailCount').textContent=num(data.detail_count);E('mode').textContent=String(data.mode||'--').toUpperCase();E('requests').textContent=num(data.request_count);E('sub').textContent=`営業日 ${{data.business_date||'不明'}} / 取得 ${{dt(data.observed_at)}}`;
E('status').textContent=data.complete?`取得完了。詳細 ${{data.detail_count}}/${{data.machine_count}}台（再利用 ${{data.reused_detail_count}}台）`:`部分取得: 失敗 ${{data.failures.length}}件`;E('status').classList.toggle('bad',!data.complete);options();render();
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="DMM/Goraggioスマホレポートを生成する")
    script_dir = Path(__file__).resolve().parent
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--analysis-output", type=Path, default=script_dir / "output" / "latest_analysis.json")
    parser.add_argument("--html-output", type=Path, default=script_dir / "output" / "mobile_report.html")
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    analysis = build_analysis(source)
    args.analysis_output.parent.mkdir(parents=True, exist_ok=True)
    args.analysis_output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    args.html_output.write_text(build_html(analysis), encoding="utf-8")
    print(json.dumps({"analysis": str(args.analysis_output), "html": str(args.html_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
