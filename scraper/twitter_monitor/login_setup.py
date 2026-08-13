"""One-time, manually operated X login setup for the monitoring pipeline.
この手動Playwrightログイン方式はXの自動化検知によるログイン制限が発生するため、import_cookies.pyの使用を推奨します。"""

from playwright.sync_api import sync_playwright

from config import AUTH_STATE_PATH


def main() -> None:
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://x.com/login", wait_until="domcontentloaded")
        input("X へのログイン完了後、Enter を押してください: ")
        context.storage_state(path=str(AUTH_STATE_PATH))
        print(f"ログイン状態を保存しました: {AUTH_STATE_PATH}")
        browser.close()


if __name__ == "__main__":
    main()
