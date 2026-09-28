# -*- coding: utf-8 -*-
"""結果発表・予告に書かれた機種の略称を、実績DBの正式な機種名に当てる。

なぜ要るか
----------
結果発表は「Lカバネリ」「北斗転生」「エウレカART」「からくり2」のような略称で書く。
2026-09-28 に当方3ホールの結果発表の機種名197種類を照合したところ、102種類が当たらず
（「Lハナビ」は別機種の『新ハナビ』に誤って当たっていた）、機種単位の結果発表の
半分近くが答え合わせ表に反映されていなかった。

方針
----
- 表記をそろえてから比べる（NFKC・小文字・空白と記号を除く）。
- 台番号の範囲（1205-1207）と「※」以降の注記は外し、範囲は呼び出し側で台の特定に使う。
- 「真打吉宗+L北斗」のような複数機種は分けて返す。
- 頭の L / S はスマスロ等の区別。候補が複数あるときの絞り込みにだけ使う。
- 決め切れない略称（ALIAS_AMBIGUOUS）は推測で当てない。status='ambiguous' で返す。
- 機種でないもの（【末尾3】・21箇所・8機種・バラエティ等）は status='not_model'。

対応表は document/registry/MODEL_ALIASES.csv（機種マスターの正式名で書く）。
"""

from __future__ import annotations

import csv
import os
import re
import sys
import unicodedata

# 対応表の正本は document/registry/MODEL_ALIASES.csv（alias, official_name, kind, confirmed_by）。
# official_name は機種マスター（各ホールDBの machine_master.machine_name_normalized）の正式名で書く。
# kind=alias は1対1、kind=candidate は同じ略称に複数の候補（その日の設置状況と台番号で決める）。
# 足したら `python -m backtest.model_alias check` で機種マスターに無い名前が無いか確かめること。
ALIASES_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "document", "registry", "MODEL_ALIASES.csv"
)


def load_aliases(path: str = ALIASES_CSV) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """対応表を読む。戻り値は (ALIASES, ALIAS_CANDIDATES)。"""
    aliases: dict[str, list[str]] = {}
    candidates: dict[str, list[str]] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            target = candidates if row.get("kind") == "candidate" else aliases
            target.setdefault(row["alias"], []).append(row["official_name"])
    return aliases, candidates


ALIASES, ALIAS_CANDIDATES = load_aliases()

# 候補も持たない、当てようのない略称（今は無し）。
ALIAS_AMBIGUOUS: set[str] = set()

# 機種ではない行（仕掛けの種類・件数・コーナー名）
# 「バラエティ」は少数台機種のコーナー、「2台設置BT機」は台数のくくりで、どれも機種名ではない（2026-09-28）。
_NOT_MODEL = re.compile(r"^【|箇所|か所|^\d+機種$|^\d+枚$|台設置|台機種|少数台|小数台|^バラエティ|^バラ$|^その他|末尾")

_NUM_RANGE = re.compile(r"(\d{3,4})\s*[-‐－~〜]\s*(\d{3,4})")
# 頭の L/S/e はスマスロ等の記号。直後が日本語か、空白をはさむときだけ記号とみなす
# （「SAO」の S を記号として剥がして 'AO' にしないため）。
_SMART_PREFIX = re.compile(r"^(?:LB|L|S|s|e)(?:\s+|(?=[^\x00-\x7f]))")


def norm(text: str) -> str:
    """比較用に表記をそろえる。"""
    t = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s・!！?？\-‐－~～:：、。'\"&＆()（）\[\]【】☆★♪]+", "", t)


def split_parts(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """1つの機種欄を、機種名の部品と台番号の範囲に分ける。"""
    t = unicodedata.normalize("NFKC", text or "").strip()
    ranges = [(int(a), int(b)) for a, b in _NUM_RANGE.findall(t)]
    t = _NUM_RANGE.sub("", t)
    t = re.split(r"※", t)[0]
    t = re.sub(r"[(（][^)）]*[)）]?", "", t)  # 閉じ括弧の無い「(1211-1213」も落とす
    t = re.sub(r"[×x]\s*\d+$", "", t.strip())
    parts = [p.strip() for p in re.split(r"[+＋/]", t) if p.strip()]
    return parts, ranges


def resolve_part(part: str, names: list[str]) -> dict:
    """機種名の部品1つを、その日の正式名 names に当てる。

    返り値: {"status": "ok"|"ambiguous"|"unmatched"|"not_model", "names": [...], "part": part}
    """
    raw = part.strip()
    if _NOT_MODEL.search(raw):
        return {"status": "not_model", "names": [], "part": raw}
    smart = bool(_SMART_PREFIX.match(raw))
    key = norm(_SMART_PREFIX.sub("", raw, count=1) if smart else raw)
    if key in {norm(a) for a in ALIAS_AMBIGUOUS}:
        return {"status": "ambiguous", "names": [], "part": raw}
    normed = {n: norm(n) for n in names}

    # 候補付きの略称: その日に設置されている候補が1つならそれ。複数なら ambiguous で候補を返し、
    # 台番号で絞るのは resolve() に任せる。
    for alias_key, targets in ALIAS_CANDIDATES.items():
        if norm(alias_key) != key:
            continue
        present = [n for n, v in normed.items() if any(v.startswith(norm(t)) for t in targets)]
        if len(present) == 1:
            return {"status": "ok", "names": present, "part": raw}
        return {"status": "ambiguous", "names": present, "part": raw}

    # 1. 完全一致
    exact = [n for n, v in normed.items() if v == key]
    if len(exact) == 1:
        return {"status": "ok", "names": exact, "part": raw}
    # 2. 対応表（先頭の候補から順に、1つに決まれば採用）
    for alias_key, targets in ALIASES.items():
        if norm(alias_key) != key:
            continue
        for target in targets:
            t = norm(target)
            hits = [n for n, v in normed.items() if v == t] or [n for n, v in normed.items() if v.startswith(t)]
            if len(hits) == 1:
                return {"status": "ok", "names": hits, "part": raw}
            if len(hits) > 1:
                return {"status": "ambiguous", "names": hits, "part": raw}
    # 3a. 末尾が「…」で切れた名前は、その前までで始まる正式名が1つならそれ
    if raw.rstrip().endswith(("…", "...")):
        stem = norm(re.sub(r"(…|\.\.\.)\s*$", "", _SMART_PREFIX.sub("", raw, count=1) if smart else raw))
        starts = [n for n, v in normed.items() if stem and v.startswith(stem)]
        if len(starts) == 1:
            return {"status": "ok", "names": starts, "part": raw}
    # 3b. 部分一致（略称が正式名に含まれる、またはその逆）
    hits = [n for n, v in normed.items() if key and (key in v or v in key)]
    # 本文が正式名を複数含むとき（「スマスロ北斗の拳 転生の章2」は『スマスロ北斗の拳』と
    # 『北斗の拳 転生の章2』の両方を含む）は、いちばん長い＝具体的な正式名を採る。
    contained = [n for n in hits if normed[n] in key]
    if len(contained) > 1:
        longest = max(len(normed[n]) for n in contained)
        top = [n for n in contained if len(normed[n]) == longest]
        if len(top) == 1:
            return {"status": "ok", "names": top, "part": raw}
    if len(hits) > 1 and smart:
        smart_hits = [n for n in hits if "スマスロ" in n or n.startswith("L")]
        hits = smart_hits or hits
    if len(hits) == 1:
        return {"status": "ok", "names": hits, "part": raw}
    if len(hits) > 1:
        return {"status": "ambiguous", "names": hits, "part": raw}
    return {"status": "unmatched", "names": [], "part": raw}


def resolve(
    text: str,
    names: list[str],
    numbers_by_name: dict[str, set[int]] | None = None,
    hint_numbers: set[int] | None = None,
) -> dict:
    """機種欄1つを解決する。

    numbers_by_name: その日の {正式名: 台番号の集合}。
    hint_numbers: 同じ結果発表の画像などから分かっている対象台の台番号。
    候補が複数の略称（とある2 等）は、機種欄の台番号の範囲と hint_numbers のどちらかに
    台番号を持つ機種が1つだけなら、その機種に絞る。

    返り値: {"parts": [resolve_part の結果...], "names": 当たった正式名(重複なし),
             "ranges": [(from,to)...], "unresolved": 当たらなかった部品}
    """
    parts, ranges = split_parts(text)
    results = [resolve_part(p, names) for p in parts]
    wanted = {n for lo, hi in ranges for n in range(min(lo, hi), max(lo, hi) + 1)} | set(hint_numbers or ())
    if numbers_by_name and wanted:
        for r in results:
            if r["status"] == "ambiguous" and r["names"]:
                hit = [n for n in r["names"] if numbers_by_name.get(n, set()) & wanted]
                if len(hit) == 1:
                    r["status"], r["names"] = "ok", hit
    matched = []
    for r in results:
        if r["status"] == "ok":
            for n in r["names"]:
                if n not in matched:
                    matched.append(n)
    return {
        "parts": results,
        "names": matched,
        "ranges": ranges,
        "unresolved": [r for r in results if r["status"] in ("ambiguous", "unmatched")],
    }


def master_names(db_dir: str | None = None) -> set[str]:
    """全ホールDBの machine_master にある正式名（0バイトのダミーDBと analysis_results は除く）。"""
    import glob
    import sqlite3

    db_dir = db_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")
    names: set[str] = set()
    for path in glob.glob(os.path.join(db_dir, "*.db")):
        if os.path.getsize(path) == 0 or "analysis_results" in path:
            continue
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            names.update(r[0] for r in con.execute("select machine_name_normalized from machine_master"))
        except sqlite3.Error:
            continue
    return names


def check_master(path: str = ALIASES_CSV, db_dir: str | None = None) -> list[str]:
    """対応表の正式名のうち、どのホールの機種マスターにも無いものを返す。"""
    master = master_names(db_dir)
    aliases, candidates = load_aliases(path)
    return sorted({n for d in (aliases, candidates) for ns in d.values() for n in ns if n not in master})


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="機種略称の対応表（document/registry/MODEL_ALIASES.csv）の点検と試し引き")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="対応表の正式名が機種マスターにあるか確かめる")
    s = sub.add_parser("resolve", help="略称を機種マスターの正式名に当ててみる")
    s.add_argument("text")
    a = p.parse_args(argv)
    if a.cmd == "check":
        missing = check_master()
        n = sum(len(v) for d in load_aliases() for v in d.values())
        print("対応表 %d 行 / 機種マスターに無い正式名 %d 件" % (n, len(missing)))
        for name in missing:
            print("  " + name)
        return 1 if missing else 0
    r = resolve(a.text, sorted(master_names()))
    print("%s -> %s" % (a.text, r["names"] or "（当たらず）"))
    for u in r["unresolved"]:
        print("  %s: %s %s" % (u["status"], u["part"], u["names"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())


def find_in_text(text: str, names: list[str]) -> list[dict]:
    """自由文（予告ツイート本文など）から、その日・そのホールの機種を正式名で拾う。

    正式名と対応表の略称の両方を探す。長い語から先に当て、当てた部分は消してから次を探す
    （「北斗転生」を「北斗」＝スマスロ北斗の拳 と取り違えない、「新ハナビ」を「ハナビ」と
    取り違えないため）。候補付きの略称（とある2 等）は、設置が1機種のときだけ当てる。

    返り値: [{"machine_name": 正式名, "via": 本文中の語, "match": "official"|"alias"}]（本文の出現順）
    """
    body = norm(text)
    present = {norm(n): n for n in names}
    terms: list[tuple[str, str, str]] = []  # (正規化した語, 正式名, 種類)
    for key, name in present.items():
        terms.append((key, name, "official"))
    for alias, targets in ALIASES.items():
        hits = [present[norm(t)] for t in targets if norm(t) in present]
        if len(hits) == 1 and len(norm(alias)) >= 2:
            terms.append((norm(alias), hits[0], "alias"))
    for alias, targets in ALIAS_CANDIDATES.items():
        hits = [present[norm(t)] for t in targets if norm(t) in present]
        if len(hits) == 1:
            terms.append((norm(alias), hits[0], "alias"))
    terms.sort(key=lambda x: -len(x[0]))
    found: dict[str, dict] = {}
    for term, name, kind in terms:
        pos = body.find(term)
        if pos < 0:
            continue
        body = body[:pos] + "\0" * len(term) + body[pos + len(term) :]
        if name not in found:
            found[name] = {"machine_name": name, "via": term, "match": kind, "pos": pos}
    return [{k: v for k, v in x.items() if k != "pos"} for x in sorted(found.values(), key=lambda x: x["pos"])]


def clean_image_name(text: str) -> str:
    """画像（結果発表の台一覧の画像）から読んだ機種名の飾りを落とす。

    画像の機種名には、頭の L/S（「L/」「L 」も）、「パチスロ」「スロット」、型式の記号
    （「FN」「AD」「/SC2」「/A1」）、末尾の「…」が付く。2026-09-28 の照合で不一致の上位が
    この形（『L 防振り FN』『パチスロ北斗の拳AD…』『L/ヨシムネS/SC2』）だった。
    """
    t = unicodedata.normalize("NFKC", text or "").strip()
    t = re.sub(r"(…|\.\.\.)\s*$", "", t)
    t = re.sub(r"^(?:LB|[LSse])\s*[/／]\s*", "", t)
    # 「/」区切りなら、日本語を含むいちばん長い部分を機種名とみなす
    segs = [s.strip() for s in re.split(r"[/／]", t) if s.strip()]
    if len(segs) > 1:
        jp = [s for s in segs if re.search(r"[^\x00-\x7f]", s)]
        t = max(jp or segs, key=len)
    t = _SMART_PREFIX.sub("", t, count=1)
    t = re.sub(r"^(パチスロ|スロット)\s*", "", t)
    # 型式の記号は空白で区切られて複数付くことがある（「北斗の拳AD XR」「北斗の拳A D」）
    t = re.sub(r"(\s*[A-Z]{1,3}\d?)+$", "", t) if re.search(r"[^\x00-\x7f]", t) else t
    return t.strip()
