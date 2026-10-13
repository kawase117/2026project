"""CI(GitHub Actions)では動かせないテストを、CIだけで skip する。

ローカルでは全て実行される。CI で動かせない理由は次のいずれか:
- db/*.db が .gitignore のためCIに存在しない(実DBを読むテスト)
- NOTION_API_KEY / .env が無い
- 未追跡のローカルファイル(names.json など)に依存する
- CI の Python 3.14 では nodriver が構文エラーで import できない
新しく CI で動かないテストが出たら、ここへ足す前に「本当に実データが要るか」を確認すること。
"""

import os

import pytest

_CI_SKIP = {
    "test/backtest/test_censoring.py": "実DB(db/楽園蒲田店.db)が必要",
    "test/heatmap/test_export_dd_candidates.py": "実DBが必要",
    "test/heatmap/test_kamata7_dual_html.py": "実DB(蒲田7)が必要",
    "test/ml/test_gate_analysis.py": "実DB(蒲田7)が必要",
    "test/ml/test_kamata_corner_mirror_analysis.py": "実DB(蒲田7)が必要",
    "test/scraper/realtime/test_names_and_register.py": "ローカルのnames.json等に依存",
    "test/scraper/test_anaslo_scraper_auto.py": "CIのPython 3.14でnodriverが構文エラー",
    "test/test_event_history.py": "ローカルの台帳・実データに依存",
    "test/test_kamata7_theory_dashboard.py": "実DB(蒲田7)が必要",
    "test/test_notion_exporter.py": "NOTION_API_KEY / .env が必要",
}


def pytest_collection_modifyitems(config, items):
    if not os.environ.get("CI"):
        return
    for item in items:
        path = item.nodeid.split("::")[0]
        reason = _CI_SKIP.get(path)
        if reason:
            item.add_marker(pytest.mark.skip(reason=f"CIでは実行しない: {reason}"))
