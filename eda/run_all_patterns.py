"""
全ホール横断パターン検索 — instinctから抽出した全既知パターンを全9ホールに適用

実行方法:
    cd C:/Users/.../2026project
    python3 eda/run_all_patterns.py

出力:
    document/sessions/YYYY-MM-DD-all-hall-pattern-scan.md
"""

import warnings
warnings.filterwarnings("ignore")
import sys
import io
from pathlib import Path
from datetime import date
import pandas as pd
import numpy as np

# Windows cp932 対策: stdout を UTF-8 に強制
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))
from eda.core import load_hall_df, scan_dimension, lag_analysis, HALL_DBS

OUTPUT_DIR = Path(__file__).parent.parent / "document" / "sessions"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / f"{date.today().isoformat()}-all-hall-pattern-scan.md"

lines = []

def p(s=""):
    print(s)
    lines.append(s)

# ── instinctから抽出したスキャン定義 ─────────────────────────────────────────
SCANS = [
    # ── 1次元 ────────────────────────────────────────────────────────────
    dict(name="DD系統(4系/7系)",       cols=["dd_group"],                    filters=None,               min_n=10),
    dict(name="日末尾X系(0-9)",        cols=["dd_mod10"],                    filters=None,               min_n=10),
    dict(name="DD個別(1-31)",          cols=["dd"],                          filters=None,               min_n=5),
    dict(name="曜日",                  cols=["day_of_week"],                 filters=None,               min_n=10),
    dict(name="台番号末尾",             cols=["machine_digit"],               filters=None,               min_n=10),
    dict(name="機種名",                cols=["machine_name"],                filters=None,               min_n=20),
    dict(name="第N曜日",               cols=["weekday_nth"],                 filters=None,               min_n=8),
    # ── 2次元（全日）────────────────────────────────────────────────────
    dict(name="DD系統×曜日",           cols=["dd_group","day_of_week"],      filters=None,               min_n=8),
    dict(name="日末尾X系×曜日",        cols=["dd_mod10","day_of_week"],      filters=None,               min_n=8),
    dict(name="曜日×台番号末尾",        cols=["day_of_week","machine_digit"], filters=None,               min_n=8),
    dict(name="DD系統×台番号末尾",      cols=["dd_group","machine_digit"],    filters=None,               min_n=8),
    dict(name="機種名×DD系統",          cols=["machine_name","dd_group"],     filters=None,               min_n=8),
    dict(name="機種名×曜日",            cols=["machine_name","day_of_week"],  filters=None,               min_n=8),
    # ── 2次元（イベント日限定）──────────────────────────────────────────
    dict(name="[EVT]DD系統×曜日",      cols=["dd_group","day_of_week"],      filters={"is_any_event":1}, min_n=5),
    dict(name="[EVT]曜日×台末尾",      cols=["day_of_week","machine_digit"], filters={"is_any_event":1}, min_n=5),
    dict(name="[EVT]日末尾X系×曜日",   cols=["dd_mod10","day_of_week"],      filters={"is_any_event":1}, min_n=5),
    # ── 2次元（非イベント日）────────────────────────────────────────────
    dict(name="[非EVT]DD系統×曜日",    cols=["dd_group","day_of_week"],      filters={"is_any_event":0}, min_n=8),
    dict(name="[非EVT]曜日×台末尾",    cols=["day_of_week","machine_digit"], filters={"is_any_event":0}, min_n=8),
    dict(name="[非EVT]日末尾X系×曜日", cols=["dd_mod10","day_of_week"],      filters={"is_any_event":0}, min_n=8),
    # ── x_day限定 ───────────────────────────────────────────────────────
    dict(name="[X-day]曜日×台末尾",    cols=["day_of_week","machine_digit"], filters={"is_x_day":1},     min_n=5),
    dict(name="[非x_day]曜日×台末尾",  cols=["day_of_week","machine_digit"], filters={"is_x_day":0},     min_n=8),
]


def global_bias_check(result, df_raw, cols):
    """deviation = avg_diff - ホール全体平均（グローバルバイアス混同チェック）"""
    global_mean = df_raw["diff"].mean()
    result["deviation"] = (result["avg_diff"] - global_mean).round(0).astype(int)
    return result


def fmt_tier_rows(result, cols, top_n=5, tier_filter=None):
    if tier_filter:
        subset = result[result["tier"].isin(tier_filter)].head(top_n)
    else:
        subset = result.head(top_n)
    if subset.empty:
        return "  （なし）"
    rows = []
    for _, r in subset.iterrows():
        key = " / ".join(str(r[c]) for c in cols)
        dev = f" dev={r['deviation']:+d}" if "deviation" in r else ""
        ci  = f" CI=[{r.get('ci_lo','?')},{r.get('ci_hi','?')}]"
        rows.append(
            f"  {key}: avg={r['avg_diff']:+d} plus={r['plus_rate']:.0f}%"
            f" n={r['n']} tier={r['tier']}"
            f" p={r.get('p_value',float('nan')):.3f}"
            f" eps2={r.get('epsilon_sq',float('nan')):.4f}"
            f"{ci}{dev}"
        )
    return "\n".join(rows)


# ── メイン実行 ────────────────────────────────────────────────────────────────

p(f"# 全ホール横断パターン検索レポート")
p(f"生成日: {date.today().isoformat()}")
p(f"対象ホール: {', '.join(HALL_DBS.keys())}")
p()

all_results = []  # (scan_name, hall, result_df)

for scan in SCANS:
    sname, cols, filters, min_n = scan["name"], scan["cols"], scan["filters"], scan["min_n"]
    p(f"\n{'='*72}")
    p(f"## {sname}  ({' × '.join(cols)})")
    if filters:
        p(f"   フィルタ: {filters}")
    p()

    hall_ab_keys = {}  # hall -> set of pattern_key with Tier A/B

    for hall in HALL_DBS:
        try:
            df = load_hall_df(hall)
            result = scan_dimension(hall, cols, filters=filters, min_n=min_n, df=df)
            if result.empty:
                continue
            result = global_bias_check(result, df, cols)
            all_results.append((sname, hall, result.copy()))

            tier_counts = result["tier"].value_counts().to_dict()
            ab = result[result["tier"].isin(["A","B"])]
            av = result[result["tier"] == "Avoid"]

            p(f"### {hall}  "
              f"[A={tier_counts.get('A',0)} B={tier_counts.get('B',0)} "
              f"C={tier_counts.get('C',0)} Avoid={tier_counts.get('Avoid',0)}]")

            if not ab.empty:
                p("  ▲ Tier A/B （上位5件）:")
                p(fmt_tier_rows(ab, cols, top_n=5))

            if not av.empty:
                p("  ▼ Avoid（下位3件）:")
                p(fmt_tier_rows(av.sort_values("avg_diff"), cols, top_n=3))

            p()

            hall_ab_keys[hall] = set(
                "_".join(str(ab.iloc[i][c]) for c in cols)
                for i in range(len(ab))
            )
        except Exception as e:
            p(f"  {hall}: ERROR -- {e}")
            p()

    # クロスホール比較（2ホール以上でTier A/B）
    all_keys = {}
    for hall, keys in hall_ab_keys.items():
        for k in keys:
            all_keys.setdefault(k, []).append(hall)
    universal = {k: v for k, v in all_keys.items() if len(v) >= 2}
    if universal:
        p(f"  ★ **共通パターン（2ホール以上でTier A/B）**:")
        for k, halls_list in sorted(universal.items(), key=lambda x: -len(x[1])):
            p(f"    {k}: {', '.join(halls_list)}")
        p()


# ── ラグ分析 ──────────────────────────────────────────────────────────────────

p(f"\n{'='*72}")
p(f"## ラグ分析（機種名単位・据え/リバウンド）")
p()

for hall in HALL_DBS:
    p(f"### {hall}")
    try:
        lag = lag_analysis(hall, "machine_name", lag=1, min_n=5)
        valid = lag.dropna(subset=["rebound_rate","streak_rate"])
        if valid.empty:
            p("  （サンプル不足）")
        else:
            top3_r = valid.nlargest(3, "rebound_rate")
            top3_s = valid.nlargest(3, "streak_rate")
            p("  リバウンド上位（前日−→当日+）:")
            for _, r in top3_r.iterrows():
                p(f"    {r['machine_name']}: "
                  f"rebound={r['rebound_rate']:.0f}% n={r['n_after_minus']} "
                  f"avg_after_minus={r['avg_diff_after_minus']:.0f}")
            p("  据え継続上位（前日+→当日+）:")
            for _, r in top3_s.iterrows():
                p(f"    {r['machine_name']}: "
                  f"streak={r['streak_rate']:.0f}% n={r['n_after_plus']} "
                  f"avg_after_plus={r['avg_diff_after_plus']:.0f}")
    except Exception as e:
        p(f"  ERROR: {e}")
    p()


# ── 全体サマリー：Tier A 一覧 ─────────────────────────────────────────────────

p(f"\n{'='*72}")
p(f"## 全体サマリー：Tier A パターン一覧（avg_diff降順）")
p()

summary_rows = []
for sname, hall, result in all_results:
    for _, r in result[result["tier"]=="A"].iterrows():
        summary_rows.append({
            "パターン":  sname,
            "ホール":    hall,
            "avg_diff":  r["avg_diff"],
            "plus_rate": r["plus_rate"],
            "n":         r["n"],
            "p_value":   round(r.get("p_value", float("nan")), 4),
            "eps2":        round(r.get("epsilon_sq", float("nan")), 4),
            "deviation": r.get("deviation", float("nan")),
        })

if summary_rows:
    df_sum = pd.DataFrame(summary_rows).sort_values("avg_diff", ascending=False)
    p(df_sum.to_string(index=False))
else:
    p("Tier A パターンが見つかりませんでした。")

# ── 保存 ─────────────────────────────────────────────────────────────────────

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

p(f"\n\n✓ レポート保存完了: {OUTPUT_FILE}")
