"""
Page 14: Notion エクスポーター
クロス分析の 6つの特定組み合わせを
Notion Database に一括保存
"""

import streamlit as st
import pandas as pd
import os
from datetime import datetime

from ..utils.notion_exporter import NotionExporter
from ..utils.data_loader import load_machine_detailed_results
from ..utils.attribute_calculator import get_attr_value
from ..design_system import section_title, premium_divider


# 6つの特定組み合わせの定義
REQUIRED_COMBINATIONS = [
    ("DD別", "機種別"),
    ("DD別", "台番号末尾"),
    ("DD別", "台番号別"),
    ("曜日", "機種別"),
    ("曜日", "台番号末尾"),
    ("曜日", "台番号別"),
]




def _compute_cross_analysis(df_machines, attr1, attr2, min_games, show_low_confidence):
    """
    クロス分析を計算する（page_11 と同じロジック）
    attr1 は削除して、attr2 のみを保持

    Args:
        df_machines: 機械詳細結果データフレーム
        attr1: 第1属性（グループ化に使用）
        attr2: 第2属性（表示用）
        min_games: 最小G数フィルタ
        show_low_confidence: 低G数データも表示するか

    Returns:
        クロス集計結果データフレーム（attr2, total_diff, avg_diff, win_rate, count, avg_games）
    """
    df_cross = df_machines.copy()

    # min_games フィルタを適用（集計前）
    if not show_low_confidence:
        df_cross = df_cross[df_cross['games_normalized'] >= min_games]

    # 属性列を追加（共有関数を使用）
    df_cross['attr1'] = get_attr_value(df_cross, attr1)
    df_cross['attr2'] = get_attr_value(df_cross, attr2)

    # クロス集計
    def agg_win_rate(x):
        return (x > 0).sum() / len(x) * 100

    cross_summary = df_cross.groupby(['attr1', 'attr2']).agg({
        'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
        'games_normalized': 'mean'
    }).round(2)

    cross_summary.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
    cross_summary = cross_summary.reset_index()
    cross_summary = cross_summary.sort_values('total_diff', ascending=False)

    # attr1 を削除（attr2 のみを保持）
    cross_summary = cross_summary.drop(columns=['attr1'])

    return cross_summary


def render():
    """Notion エクスポーター"""
    section_title("📌 Notion へ保存", "クロス分析結果を Notion Database に一括保存")

    # セッション状態を確認
    if "page_14_data" not in st.session_state:
        st.error("セッション情報が失われました。Page 11 から再度操作してください。")
        st.info("操作手順: Page 11 → クロス検索条件を設定 → 「Notion に保存」ボタン")
        st.stop()
    
    page_14_data = st.session_state.page_14_data
    date_range = page_14_data.get("date_range", ("", ""))
    hall_name = st.session_state.hall_name
    
    st.write(f"**ホール**: {hall_name}")
    st.write(f"**期間**: {date_range[0]} 〜 {date_range[1]}")
    
    premium_divider()
    st.markdown("### 📊 保存対象テーブル")
    st.info(f"""
    以下の {len(REQUIRED_COMBINATIONS)} つの組み合わせを Notion Database として保存します：

    💡 **メリット**:
    - ✅ Notionのネイティブテーブル機能が使える
    - ✅ ソート・フィルタ・検索が可能
    - ✅ テーブルが分割されない
    - ✅ 全データが保存される
    """)
    
    # 6つの組み合わせを表示
    cols = st.columns(2)
    for idx, (attr1, attr2) in enumerate(REQUIRED_COMBINATIONS):
        col = cols[idx % 2]
        with col:
            st.markdown(f"✓ {attr1} × {attr2}")
    
    premium_divider()
    
    # タイトル・メモ入力
    st.markdown("### 📝 ページ情報")
    
    col1, col2 = st.columns(2)
    
    with col1:
        title = st.text_input(
            "Notion ページタイトル",
            value=f"クロス分析結果 ({hall_name}) {date_range[0]}",
            placeholder="例: クロス分析結果"
        )
    
    with col2:
        tags = st.text_input(
            "タグ（カンマ区切り）",
            placeholder="例: クロス分析, 検証用, 重要"
        )
    
    memo = st.text_area(
        "メモ",
        placeholder="この分析についてのメモがあれば入力してください",
        height=100
    )
    
    premium_divider()
    
    # 保存ボタン
    if st.button("🚀 Notion に保存", use_container_width=True, type="primary"):
        with st.spinner("📤 Notion に保存中..."):
            try:
                # データを読み込み
                min_games = page_14_data.get("min_games", 0)
                show_low_confidence = page_14_data.get("show_low_confidence", False)
                
                all_machines = load_machine_detailed_results(str(st.session_state.db_path))
                
                # 日付フィルタを適用
                all_machines['date'] = pd.to_datetime(
                    all_machines['date'], format='%Y%m%d'
                )
                
                date_start = pd.to_datetime(date_range[0])
                date_end = pd.to_datetime(date_range[1])
                
                all_machines_filtered = all_machines[
                    (all_machines['date'] >= date_start) &
                    (all_machines['date'] <= date_end)
                ]
                
                if all_machines_filtered.empty:
                    st.error("⚠️ 指定期間にデータがありません")
                else:
                    # 6つの組み合わせを計算
                    tables_dict = {}

                    for attr1, attr2 in REQUIRED_COMBINATIONS:
                        cross_result = _compute_cross_analysis(
                            all_machines_filtered,
                            attr1, attr2,
                            min_games, show_low_confidence
                        )

                        table_name = f"{attr1} × {attr2}"
                        tables_dict[table_name] = cross_result
                    
                    # Notion Database として保存
                    metadata = {
                        "date_range": date_range,
                        "hall_name": hall_name,
                        "title": title,
                        "tags": tags,
                        "memo": memo,
                    }

                    exporter = NotionExporter()
                    success, result = exporter.save_cross_analysis_as_databases(tables_dict, metadata)
                    
                    if success:
                        st.success(f"✅ Notion に保存成功！")
                        st.markdown(f"📄 [Notion ページを開く]({result})")
                    else:
                        st.error(f"❌ 保存失敗: {result}")
            
            except Exception as e:
                st.error(f"❌ エラーが発生しました: {str(e)}")
    
    # .env ファイルの確認
    premium_divider()
    st.markdown("### ⚙️ 設定確認")
    
    if os.getenv("NOTION_API_KEY"):
        st.success("✓ NOTION_API_KEY が設定されています")
    else:
        st.error("✗ NOTION_API_KEY が設定されていません。.env ファイルを確認してください")
    
    if os.getenv("NOTION_DATABASE_ID"):
        st.success("✓ NOTION_DATABASE_ID が設定されています")
    else:
        st.error("✗ NOTION_DATABASE_ID が設定されていません。.env ファイルを確認してください")
