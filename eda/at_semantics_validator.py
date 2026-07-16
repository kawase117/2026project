# -*- coding: utf-8 -*-
"""AT機セマンティクス検証器 + 拡張ATバックテスト

呼び出し: venv/Scripts/python.exe eda/at_semantics_validator.py（単体実行）

背景（ユーザー指摘 2026-07-15）:
  - ホールのデータカウンターにより「RB」「BB」に何を集計するかが変わる
  - よって (ホール, 機種, カウント列, スペック表) の組ごとに適合検証が必要
  - 例: カバネリのRBは蒲田7/みとや=ボーナス初当りレンジ、楽園=ST初当りレンジに適合

検証ロジック:
  ホール×機種のプール観測レート(3000G+日の総count/総games)が、スペック表の
  [設定最低確率×0.88, 設定最高確率×1.06] に収まる (列, 表) を採用。
  複数適合時は設定間スプレッド(p_max/p_min)最大の表を優先（ラベル判別力最大化）。

除外（ユーザー確認済みドメイン知識）:
  - 東京喰種・マギアレコード: カウントに明確な設定差なし
  - 北斗の拳 転生の章2 等の北斗バリエーション: 明確な設定差はスマスロ北斗の拳のみ
  - 革命機ヴァルヴレイヴ2: 設定差 1/476→1/456 と極小で判別不能（レンジ検証でも除外される）

スペック出典: 1geki.jp（2026-07-15 subagent収集、各entryのsourceに記載）
出力: 適合マトリクス + 採用マスタ + 機種別/プールバックテスト集計のみ標準出力。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eda.highsetting_base_rate_phase0 import HALLS, load_hall  # noqa: E402
from eda.highsetting_predictability_phase0b import backtest  # noqa: E402

MIN_GAMES = 3000
P_HIGH_THRESHOLD = 0.80
HIGH_SETTINGS = {4, 5, 6}
RANGE_LO_MARGIN = 0.88  # 観測レート下限 = 設定最低確率 × これ
RANGE_HI_MARGIN = 1.06  # 観測レート上限 = 設定最高確率 × これ

# 機種名は machine_detailed_results.machine_name と完全一致。
# tables: 表名 -> {設定: 1/確率の分母}
AT_SPECS = {
    "スマスロ北斗の拳": {
        "source": "https://1geki.jp/slot/s_sma_hokutonoken/",
        "tables": {"at": {1: 383.4, 2: 370.5, 4: 297.8, 5: 258.7, 6: 235.1}},
    },
    "モンキーターンV": {
        "source": "https://1geki.jp/slot/l_monkeyturn5/0/",
        "tables": {"at": {1: 299.8, 2: 295.5, 4: 258.8, 5: 235.7, 6: 222.9}},
    },
    "かぐや様は告らせたい": {
        "source": "https://1geki.jp/slot/l_kaguya/",
        "tables": {"bonus": {1: 362, 2: 360, 3: 357, 4: 349, 5: 343, 6: 335}},
    },
    "甲鉄城のカバネリ 海門(うなと)決戦": {
        "source": "https://1geki.jp/slot/l_kabaneri2/0/",
        "tables": {
            "at_st": {1: 422.5, 2: 405.9, 3: 398.7, 4: 357.2, 5: 332.6, 6: 318.5},
            "bonus": {1: 254.2, 2: 242.3, 3: 239.6, 4: 214.0, 5: 203.2, 6: 195.1},
        },
    },
    "からくりサーカス": {
        "source": "https://1geki.jp/slot/l_karakuri/",
        "tables": {
            "at": {1: 564, 2: 543, 4: 469, 5: 451, 6: 447},
            "cz": {1: 333, 2: 320, 4: 292, 5: 277, 6: 275},
        },
    },
    "モンスターハンターライズ": {
        "source": "https://1geki.jp/slot/l_mh_rize/",
        "tables": {"at": {1: 309.5, 2: 301.4, 3: 290.8, 4: 256.4, 5: 237.1, 6: 230.8}},
    },
    "東京リベンジャーズ": {
        "source": "https://1geki.jp/slot/l_tokyo_revengers/0/",
        "tables": {
            "at": {1: 482.2, 2: 474.7, 3: 456.9, 4: 414.0, 5: 393.8, 6: 373.1},
            "bonus_total": {1: 282.4, 2: 279.5, 3: 272.2, 4: 255.8, 5: 249.1, 6: 240.1},
        },
    },
    "戦国乙女4 戦乱に閃く炯眼の軍師": {
        "source": "https://1geki.jp/slot/l_otome_keigan/0/",
        "tables": {"total": {1: 272.2, 2: 267.3, 3: 255.3, 4: 238.2, 5: 223.2, 6: 217.1}},
    },
    "化物語": {
        "source": "https://1geki.jp/slot/l_bakemonogatari/",
        "tables": {"at": {1: 265.1, 2: 260.7, 3: 252.1, 4: 238.8, 5: 230.8, 6: 219.6}},
    },
    "ゴッドイーター リザレクション": {
        "source": "https://1geki.jp/slot/l_godeater_r/",
        "tables": {"at": {1: 351.9, 2: 344.5, 3: 330.1, 4: 317.0, 5: 302.2, 6: 290.3}},
    },
    "スーパーブラックジャック": {
        "source": "https://1geki.jp/slot/l_sbj/",
        "tables": {"bonus": {1: 241.7, 2: 238.8, 3: 235.9, 4: 201.8, 5: 194.9, 6: 181.3}},
    },
    "交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART": {
        # スペックはユーザー提供（2026-07-16）。機種名のハイフンはU+2010（DB表記に完全一致）
        # bonus_total = 1/(1/BB合算+1/RB合算) を導出。BB合算単独は設定差ほぼ無し(1/299.3→1/295.2)のため不使用
        "source": "user-provided 2026-07-16 (TYPE-ART公式解析値)",
        "tables": {
            "hatsuatari_total": {1: 159.7, 2: 154.8, 3: 151.0, 4: 141.4, 5: 138.1, 6: 133.2},
            "cm": {1: 270.4, 2: 255.7, 3: 239.3, 4: 210.7, 5: 201.2, 6: 188.7},
            "rb_total": {1: 565.0, 2: 546.1, 3: 528.5, 4: 504.1, 5: 496.5, 6: 481.9},
            "bonus_total": {1: 195.7, 2: 192.7, 3: 190.5, 4: 186.7, 5: 185.6, 6: 183.0},
        },
    },
    "交響詩篇エウレカセブン3 HI-EVOLUTION ZERO": {
        # https://1geki.jp/slot/s_eureka3/ 通常時ボーナス（AT中除外）と各種合算
        "source": "https://1geki.jp/slot/s_eureka3/",
        "tables": {
            "bonus_normal": {1: 355.0, 2: 338.6, 3: 319.3, 4: 286.9, 5: 271.6, 6: 223.8},
            "bb_normal": {1: 579.0, 2: 557.0, 3: 517.9, 4: 461.4, 5: 424.5, 6: 327.7},
            "rb_normal": {1: 957.3, 2: 898.1, 3: 865.2, 4: 784.7, 5: 780.4, 6: 728.0},
            "bonus_at_total": {1: 151.1, 2: 143.6, 3: 136.2, 4: 118.5, 5: 110.4, 6: 94.5},
        },
    },
}

# 設定間スプレッド（最高確率/最低確率）がこの値未満の表は判別力不足として不採用
# （例: エウレカTYPE-ARTのbonus_total=1.07、ヴァルヴレイヴ2=1.04 は一様事後がほぼ動かず誤ラベル源になる）
MIN_SPREAD = 1.10


def spec_range(table: dict) -> tuple[float, float, float]:
    """(下限レート, 上限レート, スプレッド) を返す"""
    probs = [1.0 / v for v in table.values()]
    return min(probs), max(probs), max(probs) / min(probs)


def validate_hall(df: pd.DataFrame) -> list[dict]:
    """ホール内の全 (機種, 列, 表) 適合を判定"""
    results = []
    for name, spec in AT_SPECS.items():
        sub = df[(df["machine_name"] == name) & (df["games_normalized"] >= MIN_GAMES)]
        if len(sub) < 100:
            continue
        g = float(sub["games_normalized"].sum())
        for col in ("rb_count", "bb_count"):
            cnt = float(sub[col].sum())
            if cnt <= 0:
                continue
            rate = cnt / g
            for tname, table in spec["tables"].items():
                lo, hi, spread = spec_range(table)
                # 上限は「中央設定の確率」: ホール平均が設4超相当に濃い採用は
                # 別セマンティクスの偶然一致とみなして排除（楽園エウレカbb=cm誤採用の教訓）
                probs_sorted = [1.0 / table[s] for s in sorted(table)]
                mid_p = probs_sorted[len(probs_sorted) // 2]
                ok = (lo * RANGE_LO_MARGIN) <= rate <= min(hi * RANGE_HI_MARGIN, mid_p)
                results.append(
                    {
                        "machine": name,
                        "col": col,
                        "table": tname,
                        "obs": f"1/{g / cnt:.0f}",
                        "range": f"1/{1 / lo:.0f}〜1/{1 / hi:.0f}",
                        "spread": spread,
                        "pass": ok,
                        "n_days": len(sub),
                    }
                )
    return results


def choose_mapping(results: list[dict]) -> dict:
    """機種ごとに採用 (列, 表) を選択（pass かつ spread>=MIN_SPREAD のうちスプレッド最大、rb優先）"""
    chosen = {}
    for r in results:
        if not r["pass"] or r["spread"] < MIN_SPREAD:
            continue
        key = r["machine"]
        cur = chosen.get(key)
        rank = (r["spread"], 1 if r["col"] == "rb_count" else 0)
        if cur is None or rank > (cur["spread"], 1 if cur["col"] == "rb_count" else 0):
            chosen[key] = r
    return chosen


def posterior_high(sub: pd.DataFrame, col: str, table: dict) -> np.ndarray:
    n = sub["games_normalized"].to_numpy(dtype=float)
    k = sub[col].to_numpy(dtype=float)
    settings = sorted(table)
    lls = []
    for s in settings:
        p = 1.0 / table[s]
        lls.append(k * np.log(p) + (n - k) * np.log1p(-p))
    ll = np.vstack(lls)
    ll -= ll.max(axis=0, keepdims=True)
    post = np.exp(ll)
    post /= post.sum(axis=0, keepdims=True)
    hi = [i for i, s in enumerate(settings) if s in HIGH_SETTINGS]
    return post[hi].sum(axis=0)


def build_panel(df: pd.DataFrame, name: str, col: str, table: dict) -> pd.DataFrame:
    sub = df[df["machine_name"] == name].copy()
    sub["evaluable"] = sub["games_normalized"] >= MIN_GAMES
    sub["p_high"] = np.nan
    ev = sub[sub["evaluable"]]
    if len(ev):
        sub.loc[ev.index, "p_high"] = posterior_high(ev, col, table)
    sub["is_high"] = (sub["p_high"] >= P_HIGH_THRESHOLD).fillna(False)
    return sub[["date", "machine_number", "evaluable", "is_high"]]


def fmt_bt(r: dict) -> str:
    carry = r["carry_cond"] / r["carry_base"] if r["carry_base"] else float("nan")
    return (
        f"lift={r['lift']:.2f}x (prec={r['precision']:.3f}/base={r['base_rate']:.3f}) "
        f"的中日={r['hit_ge1']:.1%}(rand {r['rand_hit_ge1']:.1%}) 据置={carry:.2f}x"
    )


def main() -> None:
    for hall, path in HALLS.items():
        df, _ = load_hall(path)
        print(f"\n{'=' * 74}\n[{hall}] セマンティクス適合マトリクス")
        results = validate_hall(df)
        for r in sorted(results, key=lambda x: (x["machine"], x["col"], x["table"])):
            mark = "PASS" if r["pass"] else "fail"
            print(
                f"  {mark} {r['machine'][:20]:20s} {r['col'][:2]} vs {r['table']:11s} "
                f"観測{r['obs']:8s} 範囲{r['range']}"
            )
        chosen = choose_mapping(results)
        if not chosen:
            print("  → 適合機種なし")
            continue
        print(f"[{hall}] 採用マスタとバックテスト:")
        panels = []
        for name, r in chosen.items():
            table = AT_SPECS[name]["tables"][r["table"]]
            panel = build_panel(df, name, r["col"], table)
            panels.append(panel)
            n_daily = panel.groupby("date")["machine_number"].size().mean()
            hi = panel[panel["evaluable"]].groupby("date")["is_high"].sum()
            line = f"  {name[:20]:20s} [{r['col'][:2]}={r['table']}] 設置{n_daily:.0f} 高設定{hi.mean():.2f}台/日"
            if n_daily >= 5:
                line += "  " + fmt_bt(backtest(panel))
            print(line)
        pooled = pd.concat(panels, ignore_index=True)
        n_daily = pooled.groupby("date")["machine_number"].size().mean()
        hi = pooled[pooled["evaluable"]].groupby("date")["is_high"].sum()
        print(
            f"  [プール] 設置{n_daily:.0f} 高設定{hi.mean():.2f}台/日 "
            f"0台の日={(hi == 0).mean():.0%}  " + fmt_bt(backtest(pooled))
        )


if __name__ == "__main__":
    main()
