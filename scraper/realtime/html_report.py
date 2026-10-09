"""ランキングJSONを、人が読める自己完結型のHTMLにする。

使い方: python -m scraper.realtime.html_report [ランキングJSON]
引数なしなら output/rankings の最新を使い、同じ場所に .html を書く。
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RANK_DIR = HERE / "output" / "rankings"

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>リアルタイム収集ランキング</title>
<style>
:root{--bg:#fff;--fg:#1d2433;--mute:#667085;--line:#e4e7ec;--card:#f7f8fa;--bar:#2f6fdd;--hot:#d9480f}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14171f;--fg:#e6e9f0;--mute:#98a2b3;--line:#2a2f3b;--card:#1b1f29;--bar:#6ea0ff;--hot:#ff8a4c}}
:root[data-theme="dark"]{--bg:#14171f;--fg:#e6e9f0;--mute:#98a2b3;--line:#2a2f3b;--card:#1b1f29;--bar:#6ea0ff;--hot:#ff8a4c}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,"Hiragino Sans","Yu Gothic UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 6px}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
#theme{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:5px 12px;font:inherit;font-size:13px;cursor:pointer;white-space:nowrap}
.sub,.note{color:var(--mute);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}
.chips button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:4px 12px;font:inherit;font-size:13px;cursor:pointer}
.chips button[aria-pressed="true"]{background:var(--bar);border-color:var(--bar);color:#fff}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;min-width:640px}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--card);font-size:12px;color:var(--mute);font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
.bar{display:inline-block;height:8px;border-radius:4px;background:var(--bar);vertical-align:middle;margin-right:6px}
.hot{color:var(--hot);font-weight:700}
details{margin-top:24px}summary{cursor:pointer;font-weight:600}
</style></head><body><main>
<div class="top"><div><h1>リアルタイム収集ランキング</h1>
<div class="sub" id="meta"></div></div>
<button id="theme" type="button"></button></div>
<div class="chips" id="chips" role="group" aria-label="ホール絞り込み"></div>
<h2>設定5以上の確率(RBで判別できる機種)</h2>
<div class="note">RB0の台は情報が無いので除外。AT機はスマスロ北斗のみRBで推定。最尤設定は事後確率が最大の設定、期待設定は事後確率で平均した設定値(どちらも近似)。確度が低い台は事前分布に近いだけ。途中の高RBは最終で平均に回帰しうる。低RBで台や並びを否定する根拠にもしない。</div>
<div class="wrap"><table id="t1"></table></div>
<details><summary id="s3"></summary><div class="wrap"><table id="t3"></table></div></details>
<details><summary id="s4"></summary><div class="wrap"><table id="t4"></table></div></details>
</main>
<script>
const D=__DATA__;
const esc=s=>String(s??"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const halls=[...new Set(Object.values(D).flat().map(r=>r.hall))];
let cur=null;
const pick=a=>a.filter(r=>!cur||r.hall===cur);
const fmtT=s=>(s||"").slice(11,16);
function rows(a,cols,limit){
  const h="<tr>"+cols.map(c=>`<th class="${c.n?"n":""}">${c.h}</th>`).join("")+"</tr>";
  const b=a.slice(0,limit).map((r,i)=>"<tr>"+cols.map(c=>`<td class="${c.n?"n":""}">${c.f(r,i)}</td>`).join("")+"</tr>").join("");
  return h+(b||`<tr><td colspan="${cols.length}" class="note">該当なし</td></tr>`);
}
const base=[{h:"順位",n:1,f:(r,i)=>i+1},{h:"ホール",f:r=>esc(r.hall)},{h:"台",n:1,f:r=>r.unit},{h:"機種",f:r=>esc(r.model)},{h:"G",n:1,f:r=>r.games==null?"-":r.games.toLocaleString()},{h:"RB",n:1,f:r=>r.rb??"-"}];
const root=document.documentElement,tbtn=document.getElementById("theme");
const eff=()=>root.dataset.theme||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light");
const tlabel=()=>{tbtn.textContent=eff()==="dark"?"☀ ライトにする":"🌙 ダークにする"};
try{const s=localStorage.getItem("theme");if(s)root.dataset.theme=s}catch(e){}
tbtn.addEventListener("click",()=>{const n=eff()==="dark"?"light":"dark";root.dataset.theme=n;try{localStorage.setItem("theme",n)}catch(e){}tlabel()});
tlabel();
const sp=r=>Object.entries(r.setting_probabilities||{}).map(([s,p])=>[+s,p]).sort((a,b)=>a[0]-b[0]);
const mapS=r=>{const a=sp(r);return a.length?a.reduce((m,x)=>x[1]>m[1]?x:m):null};
const expS=r=>{const a=sp(r);return a.length?a.reduce((t,x)=>t+x[0]*x[1],0):null};
const setCols=[
  {h:"最尤設定",f:r=>{const m=mapS(r);if(!m)return "-";if(m[1]<1/sp(r).length+0.1)return `<span class="sub">情報不足</span>`;return `設定${m[0]} <span class="sub">(${Math.round(m[1]*100)}%)</span>`}},
  {h:"期待設定",n:1,f:r=>{const e=expS(r);return e==null?"-":e.toFixed(1)}}];
function draw(){
  document.getElementById("chips").innerHTML=[null,...halls].map(h=>`<button aria-pressed="${cur===h}" data-h="${h??""}">${h??"すべて"}</button>`).join("");
  const r1=pick(D.ranked).filter(r=>r.rb>0);
  document.getElementById("t1").innerHTML=rows(r1,[...base,
    {h:"RB確率",n:1,f:r=>"1/"+Math.round(r.games/r.rb)},
    ...setCols,
    {h:"設定5以上",f:r=>{const p=r.p_high;return `<span class="bar" style="width:${Math.round(p*90)}px"></span><span class="${p>=.7&&r.confidence>=.1?"hot":""}">${p.toFixed(2)}</span>`}},
    {h:"確度",n:1,f:r=>r.confidence.toFixed(2)}],50);
  const r3=pick(D.uncertain).filter(r=>r.rb>0&&r.p_high!=null);
  document.getElementById("s3").textContent=`判別困難に近い機種 ${r3.length}台(開く)`;
  document.getElementById("t3").innerHTML=rows(r3,[...base,{h:"設定5以上",n:1,f:r=>r.p_high==null?"-":r.p_high.toFixed(2)}],100);
  const r4=pick(D.new_machines);
  document.getElementById("s4").textContent=`新台・累計G不足など ${r4.length}台(開く)`;
  document.getElementById("t4").innerHTML=rows(r4,[...base,{h:"備考",f:r=>esc((r.notes||[]).join(" / "))}],100);
}
document.getElementById("chips").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;cur=b.dataset.h||null;draw()});
const t=Object.values(D).flat().map(r=>r.observed_at).filter(Boolean).sort();
document.getElementById("meta").textContent=`観測 ${fmtT(t[0])}〜${fmtT(t[t.length-1])} / RB判別 ${D.ranked.filter(r=>r.rb>0).length}台(RB0は除外)`;
draw();
</script></body></html>
"""


def render(src: Path) -> Path:
    data = json.loads(src.read_text(encoding="utf-8"))
    keep = (
        "hall",
        "unit",
        "model",
        "games",
        "rb",
        "p_high",
        "confidence",
        "score",
        "setting_probabilities",
        "observed_at",
    )
    slim = {}
    for key in ("ranked", "uncertain", "new_machines"):
        items = data.get(key, [])
        if key in ("ranked", "uncertain"):
            items = [r for r in items if r.get("rb")]  # RB0は情報なし
        if key == "uncertain":
            items = items[:100]
        slim[key] = [
            {
                **{k: r.get(k) for k in keep},
                "setting_probabilities": {s: round(p, 4) for s, p in (r.get("setting_probabilities") or {}).items()},
                **({"notes": r.get("notes", [])} if key == "new_machines" else {}),
            }
            for r in items
        ]
    data = slim
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out = src.with_suffix(".html")
    out.write_text(PAGE.replace("__DATA__", payload), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        src = Path(args[0])
    else:
        files = sorted(RANK_DIR.glob("ranking_*.json"))
        if not files:
            print("ランキングJSONがありません", file=sys.stderr)
            return 1
        src = files[-1]
    print(render(src))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
