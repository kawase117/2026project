# Scrapling を活用した anaslo-scraper 改良版 - 実装計画

**作成日**: 2026-06-12  
**実装担当**: Codex  
**プランニング**: Claude  

---

## 📋 1. 要件・目的

### 現状の課題
- **nodriver の複雑性**: ブラウザ管理・メモリリークリスク
- **反ボット対策の不足**: Cloudflare Turnstile 等への対応が限定的
- **並行処理の基本性**: pause/resume 機能がない
- **URL 処理の複雑性**: スペース表記揺れ対応に複雑な logic
- **堅牢性**: ページレイアウト変更時の自動復帰がない

### 改良版のゴール
1. **Scrapling の Spider フレームワーク**で並行クロール・pause/resume を実装
2. **StealthyFetcher**で高度な反ボット対策（Cloudflare 等対応）
3. **Selector API**で HTML 解析を統一・最適化（adaptive=True で堅牢化）
4. **既存互換性維持**: JSON 出力形式は anaslo-scraper_multi.py と同じ
5. **9 ホール並行処理**＋メモリ最適化

---

## 🏗️ 2. アーキテクチャ設計

### 2.1 全体構成

```
scraper/
├── anaslo-scraper_multi.py          ← 既存版（保持）
├── anaslo_scrapling.py              ← 新規：Scrapling 改良版（Entry point）
├── scrapling_modules/               ← 新規：Scrapling 専用モジュール
│   ├── __init__.py
│   ├── hall_spider.py               ← メインの Spider クラス定義
│   ├── data_extractor.py            ← Selector ベース HTML 解析
│   ├── session_manager.py           ← StealthySession・proxy 管理
│   └── json_exporter.py             ← JSON 出力（既存互換）
└── tests/
    └── test_scrapling_scraper.py    ← Scrapling 版のテスト
```

### 2.2 処理フロー

```
1. hall_config.json 読み込み（9 ホール設定）
   ↓
2. HallSpider 初期化
   - start_urls = [各ホール一覧ページ]
   - concurrent_requests = 3（per-domain throttling）
   ↓
3. 各ホール × 日付範囲でリクエスト生成
   - StealthySession で反ボット対策
   - クロール進捗を JSON チェックポイントに保存（pause/resume 対応）
   ↓
4. parse() コールバックで HTML 解析
   - Selector API + adaptive=True で堅牢化
   - data_extractor.py で 日付・台番号・成績抽出
   ↓
5. JSON エクスポート
   - 既存 anaslo-scraper_multi.py と同じ形式
   - data/ ディレクトリに保存
```

---

## 📦 3. モジュール設計

### 3.1 `hall_spider.py` — メイン Spider クラス

**責務**:
- Spider フレームワークの初期化
- hall_config.json からの URL 生成
- 一覧ページ・詳細ページの解析callback

**主要メソッド**:
```python
class HallSpider(Spider):
    name = "anaslo_halls"
    concurrent_requests = 3  # ホール別 throttling
    
    def __init__(self, config_path, date_range, use_stealth=True):
        # hall_config.json 読み込み
        # date_range = ("20260601", "20260630")
        
    def configure_sessions(self, manager):
        # StealthySession / DynamicSession 登録
        
    def start_requests(self):
        # 各ホール × 日付の Request 生成
        
    async def parse_list(self, response: Response):
        # 一覧ページ → 詳細ページリンク抽出
        
    async def parse_detail(self, response: Response):
        # 詳細ページ → 台データ抽出 → yield
```

**Scrapling 活用点**:
- `Spider.start(crawldir="./crawl_data")` で pause/resume 対応
- `concurrent_requests` でホール別スロットリング
- `StealthySession` で反ボット対策

---

### 3.2 `data_extractor.py` — HTML 解析・データ抽出

**責務**:
- Selector API で台番号・機種名・成績を抽出
- HTML 構造変更への自動対応（adaptive=True）

**主要メソッド**:
```python
class DataExtractor:
    @staticmethod
    def extract_machines(html_content, date, adaptive=True):
        """Selector で台データを抽出"""
        sel = Selector(html_content)
        machines = []
        for row in sel.css('.data-table tr', adaptive=adaptive):
            machines.append({
                'machine_number': row.css('td.number::text').get(),
                'machine_name': row.css('td.name::text').get(),
                'games': int(row.css('td.games::text').get() or 0),
                'diff_coins': int(row.css('td.diff::text').get() or 0),
            })
        return machines
```

**Scrapling 活用点**:
- `Selector` API で CSS 選択を統一
- `adaptive=True` でページレイアウト変更時の自動追跡

---

### 3.3 `session_manager.py` — セッション・プロキシ管理

**責務**:
- StealthySession / DynamicSession の初期化
- Cloudflare 対応設定
- メモリ最適化（max_pages 制限）

**主要メソッド**:
```python
class HallSessionManager:
    @staticmethod
    def configure(manager, use_stealth=True):
        if use_stealth:
            manager.add("stealth", 
                StealthySession(
                    headless=True,
                    solve_cloudflare=True,  # Cloudflare Turnstile 対応
                    max_pages=5             # ブラウザタブ数制限
                )
            )
```

**Scrapling 活用点**:
- `solve_cloudflare=True` で自動対応
- `max_pages` でメモリリーク防止

---

### 3.4 `json_exporter.py` — JSON 出力（既存互換）

**責務**:
- Spider の yield データを JSON に変換
- 既存版と同じフォーマットで出力

**主要メソッド**:
```python
class JsonExporter:
    @staticmethod
    def export(items, output_dir="data/"):
        """既存互換フォーマットで JSON 出力"""
        for item in items:
            filename = f"{output_dir}/{item['hall_name']}_{item['date']}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(item, f, ensure_ascii=False, indent=2)
```

---

## 🎯 4. 実装フェーズ（優先順位順）

### **Phase 0**: 環境セットアップ
- Scrapling インストール (`pip install "scrapling[fetchers]"`)
- ブラウザ依存関係インストール (`scrapling install`)
- 既存版 JSON 形式の確認

**所要時間**: 15 分

---

### **Phase 1**: 基本 Spider フレームワーク
- `hall_spider.py` 実装（start_requests, parse_list, parse_detail stub）
- `session_manager.py` 実装（StealthySession 登録）
- `anaslo_scrapling.py` 実装（Entry point）

**所要時間**: 2.5-3 時間  
**検証**: URL 生成、セッション初期化の確認

---

### **Phase 2**: HTML 解析・データ抽出
- `data_extractor.py` 実装（Selector で台データ抽出）
- `parse_detail()` callback 充実

**所要時間**: 2-2.5 時間  
**検証**: サンプル HTML で抽出精度確認

---

### **Phase 3**: JSON 互換性・エクスポート
- `json_exporter.py` 実装
- 既存版との出力形式比較テスト

**所要時間**: 1-1.5 時間

---

### **Phase 4**: 反ボット対策・セッション最適化
- `solve_cloudflare=True` 有効化
- メモリ管理（max_pages 調整）
- Cloudflare ページテスト

**所要時間**: 1.5-2 時間

---

### **Phase 5**: Pause/Resume・状態管理
- crawldir チェックポイント確認
- Ctrl+C graceful shutdown テスト

**所要時間**: 1 時間

---

### **Phase 6**: 複数ホール並行処理最適化
- concurrent_requests 最適値調査
- パフォーマンス測定（既存版との比較）

**所要時間**: 1.5-2 時間

---

### **Phase 7**: テスト・ドキュメント
- `test_scrapling_scraper.py` ユニットテスト
- 既存版との統合テスト
- README 作成

**所要時間**: 2-2.5 時間

---

## 📊 5. 依存関係・並行実装可能性

```
Phase 0 (環境) ⇒ Phase 1 (Spider コア)
                    ↓
              Phase 2 (HTML 解析) [依存: Phase 1]
                    ↓
              Phase 3 (JSON 出力) [依存: Phase 2]
                    ↓
              Phase 4 (反ボット対策)
                    ↓
              Phase 5 (Pause/Resume)
                    ↓
              Phase 6 (最適化)
                    ↓
              Phase 7 (テスト・ドキュメント)
```

---

## ⚠️ 6. リスク・代替案

| リスク | 対策 |
|--------|------|
| Scrapling インストール失敗（Windows） | Docker イメージ使用 |
| Cloudflare 対応失敗 | DynamicSession にフォールバック |
| HTML 構造の頻繁な変動 | adaptive=True で自動復帰 |
| メモリリーク（ブラウザ） | max_pages 制限 + gc.collect() |
| 実行時間が既存版より長い | concurrent_requests 調整 |

---

## 🔄 7. 既存との互換性確保

### 出力形式の保証
```json
{
  "date": "20260612",
  "hall_name": "マルハンメガシティ2000-蒲田7",
  "machines": [
    {"number": 1, "name": "機種X", "games": 1000, "diff": 5000}
  ]
}
```

### 段階的移行
- Phase 7 完了まで既存版 (`anaslo-scraper_multi.py`) は保持
- 両者の出力を並行検証
- 差異がなければ本番化

---

## ✅ 8. 検証戦略

### Unit Tests
- HTML 解析精度（複数パターン）
- JSON エクスポート互換性
- URL 生成・フォーマット変換

### Integration Tests
- 実ホール 1 つ × 5 日間のクロール
- JSON 出力 vs 既存版 diff 確認
- メモリ使用量監視

### Performance Tests
- 実行時間比較
- concurrent_requests 最適値測定

---

## 📝 9. 成果物チェックリスト

完了時に以下ファイルが存在すること：

- [ ] `scraper/anaslo_scrapling.py` — Entry point
- [ ] `scraper/scrapling_modules/hall_spider.py` — Spider クラス
- [ ] `scraper/scrapling_modules/data_extractor.py` — HTML 解析
- [ ] `scraper/scrapling_modules/session_manager.py` — セッション管理
- [ ] `scraper/scrapling_modules/json_exporter.py` — JSON 出力
- [ ] `scraper/tests/test_scrapling_scraper.py` — テスト
- [ ] `document/plans/2026-06-12-scrapling-scraper-README.md` — 使用方法

---

## 📌 総所要時間見積もり

| フェーズ | 所要時間 |
|---------|--------|
| Phase 0 | 15 分 |
| Phase 1 | 2.5 時間 |
| Phase 2 | 2.25 時間 |
| Phase 3 | 1.25 時間 |
| Phase 4 | 1.75 時間 |
| Phase 5 | 1 時間 |
| Phase 6 | 1.75 時間 |
| Phase 7 | 2.25 時間 |
| **合計** | **~13-14 時間** |

⚠️ 環境構築トラブル・HTML 構造の予期しない変動で ±2-3 時間の変動可能性

---

## 🎬 開始条件

実装開始前に確認：

1. ✅ Scrapling インストール完了（Phase 0）
2. ✅ 既存版 JSON 形式が文書化
3. ✅ このプランを Codex が確認・承認

