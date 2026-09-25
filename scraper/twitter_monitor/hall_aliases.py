"""チェーン横断アカウント(999999Q9Qほか)の投稿本文から、対象ホールを推定するためのエイリアス表。

999999Q9Q は店舗名ではなく店長のニックネーム（「ウスイ」「サトウ」「よこやん」等）で
店舗を語る。店長交代（例: 蒲田1はサトウ→よこやん、2026-09-01切替）があるため、
エイリアスには有効期間を持たせる。

なぜ必要か
----------
infer_hall.py の台番号+機種名の数値一致だけでは、対象外ホール（例: マルハン川口店、
サトウ移動後の鷲宮店）の投稿を、たまたま台番号が一致する追跡対象ホールに誤って
割り当てることがある（2026-09-24、ARROW池上店への誤判定=実際はマルハン川口店の
投稿だったケースで発覚）。本文に追跡対象ホールのどのエイリアスも現れない投稿は、
そもそも対象ホールの話ではない可能性が高いので、数値一致の対象から除外する。
"""

from datetime import date

# hall_name -> [(keyword, valid_from, valid_until), ...]
# valid_from/valid_until は None なら無期限。日付は投稿日(posted_at_jst の日付部分)で判定する。
HALL_ALIASES: dict[str, list[tuple[str, date | None, date | None]]] = {
    "マルハンメガシティ2000-蒲田1": [
        ("マルハン蒲田1", None, None),
        ("メガシティ蒲田1", None, None),
        ("メガワン", None, None),
        ("メガいち", None, None),
        # サトウは2026-08-23に蒲田1店長を退任し鷲宮店へ。それ以降の「サトウ」は蒲田1を指さない。
        ("ファンキーサトウ", None, date(2026, 8, 23)),
        ("サトウ", None, date(2026, 8, 23)),
        # よこやんは2026-09-01に蒲田1新店長として就任。
        ("よこやん", date(2026, 9, 1), None),
    ],
    "マルハンメガシティ2000-蒲田7": [
        ("マルハン蒲田7", None, None),
        ("メガシティ蒲田7", None, None),
        ("メガなな", None, None),
        ("GALAXYウスイ", None, None),
        ("ウスイ", None, None),
    ],
    "楽園蒲田店": [
        ("楽園蒲田", None, None),
        ("楽園", None, None),
    ],
    "ヒロキ東口店": [
        ("ヒロキ東口", None, None),
        ("アスロボ7", None, None),
    ],
    "みとや大森町店": [
        ("みとや大森町", None, None),
        ("みとや", None, None),
    ],
    "ARROW池上店": [
        ("ARROW池上", None, None),
    ],
    "レイトギャップ平和島": [
        ("レイトギャップ平和島", None, None),
        ("平和島", None, None),
    ],
    "金時京急蒲田店": [
        ("金時京急蒲田", None, None),
    ],
    "金時蒲田東口店": [
        ("金時蒲田東口", None, None),
    ],
    "ザ-シティ-ベルシティ雑色店": [
        ("ザ-シティ-ベルシティ雑色", None, None),
        ("ベルシティ雑色", None, None),
    ],
}


def plausible_halls(text: str, on_date: date | None) -> set[str]:
    """本文と投稿日から、言及されている可能性のある追跡対象ホールの集合を返す。

    どのエイリアスにも一致しなければ空集合。呼び出し側は、空集合の場合に
    「対象ホール不明として除外する」か「フォールバックする」かを選ぶこと。
    """
    text = text or ""
    result: set[str] = set()
    for hall_name, aliases in HALL_ALIASES.items():
        for keyword, valid_from, valid_until in aliases:
            if keyword not in text:
                continue
            if valid_from is not None and on_date is not None and on_date < valid_from:
                continue
            if valid_until is not None and on_date is not None and on_date > valid_until:
                continue
            result.add(hall_name)
            break
    return result
