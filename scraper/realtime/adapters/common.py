"""既存の機種名レジストリを使う変換補助。"""

from functools import lru_cache

from backtest.model_alias import master_names, resolve_part


@lru_cache(maxsize=1)
def names() -> list[str]:
    return sorted(master_names())


def model_name(raw: str) -> str | None:
    if not raw:
        return None
    match = resolve_part(raw, names())
    return match["names"][0] if match["status"] == "ok" and len(match["names"]) == 1 else None
