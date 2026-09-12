#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""小役カウントから設定を推定する（多項分布の尤度）。

台データのスクレイピングでは小役回数が取れないため、この推定は手入力の
実戦記録だけを入力とする。scraper/site777/setting_estimator.py は
ボーナス確率(RB)ベースで別物なので、混同しないこと。

⚠️ 分母は必ずカウント区間の回転数(counted_games)を使う。総回転数を使うと
ボーナス/AT消化分だけ全役のレートが一律に薄まり、結論が反転する。
2026-09-12 の実測では 2322G(総回転) で高設定9.8%、2076G(カウント区間) で
高設定68.3% と逆転した。差はわずか246G。

使い方:
    venv\Scripts\python.exe field/koyaku_setting.py field/sessions/xxx.json
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent
SPECS = BASE / "specs" / "koyaku_specs.json"


def load_specs(path: pathlib.Path = SPECS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def role_probability(machine: dict, role_key: str, setting: int) -> float:
    """役の理論確率。components を合算する。"""
    for role in machine["roles"]:
        if role["key"] != role_key:
            continue
        total = 0.0
        for name, table in role["components"].items():
            denom = table.get(str(setting))
            if denom is None:
                raise ValueError(f"{role_key}/{name} に設定{setting}の値が無い")
            total += 1.0 / float(denom)
        return total
    raise KeyError(f"役 {role_key} がスペックに無い")


def posterior(machine: dict, counts: dict[str, int], games: int) -> dict[int, float]:
    """多項分布（各役 + その他）の尤度から、一様事前の事後確率を出す。"""
    settings = machine["settings"]
    loglik: dict[int, float] = {}
    for s in settings:
        ps = {k: role_probability(machine, k, s) for k in counts}
        p_other = 1.0 - sum(ps.values())
        n_other = games - sum(counts.values())
        if p_other <= 0 or n_other < 0:
            raise ValueError("確率または残り回数が負。counted_games を確認すること")
        ll = sum(counts[k] * math.log(ps[k]) for k in counts)
        ll += n_other * math.log(p_other)
        loglik[s] = ll
    best = max(loglik, key=loglik.get)
    rel = {s: math.exp(loglik[s] - loglik[best]) for s in settings}
    total = sum(rel.values())
    return {s: rel[s] / total for s in settings}


def band(machine: dict, counts: dict[str, int], games: int) -> list[int]:
    """95%信頼区間で否定できない設定（役ごとに見て、1つでも入ればその設定は残る）。"""
    from statsmodels.stats.proportion import proportion_confint

    keep = []
    for s in machine["settings"]:
        ok = True
        for k, n in counts.items():
            lo, hi = proportion_confint(n, games, alpha=0.05, method="wilson")
            if not (lo <= role_probability(machine, k, s) <= hi):
                ok = False
                break
        if ok:
            keep.append(s)
    return keep


def report(session: dict, specs: dict) -> None:
    key = session["machine_key"]
    machine = specs["machines"][key]
    counts = {k: int(v) for k, v in session["counts"].items()}
    games = int(session["counted_games"])
    settings = machine["settings"]

    print(
        f"=== {machine['display_name']}  {session.get('date', '')} "
        f"{session.get('hall', '')} {session.get('machine_number', '')} ==="
    )
    total = session.get("total_games")
    if total:
        print(f"  総回転 {total}G / カウント区間 {games}G （差 {int(total) - games}G はボーナス・AT消化分とみなす）")
    else:
        print(f"  カウント区間 {games}G")
    print("  実測: " + "  ".join(f"{k} 1/{games / v:.2f}({v}回)" for k, v in counts.items()))

    print("\n  理論値と期待回数")
    header = "  設定 " + " ".join(f"{k:>22s}" for k in counts)
    print(header)
    for s in settings:
        cells = []
        for k in counts:
            p = role_probability(machine, k, s)
            cells.append(f"1/{1 / p:7.2f}(期待{p * games:6.1f})")
        print(f"   {s:>2d}  " + " ".join(f"{c:>22s}" for c in cells))

    post = posterior(machine, counts, games)
    low = sum(v for s, v in post.items() if s <= 2)
    high = sum(v for s, v in post.items() if s >= 5)
    print("\n  事後確率（一様事前）")
    for s in settings:
        print(f"    設定{s}: {post[s]:6.1%}")
    print(f"    低設定(1+2)={low:.1%} / 高設定(5+6)={high:.1%}  高低比={high / low if low else float('inf'):.2f}")
    print(f"    最尤 設定{max(post, key=post.get)}")

    b = band(machine, counts, games)
    print(f"\n  否定できない設定（全役の95%CIに入る）: {b if b else '無し'}")
    if len(b) == len(settings):
        print("    ⚠️ 全設定が残っている。回転数が足りず、断定はできない。")

    print("\n  分母への感度（カウント区間が曖昧なときの幅）")
    for d in (-60, -30, 0, +30, +60):
        g = games + d
        if g <= sum(counts.values()):
            continue
        p = posterior(machine, counts, g)
        h = sum(v for s, v in p.items() if s >= 5)
        print(f"    {g}G: " + " ".join(f"設定{s}:{p[s]:5.1%}" for s in settings) + f"   高設定={h:5.1%}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="小役カウントからの設定推定")
    ap.add_argument("session", help="field/sessions/*.json")
    ap.add_argument("--specs", default=str(SPECS))
    args = ap.parse_args(argv)
    session = json.loads(pathlib.Path(args.session).read_text(encoding="utf-8"))
    report(session, load_specs(pathlib.Path(args.specs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
