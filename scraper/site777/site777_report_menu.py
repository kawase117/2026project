# -*- coding: utf-8 -*-
"""報告メニュー1〜5を固定順で出す（スキル site777-highsetting-scan の手順5）。

なぜコードにするか
------------------
2026-09-19 の楽園蒲田で、収集後の報告が6項目中2項目しか出ていなかった。
手順書は文章で、守らなくてもエラーにならない。必須マトリクスと同じく
「出せなければ終了コード2」にして、黙って飛ばせなくする。

出せない項目は空欄にせず「未出力（理由）」と書く。6（予告突合）は site777_live_brief.py 側。
"""

from __future__ import annotations

import math
import os
import statistics as st
from collections import defaultdict

REQUIRED = (
    "1. 全体水準",
    "2. 差枚TOPと機種別平均",
    "3. 並びブロック",
    "4. ニブイチ判定",
    "5. 全台系判定（全台合算）",
)
NIBUICHI_MIN_MODEL = 3
BLOCK_MIN = 4


def _pctl(values, q):
    s = sorted(values)
    if not s:
        return 0.0
    return s[min(len(s) - 1, max(0, int(math.ceil(q * len(s))) - 1))]


def build(machines, setting_report_path, update_time):
    out = []
    produced = []
    readable = [m for m in machines if m.get("latest_diff") is not None]
    hall_games = st.mean(m["games"] for m in machines) if machines else 0.0

    # 1. 全体水準
    out.append("## 報告メニュー")
    out.append("")
    out.append("### 1. 全体水準")
    produced.append(REQUIRED[0])
    if readable:
        diffs = [m["latest_diff"] for m in readable]
        cens = sum(1 for m in readable if m.get("diff_censored_high") or m.get("diff_censored_low"))
        out.append(
            "- データ時刻 %s / 差枚が読めた %d/%d台 / 平均G %.0f / 差枚 平均%+.0f・中央値%+.0f・勝率%.0f%% / 軸張り付き%d台"
            % (
                update_time,
                len(readable),
                len(machines),
                hall_games,
                st.mean(diffs),
                st.median(diffs),
                100.0 * sum(1 for d in diffs if d > 0) / len(diffs),
                cens,
            )
        )
        out.append("- ⚠️ 差枚は2,000G到達組に偏る。時刻をまたぐ比較や「今日は弱い」の根拠に使わない。")
    else:
        out.append("- 未出力（差枚が読めた台が0）")
    out.append("")

    # 2. 差枚TOPと機種別平均
    out.append("### 2. 差枚TOPと機種別平均（3台以上）")
    produced.append(REQUIRED[1])
    if readable:
        top = sorted(readable, key=lambda m: -m["latest_diff"])[:10]
        out.append(
            "差枚TOP10: "
            + " / ".join(
                "%s %s %+.0f(%dG)" % (m["machine_number"], m["model_name"][:8], m["latest_diff"], m["games"])
                for m in top
            )
        )
        by_model = defaultdict(list)
        for m in machines:
            by_model[m["model_name"]].append(m)
        rows = []
        for name, ms in by_model.items():
            ds = [m["latest_diff"] for m in ms if m.get("latest_diff") is not None]
            if len(ms) >= 3 and ds:
                g = st.mean(m["games"] for m in ms)
                rows.append(
                    (
                        st.mean(ds),
                        name,
                        len(ms),
                        len(ds),
                        g / hall_games if hall_games else 0.0,
                        sum(1 for d in ds if d >= 1800),
                    )
                )
        rows.sort(reverse=True)
        out.append("")
        out.append("| 機種 | 設置 | 差枚台 | G比 | 平均差枚 | +1800超え |")
        out.append("|---|---:|---:|---:|---:|---:|")
        for mean, name, n, nd, gr, ov in rows[:12] + [r for r in rows[-3:] if r not in rows[:12]]:
            out.append("| %s | %d | %d | %.2f | %+.0f | %d |" % (name, n, nd, gr, mean, ov))
    else:
        out.append("- 未出力（差枚が読めた台が0）")
    out.append("")

    # 3. 並びブロック（台番号連続でプラス）
    out.append("### 3. 並びブロック（台番号が連続で差枚プラス、%d台以上）" % BLOCK_MIN)
    produced.append(REQUIRED[2])
    dmap = {int(m["machine_number"]): m for m in machines}
    blocks, cur = [], []
    for n in sorted(dmap):
        d = dmap[n].get("latest_diff")
        if d is not None and d > 0 and (not cur or n == cur[-1] + 1):
            cur.append(n)
        else:
            if len(cur) >= BLOCK_MIN:
                blocks.append(cur)
            cur = [n] if (d is not None and d > 0) else []
    if len(cur) >= BLOCK_MIN:
        blocks.append(cur)
    if blocks:
        for b in blocks:
            ds = [dmap[n]["latest_diff"] for n in b]
            out.append(
                "- %d-%d（%d台）合計%+.0f / 機種 %s"
                % (b[0], b[-1], len(b), sum(ds), "・".join(sorted({dmap[n]["model_name"][:8] for n in b})))
            )
    else:
        out.append("- 該当なし（差枚が読めた台が少ない時間帯は検出力が低い。否定に使わない）")
    out.append("- 回転数の3連（G比≧2・両隣低回転）はブリーフの軸スイープと各台表を併読する。")
    out.append("")

    # 4. ニブイチ判定（announce._judge_model_named_ratio と同じ式、N=2）
    out.append("### 4. ニブイチ判定（機種の上位半数平均 vs ホール上位1/2分位平均・当該機種除く）")
    produced.append(REQUIRED[3])
    by_model = defaultdict(list)
    for m in readable:
        by_model[m["model_name"]].append(m["latest_diff"])
    rows = []
    for name, ds in by_model.items():
        if len(ds) < NIBUICHI_MIN_MODEL:
            continue
        others = [m["latest_diff"] for m in readable if m["model_name"] != name]
        if not others:
            continue
        q = _pctl(others, 0.5)
        hall_top = st.mean([d for d in others if d >= q])
        k = -(-len(ds) // 2)
        mine_top = st.mean(sorted(ds, reverse=True)[:k])
        rows.append((mine_top - hall_top, name, len(ds), mine_top, hall_top))
    rows.sort(reverse=True)
    if rows:
        out.append("| 機種 | 差枚台 | 上位半数平均 | ホール上位1/2平均 | 差 |")
        out.append("|---|---:|---:|---:|---:|")
        for diff, name, n, a, b in rows[:8]:
            out.append("| %s | %d | %+.0f | %+.0f | %+.0f |" % (name, n, a, b, diff))
        out.append("- ⚠️ 差枚ベースなので設定の証拠ではない。判別可能機種はRB確率側で確認する。")
    else:
        out.append("- 未出力（差枚が読めた3台以上の機種が無い）")
    out.append("")

    # 5. 全台系判定（設定レポートの表を転記）
    out.append("### 5. 全台系判定（全台合算）")
    lines = []
    if os.path.exists(setting_report_path):
        with open(setting_report_path, encoding="utf-8-sig") as h:
            text = h.read().splitlines()
        start = next((i for i, l in enumerate(text) if l.startswith("## 機種別 全台系判定")), None)
        if start is not None:
            for l in text[start + 1 :]:
                if l.startswith("|"):
                    lines.append(l)
                elif lines:
                    break
    if lines:
        produced.append(REQUIRED[4])
        out.extend(lines)
        out.append("- 「判定保留（情報不足）」は否定ではない。合算平均が高いだけで全台系と言わない。")
    else:
        out.append("- 未出力（設定レポートに全台系判定表が無い: %s）" % setting_report_path)
    out.append("")
    return out, produced


def missing(produced):
    return [r for r in REQUIRED if r not in produced]
