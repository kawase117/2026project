"""既存の機種名レジストリを使う変換補助。"""

import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from backtest.model_alias import master_names, resolve_part

_FLOOR = re.compile(r"^\d+F\s*")  # MAXの「1F L…」「2F L/…」の階数表記
_PREFIX = re.compile(r"^(?:LB|L|S|s|e)\s*")
# メーカー型式コード(例: KM, XR, L8)。版数の数字を巻き込まないよう英字1〜3字+数字1桁までに限る。
_VENDOR_CODE = re.compile(r"\s*[A-Z]{1,3}\d?$")


MASTER_CSV = Path(__file__).resolve().parents[3] / "document/machine_master_research/machine_master.csv"


@lru_cache(maxsize=1)
def names() -> list[str]:
    """各ホールDBの機種マスターに、一撃CSV(正本)で登録済みだがホールDBにまだ現れない機種を足す。"""
    found = set(master_names())
    if MASTER_CSV.exists():
        with MASTER_CSV.open(encoding="utf-8-sig", newline="") as stream:
            found.update(r["canonical_machine_name"] for r in csv.DictReader(stream) if r.get("canonical_machine_name"))
    return sorted(found)


def _width_variant(candidates: list[str]) -> str | None:
    """半角・全角だけが違う名前(いざ!番長/いざ！番長)は、全角のほうを採る(ユーザー指定 2026-10-07)。"""
    if len({unicodedata.normalize("NFKC", n) for n in candidates}) != 1:
        return None
    wide = [n for n in candidates if n != unicodedata.normalize("NFKC", n)]
    return wide[0] if len(wide) == 1 else None


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
        if match["status"] == "ambiguous" and (wide := _width_variant(match["names"])):
            return wide
    return None
