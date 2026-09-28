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

対応表を足すときは、その日の実績DBに実在する正式名で書くこと（部分一致で使う）。
"""

from __future__ import annotations

import re
import unicodedata

# 略称（正規化後）→ 正式名に含まれる文字列（正規化前の表記でよい）。上から順に試す。
ALIASES: dict[str, list[str]] = {
    "北斗転生": ["北斗の拳 転生の章2"],
    "北斗転生2": ["北斗の拳 転生の章2"],
    "北斗": ["スマスロ北斗の拳"],
    "北斗の拳": ["スマスロ北斗の拳"],
    "カバネリ": ["甲鉄城のカバネリ"],
    "カバネリ海門": ["甲鉄城のカバネリ 海門"],
    "エウレカart": ["交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART"],
    "エウレカ": ["交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART"],
    "沖ドキblack": ["沖ドキ!BLACK"],
    "マギレコ": ["マギアレコード"],
    "マギアレコード": ["マギアレコード"],
    "モンハンライズ": ["モンスターハンターライズ"],
    "モンハン": ["モンスターハンターライズ"],
    "東リベ": ["東京リベンジャーズ"],
    "キンハナ": ["キングハナハナ-30"],
    "キングハナハナ": ["キングハナハナ-30"],
    "ニューキンハナ": ["ニューキングハナハナV‐30"],
    "真打吉宗": ["真打 吉宗"],
    "戦国乙女5": ["戦国乙女5"],
    "乙女5": ["戦国乙女5"],
    "ハナビ": ["スマスロ ハナビ"],
    "ヴヴヴ2": ["革命機ヴァルヴレイヴ2"],
    "ヴァルヴレイヴ2": ["革命機ヴァルヴレイヴ2"],
    "ヴヴヴ": ["革命機ヴァルヴレイヴ"],
    "戦コレ6": ["戦国コレクション6"],
    "ミリオンゴッド": ["ミリオンゴッド‐神々の軌跡‐"],
    "ジャグガ": ["ジャグラーガールズ"],
    "からくり2": ["からくりサーカス2"],
    "からくり": ["からくりサーカス"],
    "ワルダイ": ["ワールドダイスター"],
    "sao": ["ソードアート・オンライン"],
    "sao2": ["ソードアート・オンラインII"],
    "鏡": ["HEY！エリートサラリーマン鏡"],
    "バジ絆2天膳": ["バジリスク～甲賀忍法帖～絆2 天膳"],
    "絆2天膳": ["バジリスク～甲賀忍法帖～絆2 天膳"],
    "バジリスク絆2天膳": ["バジリスク～甲賀忍法帖～絆2 天膳"],
    "サンダーv": ["スマスロ サンダーV"],
    "マイジャグv": ["マイジャグラーV"],
    "マイジャグ": ["マイジャグラーV"],
    "ゴージャグ3": ["ゴーゴージャグラー3"],
    "ハピジャグ": ["ハッピージャグラーVIII"],
    "ファンキー2": ["ファンキージャグラー2"],
    "ネオアイム": ["ネオアイムジャグラーEX"],
    "アイム": ["ネオアイムジャグラーEX"],
    "花の慶次": ["花の慶次～佐渡攻めの章～"],
    "慶次佐渡": ["花の慶次～佐渡攻めの章～"],
    "慶次": ["花の慶次～佐渡攻めの章～"],
    "とんスキ": ["とんでもスキルで異世界放浪メシ"],
    "とんでもスキル": ["とんでもスキルで異世界放浪メシ"],
    "炎炎2": ["スマスロ炎炎ノ消防隊2"],
    "炎炎": ["スマスロ炎炎ノ消防隊"],
    "バイオre3": ["バイオハザード RE:3"],
    "バイオ5": ["バイオハザード5"],
    "防振り": ["痛いのは嫌なので防御力に極振り"],
    "クラクレ": ["クランキークレスト"],
    "いざ番長": ["いざ！番長"],
    "バーディーウィング": ["BIRDIE WING"],
    "アズレン": ["アズールレーン"],
    "シェイク": ["SHAKE BONUS TRIGGER"],
    "邪神ちゃん": ["邪神ちゃんドロップキック"],
    "アレックス": ["アレックス ブライト"],
    "ダンまち2": ["ダンジョンに出会いを求めるのは間違っているだろうか2"],
    "かぐや様": ["かぐや様は告らせたい"],
    "このすば": ["この素晴らしい世界に祝福を！"],
    "reゼロ2": ["Re:ゼロから始める異世界生活 season2"],
    "スタァライト": ["少女☆歌劇 レヴュースタァライト"],
    "スト6": ["ストリートファイター6"],
    "やじきた参": ["やじきた道中記参る"],
    "やじきた": ["やじきた道中記参る"],
    "かのかり": ["彼女、お借りします"],
    "god": ["ミリオンゴッド‐神々の軌跡‐"],
    "化物語": ["化物語"],
    "モンキーv": ["モンキーターンV"],
    "モンキー": ["モンキーターンV"],
    "東京喰種": ["東京喰種"],
    "喰種": ["東京喰種"],
    "リゼロ2": ["Re:ゼロから始める異世界生活 season2"],
    "青ブタ": ["青春ブタ野郎"],
    "ゾンサガ": ["ゾンビランドサガ"],
    "東リべ": ["東京リベンジャーズ"],  # ひらがなの「べ」で書かれることがある
    "ハッピーviii": ["ハッピージャグラーVIII"],
    "ハッピーv": ["ハッピージャグラーVIII"],
    "ゴジエヴァ": ["ゴジラ対エヴァンゲリオン"],
    "サラ金": ["サラリーマン金太郎"],
    "birdiewing": ["BIRDIE WING"],
}

ALIASES["ガールズ"] = ["ジャグラーガールズ"]  # 2026-09-28 ユーザー確認: 基本的にジャグラーガールズ

# 名前だけでは決め切れない略称 → 候補。その日の設置状況と台番号で決める（resolve の numbers_by_name）。
#   とある2 … 禁書目録2／超電磁砲2（2026-09-28 ユーザー: 言葉だけでは判別できないが、その日の台番号で判断できる）
ALIAS_CANDIDATES: dict[str, list[str]] = {
    "とある2": ["とある魔術の禁書目録2", "とある科学の超電磁砲2"],
}

# 候補も持たない、当てようのない略称（今は無し）。
ALIAS_AMBIGUOUS: set[str] = set()

# 機種ではない行（仕掛けの種類・件数・コーナー名）
_NOT_MODEL = re.compile(r"^【|箇所|か所|^\d+機種$|^\d+枚$|台設置|^バラエティ$|^バラ$|^その他$|末尾")

_NUM_RANGE = re.compile(r"(\d{3,4})\s*[-‐－~〜]\s*(\d{3,4})")
# 頭の L/S/e はスマスロ等の記号。直後が日本語か、空白をはさむときだけ記号とみなす
# （「SAO」の S を記号として剥がして 'AO' にしないため）。
_SMART_PREFIX = re.compile(r"^(?:L|S|s|e)(?:\s+|(?=[^\x00-\x7f]))")


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
    # 3. 部分一致（略称が正式名に含まれる、またはその逆）
    hits = [n for n, v in normed.items() if key and (key in v or v in key)]
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
