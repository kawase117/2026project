"""Convert a Cookie-Editor JSON export to Playwright storage state."""

import argparse
import json
from pathlib import Path

from config import AUTH_STATE_PATH


DEFAULT_INPUT_PATH = AUTH_STATE_PATH.parent / "exported_cookies.json"
ALLOWED_DOMAINS = {".x.com", "x.com", ".twitter.com", "twitter.com"}
SAME_SITE_MAP = {
    "no_restriction": "None",
    "lax": "Lax",
    "strict": "Strict",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cookie-Editor の JSON を Playwright storage_state に変換します。")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help=f"Cookie-Editor の JSON ファイル (default: {DEFAULT_INPUT_PATH})",
    )
    return parser.parse_args()


def convert_cookie(cookie: dict) -> dict:
    same_site = SAME_SITE_MAP.get(cookie.get("sameSite"), "Lax")
    expires = -1 if cookie.get("session") is True or "expirationDate" not in cookie else float(cookie["expirationDate"])

    return {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": cookie["domain"],
        "path": cookie.get("path", "/"),
        "expires": expires,
        "httpOnly": bool(cookie.get("httpOnly", False)),
        "secure": bool(cookie.get("secure", False)),
        "sameSite": same_site,
    }


def main() -> int:
    args = parse_args()
    with args.input.open(encoding="utf-8") as file:
        exported_cookies = json.load(file)

    cookies = [convert_cookie(cookie) for cookie in exported_cookies if cookie.get("domain") in ALLOWED_DOMAINS]

    if not any(cookie["name"] == "auth_token" for cookie in cookies):
        print(
            "エラー: ログインセッションCookie（auth_token）が見つかりません。"
            "Cookie-Editorのエクスポート範囲を確認してください。"
        )
        return 1

    state = {"cookies": cookies, "origins": []}
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUTH_STATE_PATH.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"{len(cookies)}件のCookieを変換し、保存しました: {AUTH_STATE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
