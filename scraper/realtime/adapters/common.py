"""既存の機種名レジストリを使う変換補助。"""

import re
import unicodedata
from functools import lru_cache

from backtest.model_alias import master_names, resolve_part

_FLOOR = re.compile(r"^\d+F\s*")  # MAXの「1F L…」「2F L/…」の階数表記
_PREFIX = re.compile(r"^(?:LB|L|S|s|e)\s*")
# メーカー型式コード(例: KM, XR, L8)。版数の数字を巻き込まないよう英字1〜3字+数字1桁までに限る。
_VENDOR_CODE = re.compile(r"\s*[A-Z]{1,3}\d?$")


@lru_cache(maxsize=1)
def names() -> list[str]:
    return sorted(master_names())


def _variants(raw: str) -> list[str]:
    text = _FLOOR.sub("", unicodedata.normalize("NFKC", raw).replace("/", " ").strip())
    body = _PREFIX.sub("", text)
    return list(dict.fromkeys(v for v in (raw, text, body, _VENDOR_CODE.sub("", body)) if v))


def model_name(raw: str) -> str | None:
    """候補が一意に決まったときだけ返す。元の表記で照合できなければ、前置詞・型式コードを外して再試行する。"""
    if not raw:
        return None
    for variant in _variants(raw):
        match = resolve_part(variant, names())
        if match["status"] == "ok" and len(match["names"]) == 1:
            return match["names"][0]
    return None
