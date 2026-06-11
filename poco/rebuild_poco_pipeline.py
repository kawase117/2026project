"""
Poco データ全期間再構築パイプライン
対応フォーマット:
  Format A (7〜1月): CSV形式
  Format B (2〜4月): Markdownテーブル形式
  Format C (5月〜): 3行1セット形式

実行方法（プロジェクトルートから）:
  python poco/rebuild_poco_pipeline.py

出力:
  docs/poco/poco_data_extracted_full.csv  抽出結果（全期間）
  docs/poco/poco_data_v4.csv              weekday_strategy + full_half 分離
  docs/poco/poco_data_v5.csv              正規化済み
  docs/poco/poco_unmapped_machines.csv    マッピング未対応機種一覧
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import re
import sqlite3
import pandas as pd
from pathlib import Path

# プロジェクトルート（このスクリプトは poco/ に置くが、
# python poco/rebuild_poco_pipeline.py で実行するため CWD = project root）
BASE = Path(".")
POCO_DIR = BASE / "docs" / "ぽこデータ抽出"
MAP_FILE = BASE / "docs" / "poco" / "poco_machine_mapping_TRULY_FINAL.csv"
DB_K7 = BASE / "db" / "マルハンメガシティ2000-蒲田7.db"
DB_K1 = BASE / "db" / "マルハンメガシティ2000-蒲田1.db"
OUT_DIR = BASE / "docs" / "poco"  # 出力先

MONTH_MAP = {
    "7月":  (2025, 7),  "8月":  (2025, 8),  "9月":  (2025, 9),
    "10月": (2025, 10), "11月": (2025, 11), "12月": (2025, 12),
    "1月":  (2026, 1),  "2月":  (2026, 2),  "3月":  (2026, 3),
    "4月":  (2026, 4),  "5月":  (2026, 5),
}

EVENT_DAY_SET = {1, 7, 11, 17, 21, 22, 27, 30, 31}
GRAND_OPENING_DATES = {"20250707", "20250708", "20250709", "20250710", "20250711"}
COLOR_MACHINES = {'スーパービンゴネオ', 'ネオプラネット', 'チバリヨ2プラス'}

# ============================================================
# 1. 抽出（フォーマット別）
# ============================================================
def detect_format(content: str, month_num: int) -> str:
    if month_num == 5:
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        date_only = sum(1 for l in lines if re.match(r'^\d+日', l) and '/' not in l and '|' not in l)
        if date_only > 5:
            return 'C'
    if '|' in content and '**' in content:
        return 'B'
    return 'A'

def parse_diff_content(cell: str):
    cell = re.sub(r'\*\*', '', cell).strip().strip('|').strip()
    if not cell or cell == '-':
        return None, ''
    m = re.match(r'^([+\-]?[\d,]+)\s*/\s*(.*)$', cell)
    if m:
        try:
            diff = int(m.group(1).replace(',', '').replace('+', ''))
            return diff, m.group(2).strip()
        except:
            return None, m.group(2).strip()
    return None, cell

def parse_format_a(text: str, year: int, month: int) -> list:
    records = []
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if i <= 1:
            continue
        parts = []
        in_q = False
        cur = ""
        for ch in line:
            if ch == '"':
                in_q = not in_q
                cur += ch
            elif ch == ',' and not in_q:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        if cur:
            parts.append(cur)
        if len(parts) < 2:
            continue
        dm = re.match(r'(\d+)日', parts[0])
        if not dm:
            continue
        day = int(dm.group(1))
        try:
            date_str = f"{year:04d}{month:02d}{day:02d}"
            def to_num(s):
                s = s.strip().strip('"')
                if not s or s == '-':
                    return None
                try:
                    return int(s.replace('+', '').replace(',', '').replace('"', ''))
                except:
                    return None
            d7 = to_num(parts[1]) if len(parts) > 1 else None
            c7 = parts[2].strip().strip('"') if len(parts) > 2 else ''
            d1 = to_num(parts[3]) if len(parts) > 3 else None
            c1 = parts[4].strip().strip('"') if len(parts) > 4 else ''
            if c7 and re.fullmatch(r'[\d,]+', c7):
                c7 = ''
            if c1 and re.fullmatch(r'[\d,]+', c1):
                c1 = ''
            records.append((date_str, year, month, day, d7, c7, d1, c1))
        except:
            continue
    return records

def parse_format_b(text: str, year: int, month: int) -> list:
    records = []
    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith('|'):
            continue
        if re.match(r'\|\s*[-:]+', line):
            continue
        cells = [c.strip() for c in line.split('|')]
        cells = [c for c in cells if c]
        if len(cells) < 3:
            continue
        date_cell = re.sub(r'\*\*', '', cells[0]).strip()
        dm = re.match(r'(\d+)日', date_cell)
        if not dm:
            continue
        day = int(dm.group(1))
        try:
            date_str = f"{year:04d}{month:02d}{day:02d}"
            d7, c7 = parse_diff_content(cells[1])
            d1, c1 = parse_diff_content(cells[2]) if len(cells) > 2 else (None, '')
            records.append((date_str, year, month, day, d7, c7, d1, c1))
        except:
            continue
    return records

def parse_format_c(text: str, year: int, month: int) -> list:
    records = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    start = next((i for i, l in enumerate(lines) if re.match(r'^\d+日', l)), 0)
    i = start
    while i < len(lines):
        if not re.match(r'^\d+日', lines[i]):
            i += 1
            continue
        dm = re.match(r'(\d+)日', lines[i])
        day = int(dm.group(1))
        date_str = f"{year:04d}{month:02d}{day:02d}"
        c7_raw = lines[i+1] if i+1 < len(lines) and not re.match(r'^\d+日', lines[i+1]) else ''
        c1_raw = lines[i+2] if i+2 < len(lines) and not re.match(r'^\d+日', lines[i+2]) else ''
        d7, c7 = parse_diff_content(c7_raw)
        d1, c1 = parse_diff_content(c1_raw)
        records.append((date_str, year, month, day, d7, c7, d1, c1))
        i += 3
    return records

# 全ファイル処理
print("=" * 70)
print("Step 1: データ抽出")
print("=" * 70)
all_records = []
for f in sorted(POCO_DIR.glob("*.md")):
    ms = re.search(r'^(\d+月)', f.stem)
    if not ms or ms.group(1) not in MONTH_MAP:
        continue
    month_key = ms.group(1)
    year, month = MONTH_MAP[month_key]
    text = f.read_text(encoding='utf-8')
    fmt = detect_format(text, month)
    recs = (parse_format_a if fmt == 'A' else parse_format_b if fmt == 'B' else parse_format_c)(text, year, month)
    print(f"  {f.name}: Format {fmt} -> {len(recs)}件")
    all_records.extend(recs)

cols = ['date','year','month','day','kamata7_diff','kamata7_content','kamata1_diff','kamata1_content']
df_ext = pd.DataFrame(all_records, columns=cols).sort_values('date').reset_index(drop=True)
df_ext.to_csv(OUT_DIR / "poco_data_extracted_full.csv", index=False, encoding='utf-8')
print(f"\n抽出完了: {len(df_ext)}行 / {df_ext['date'].min()} ~ {df_ext['date'].max()}")

# ============================================================
# 2. v4 変換（weekday_strategy + full_half 分離）
# ============================================================
print("\n" + "=" * 70)
print("Step 2: weekday_strategy / full_half 分離")
print("=" * 70)

def calc_is_event_day(date_str: str) -> int:
    try:
        m, d = int(date_str[4:6]), int(date_str[6:8])
        return int((d in EVENT_DAY_SET) or (m == d))
    except:
        return 0

def protect_brackets(s: str) -> str:
    """括弧内の読点をプレースホルダーに置き換えて分割保護"""
    result = []
    depth = 0
    for ch in s:
        if ch in '(（':
            depth += 1
        elif ch in ')）':
            depth -= 1
        if ch == '、' and depth > 0:
            result.append('\x00')  # NULL文字でプレースホルダー
        else:
            result.append(ch)
    return ''.join(result)

def clean_full_half(text: str) -> str:
    for marker in ['貫通→', '全→', '発表→']:
        if text.startswith(marker):
            text = text[len(marker):]
            break
    # ？をセパレータとして扱う（例: ヴヴヴ2？からくり？ → ヴヴヴ2、からくり）
    text = text.replace('？', '、')
    # 括弧内の「、」を保護してから分割
    text = protect_brackets(text)
    parts_raw = text.split('、')
    cleaned = []
    for p in parts_raw:
        p = p.replace('\x00', '、').strip()  # プレースホルダーを戻す
        if not p:
            continue
        if re.match(r'^メガ仕掛け→', p):
            continue
        if p in ('他多数', '他多数ニブ', '他多数ニブ以上', '他多数ニブ以上あり'):
            continue
        if re.fullmatch(r'[\d,]+', p):
            continue
        if re.search(r'全台系|末尾ルーレット|全台', p) and len(p) < 10:
            continue
        # ニブ→ / 高配分→ / ニブイチ→ 除去
        p = re.sub(r'^(ニブ→|ニブイチ→|ニブ以上→|高配分→|ニブ)', '', p).strip()
        # 括弧内の機種展開
        bracket = re.search(r'[(（](.+?)[)）]', p)
        if bracket:
            inner = bracket.group(1)
            for m2 in re.split(r'[、,]', inner):
                m2 = m2.strip()
                if m2:
                    cleaned.append(m2)
            continue
        p = re.sub(r'全$', '', p).strip()
        p = p.replace('？', '').strip()
        if not p or re.fullmatch(r'[\d,]+', p):
            continue
        cleaned.append(p)
    return '、'.join(cleaned)

def parse_content(content: str):
    if not content or pd.isna(content):
        return '', ''
    s = str(content).strip()
    if not s or s == '？':
        return '', ''
    if s.startswith('貫通→') or s.startswith('全→') or s.startswith('発表→'):
        return '', clean_full_half(s)
    # スプリット検索
    split_pos = -1
    split_len = 0
    for sep in ['、', '：']:
        for mk in ['全→', '発表→', '貫通→']:
            pos = s.find(sep + mk)
            if pos != -1 and (split_pos == -1 or pos < split_pos):
                split_pos = pos
                split_len = len(sep)
    if split_pos == -1:
        return s, ''
    return s[:split_pos].strip(), clean_full_half(s[split_pos + split_len:].strip())

df_v4 = df_ext.copy()
df_v4['source'] = 'poco'
df_v4['is_event_day'] = df_v4['date'].apply(calc_is_event_day)
df_v4['is_grand_opening'] = df_v4['date'].isin(GRAND_OPENING_DATES).astype(int)

for hall in ['kamata7', 'kamata1']:
    ws_list, fh_list = [], []
    for _, row in df_v4.iterrows():
        ws, fh = parse_content(row[f'{hall}_content'])
        ws_list.append(ws)
        fh_list.append(fh)
    df_v4[f'{hall}_weekday_strategy'] = ws_list
    df_v4[f'{hall}_full_half'] = fh_list

cols_v4 = ['date','year','month','day','source','is_event_day','is_grand_opening',
           'kamata7_diff','kamata7_weekday_strategy','kamata7_full_half',
           'kamata1_diff','kamata1_weekday_strategy','kamata1_full_half',
           'kamata7_content','kamata1_content']
df_v4 = df_v4[cols_v4]
df_v4.to_csv(OUT_DIR / "poco_data_v4.csv", index=False, encoding='utf-8')

k7_fh = (df_v4['kamata7_full_half'] != '').sum()
k1_fh = (df_v4['kamata1_full_half'] != '').sum()
print(f"K7 full_half: {k7_fh}日 / K1 full_half: {k1_fh}日")

# ============================================================
# 3. v5 正規化
# ============================================================
print("\n" + "=" * 70)
print("Step 3: 機種名正規化")
print("=" * 70)

map_df = pd.read_csv(MAP_FILE, encoding='utf-8-sig')
mapping = {}
for _, row in map_df.iterrows():
    key = str(row['poco_machine']).strip()
    status = str(row['status']).strip()
    db_match = str(row['db_match']).strip() if pd.notna(row['db_match']) else ''
    mapping[key] = (status, db_match)

# 追加パッチ（既存マッピング誤り修正 + 2月〜5月の新出略称 + 新台対応）
PATCH_FOUND = {
    # ===== 既存マッピングの誤り修正（DB正式名への上書き）=====
    'GE':         'ゴッドイーター リザレクション',
    'マギレコ':    'マギアレコード 魔法少女まどか☆マギカ外伝',
    'ガルパン':    'ガールズ&パンツァー 最終章',
    'ガールズ':    'ガールズ&パンツァー 最終章',
    '防振り':     '痛いのは嫌なので防御力に極振りしたいと思います。',
    'ななつま':    '七つの魔剣が支配する',
    '7つの魔剣':  '七つの魔剣が支配する',
    'Sこのすば':   'この素晴らしい世界に祝福を！',  # DB照合: 旧版が実稼働

    # ===== 2月〜5月の新出略称（新台含む）=====
    '新鬼3':      '新鬼武者3',
    '北斗転生':    '北斗の拳 転生の章2',
    'Lカバネリ':   '甲鉄城のカバネリ 海門(うなと)決戦',
    'Sカバネリ':   '甲鉄城のカバネリ',
    'L炎炎2':     'スマスロ炎炎ノ消防隊2',
    'ステライト':  '少女☆歌劇 レヴュースタァライト ‐The SLOT‐',
    'ヴヴヴ2他':   '革命機ヴァルヴレイヴ2',
    'ヴヴ2':      '革命機ヴァルヴレイヴ2',
    'ヴヴヴ2':     '革命機ヴァルヴレイヴ2',
    'ヴヴヴ':      '革命機ヴァルヴレイヴ',
    '初代ヴヴヴ':  '革命機ヴァルヴレイヴ',
    'モンハン':    'モンスターハンターライズ',
    'モンハンライズ': 'モンスターハンターライズ',
    'DMC5':       'デビル メイ クライ5 スタイリッシュトライブ',
    'ゴージャグ3': 'ゴーゴージャグラー3',
    'ゴージャグ':  'ゴーゴージャグラー3',
    '旧北斗':     '北斗の拳 転生の章2',
    'Lハナビ':    'スマスロ ハナビ',
    'ヨルムンガンド': 'ヨルムンガンド',
    'うみねこ':   'うみねこのなく頃に2',
    'ネオアイム':  'ネオアイムジャグラーEX',
    'キンハナ':   'キングハナハナ-30',
    'キンハナ30':  'キングハナハナ-30',
    '天膳':       'バジリスク～甲賀忍法帖～絆2 天膳 BLACK EDITION',
    'ファンキー':  'ファンキージャグラー2',
    '炎炎2':      'スマスロ炎炎ノ消防隊2',
    'L炎炎':      'スマスロ炎炎ノ消防隊',   # L=スマスロプレフィックス
    'S炎炎':      '炎炎ノ消防隊',           # S=旧タイプ
    'ハッピー':   'ハッピージャグラーVIII',
    'ハッピーVIII': 'ハッピージャグラーVIII',   # 8にまつわる機種(...)の内部展開
    'ハッピーⅧ':  'ハッピージャグラーVIII',   # Unicode Ⅷ表記
    'マジハロ8':  'マジカルハロウィン8',       # 8にまつわる機種(...)の内部展開
    '鉄拳5':      '鉄拳6',                   # DB照合: 報告日に鉄拳6が稼働（報告誤記と判断）
    'ミスター':   'ミスタージャグラー',
    'バーサス':   'バーサスリヴァイズ',
    'からくり':   'からくりサーカス',
    'アズレン':   'アズールレーン THE ANIMATION',

    # ===== DBにあるが略称がサブストリングマッチしない機種 =====
    '攻殻機動隊':   '攻殻機動隊',
    '刃牙':        '範馬刃牙',
    'サンダー':    'スマスロ サンダーV',
    'ウルミラ':    'ウルトラミラクルジャグラー',
    'ダリフラ':    'ダーリン・イン・ザ・フランキス',
    'ゾンサガ':    'ゾンビランドサガ',
    '東リベ':      '東京リベンジャーズ',
    'エウレカ':    '交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART',
    '禁書目録':    'とある魔術の禁書目録',
    '超電磁砲2':   'とある科学の超電磁砲2',
    '無職転生':    '無職転生 ～異世界行ったら本気だす～',
    '秘宝伝':      'スマスロ秘宝伝',
    '乙女4':       '戦国乙女4 戦乱に閃く炯眼の軍師',
    'シャーマン':  'シャーマンキング',
    'かぐや様':    'かぐや様は告らせたい',
    'マイジャグ':  'マイジャグラーV',
    '銭形5':      '主役は銭形5',
    'ゴブスレ':    'ゴブリンスレイヤーII',
    'ゴブリンスレイヤー': 'ゴブリンスレイヤーII',

    # ===== OCRミス・誤記の訂正 =====
    'ミク':       'ミリオンゴッド‐神々の軌跡‐',  # OCRミス: ミリゴ→ミク と誤認識

    # ===== マッピングファイルdb_matchが誤っているpoco機種名を直接上書き =====
    'エヴァBT':   'ヱヴァンゲリヲン ～約束の扉～',
    'クレアBT':   'クレアの秘宝伝 ～はじまりの扉と太陽の石～ ボーナストリガーver.',
    'エウレカART': '交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART',
    '緋弾ドン':   '緑ドン VIVA!情熱南米編 REVIVAL',
    'ドラハナ':   'スマート沖スロ ドラゴンハナハナ～閃光～',

}
# ===== 複合戦略機種（PARTIAL = パイプ区切りで複数機種に展開） =====
# PATCH_FOUND は FOUND ステータスで登録されるため、パイプ区切りを分割できない。
# 2機種以上に展開が必要な場合は PATCH_FOUND ではなく下部で直接 PARTIAL として設定する。
PATCH_DELETE = {
    '不明', '他多数', '他機種', '多数',
    '仕掛け→末尾7', '仕掛け→末尾1', '仕掛け→末尾0',
    '仕掛け→末尾ゾロ目', '仕掛け→ヴヴヴ2',
    '創業日・ゾロ目', '他サミー系多数', 'ゾロ目他',
    'モンキーロング島',
    '1列ピックアップ→ハナ横の壁1列',
    'SAOスタアライト',
    '3にまつわる機種(3台設置', 'キンハナ30等多数)', '番長4)',
    '4にまつわる機種(戦国乙女4', '8にまつわる機種(8台設置', 'マジハロ8)',
    '2にまつわる機種（ヴヴ2', '天膳他多数）',
    'かぐらり他多数',
    '末尾ゾロ目他', '3〜7台設置機種',
    # 削除した誤分類項目（2026-06-03修正）:
    # 'ゾンサガ等' → ゾンビランドサガは機種名（PATCH_FOUNDで対応）
    # 'カイジ等' → 回胴黙示録カイジ 狂宴は機種名（PATCH_FOUNDで対応）
    # 'ハッピー他' → ハッピージャグラーは機種名（PATCH_FOUNDで対応）
    # 'ハナハナ天膳' → 当日稼働ハナハナ機種全+天膳全（複合戦略）
}
# 貫通→機種名 形式を直接マップ
mapping['貫通→戦国乙女'] = ('FOUND', '戦国乙女4 戦乱に閃く炯眼の軍師')
for k, v in PATCH_FOUND.items():
    mapping[k] = ('FOUND', v)
for k in PATCH_DELETE:
    mapping[k] = ('DELETE', '')

# 複合戦略機種: PARTIAL ステータスでパイプ区切りを2機種に展開
# ハナハナ天膳 = ハナハナ全台（キングハナハナ-30）+ 天膳全台（バジリスク天膳）
mapping['ハナハナ天膳'] = ('PARTIAL', 'キングハナハナ-30|バジリスク～甲賀忍法帖～絆2 天膳 BLACK EDITION')

def get_all_db_machines(db_path):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT DISTINCT machine_name FROM daily_machine_type_summary", conn)
    conn.close()
    return df['machine_name'].tolist()

k7_db = get_all_db_machines(DB_K7)
k1_db = get_all_db_machines(DB_K1)

def get_dynamic_machines(date_str, hall, spec_name):
    # 「X台設置機種」「X台設置」「X台以下設置機種」すべてに対応
    m = re.match(r'^(\d+)台(以下)?設置', spec_name)
    if not m:
        return []
    count = int(m.group(1))
    op = '<=' if m.group(2) else '='
    db_path = str(DB_K7 if hall == 'kamata7' else DB_K1)
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(
            f"SELECT machine_name FROM daily_machine_type_summary WHERE date=? AND machine_count {op} ?",
            conn, params=[date_str, count])
        conn.close()
        return df['machine_name'].tolist()
    except:
        return []

unmapped = {}
deleted_log = {}  # DELETEされた項目を追跡（監査用）

def norm_one(name: str, date_str: str, hall: str) -> list:
    name = name.strip()
    if not name:
        return []
    if re.match(r'^\d+台(以下)?設置', name):
        return get_dynamic_machines(date_str, hall, name)
    if name in mapping:
        status, db_match = mapping[name]
        if status in ('DELETE', 'WEEKDAY_STRATEGY', 'MACHINE_SPECIFICATION', 'DYNAMIC_FILTER'):
            deleted_log[name] = deleted_log.get(name, 0) + 1  # 削除を記録
            return []
        if status in ('FOUND', 'OK'):
            return [db_match] if db_match else []
        if status == 'PARTIAL':
            candidates = [c.strip() for c in db_match.split('|') if c.strip()]
            return candidates
        if status == 'MULTIPLE_MACHINES':
            # db_matchが「[複数機種] A / B / C」形式の場合を処理
            cleaned = re.sub(r'^\[複数機種[^\]]*\]\s*', '', db_match).strip()
            if cleaned:
                candidates = [c.strip() for c in re.split(r'\s*/\s*|\|', cleaned) if c.strip()]
                return candidates
            return []
        if status == 'NOT FOUND':
            unmapped[name] = unmapped.get(name, 0) + 1
            return []
    # 全→ / 発表→ / 貫通→ プレフィックスを個別パーツでも除去
    for pfx in ['全→', '発表→', '貫通→']:
        if name.startswith(pfx):
            name = name[len(pfx):]
            if name in mapping:
                status, db_match = mapping[name]
                if status in ('FOUND', 'OK', 'PARTIAL'):
                    return [c.strip() for c in db_match.split('|') if c.strip()][:1]
            break

    # 「他」系サフィックス除去（機種名他、機種名他多数 など）
    cleaned_other = re.sub(r'(他多数?|等多数?|等|など|他)$', '', name).strip()
    if cleaned_other != name and cleaned_other:
        if cleaned_other in mapping:
            status, db_match = mapping[cleaned_other]
            if status in ('FOUND', 'OK', 'PARTIAL'):
                return [c.strip() for c in db_match.split('|') if c.strip()][:1]
        name = cleaned_other  # 以降の処理のため更新

    # プレフィックス除去後に再マッチ
    clean = re.sub(r'^(ニブ→|ニブイチ→|ニブ以上→|高配分→)', '', name).strip()
    # 高配分サフィックスも処理 (例: モンキー高配分 → モンキー)
    if clean == name:
        clean = re.sub(r'高配分$', '', name).strip()
    if clean != name and clean in mapping:
        status, db_match = mapping[clean]
        if status in ('FOUND', 'OK', 'PARTIAL'):
            candidates = [c.strip() for c in db_match.split('|') if c.strip()]
            return candidates[:1] if candidates else []
    # DB部分一致
    db_list = k7_db if hall == 'kamata7' else k1_db
    for src in [name, clean]:
        if not src:
            continue
        matched = [m for m in db_list if src in m or m in src]
        if len(matched) == 1:
            return matched
        if len(matched) > 1:
            matched.sort(key=lambda x: abs(len(x) - len(src)))
            return matched[:1]
    unmapped[name] = unmapped.get(name, 0) + 1
    return []

def normalize_machines(cell: str, date_str: str, hall: str) -> str:
    if not cell or pd.isna(cell) or str(cell).strip() == '':
        return ''
    names = [n.strip() for n in str(cell).split('、') if n.strip()]
    result = []
    for n in names:
        for nm in norm_one(n, date_str, hall):
            if nm not in COLOR_MACHINES and nm not in result:
                result.append(nm)
    return '、'.join(result)

# 正規化後のDB名補正（マッピングのdb_matchが短縮名だったケース）
POST_CORRECT = {
    'ガールズ&パンツァー':       'ガールズ&パンツァー 最終章',
    'ToLoveるダークネス':       'ToLOVEるダークネス',
    '戦国乙女4':              '戦国乙女4 戦乱に閃く炯眼の軍師',
    'LBパチスロ ヱヴァンゲリヲン ～約束の扉～': 'ヱヴァンゲリヲン ～約束の扉～',
    'クレアの秘宝伝 ～はじまりの扉と太陽の石～ ボーナストリガー': 'クレアの秘宝伝 ～はじまりの扉と太陽の石～ ボーナストリガーver.',
    'パチスロ交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE-ART': '交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART',
    'スマスロ 緑ドン VIVA!情熱南米編 REVIVAL': '緑ドン VIVA!情熱南米編 REVIVAL',
    'ドラゴンハナハナ':           'スマート沖スロ ドラゴンハナハナ～閃光～',
}

def post_correct(cell: str) -> str:
    if pd.isna(cell) or not cell:
        return cell
    names = [n.strip() for n in str(cell).split('、')]
    corrected = [POST_CORRECT.get(n, n) for n in names]
    return '、'.join(corrected)

df_v5 = df_v4.copy()
df_v5['kamata7_full_half_normalized'] = df_v5.apply(
    lambda r: normalize_machines(r['kamata7_full_half'], str(r['date']), 'kamata7'), axis=1)
df_v5['kamata1_full_half_normalized'] = df_v5.apply(
    lambda r: normalize_machines(r['kamata1_full_half'], str(r['date']), 'kamata1'), axis=1)

# ポスト補正
df_v5['kamata7_full_half_normalized'] = df_v5['kamata7_full_half_normalized'].apply(post_correct)
df_v5['kamata1_full_half_normalized'] = df_v5['kamata1_full_half_normalized'].apply(post_correct)

df_v5['kamata7_full_half_normalized'] = df_v5['kamata7_full_half_normalized'].replace('', pd.NA)
df_v5['kamata1_full_half_normalized'] = df_v5['kamata1_full_half_normalized'].replace('', pd.NA)

df_v5.to_csv(OUT_DIR / "poco_data_v5.csv", index=False, encoding='utf-8')

print(f"K7 normalized: {df_v5['kamata7_full_half_normalized'].notna().sum()}日")
print(f"K1 normalized: {df_v5['kamata1_full_half_normalized'].notna().sum()}日")

# 未マップ
if unmapped:
    um_df = pd.DataFrame(sorted(unmapped.items(), key=lambda x: -x[1]), columns=['poco_machine', 'count'])
    um_df.to_csv(OUT_DIR / "poco_unmapped_machines.csv", index=False, encoding='utf-8')
    print(f"\n未マップ機種: {len(unmapped)}件")
    for _, row in um_df.iterrows():
        print(f"  {row['poco_machine']} ({row['count']}回)")
else:
    print("\n未マップ機種: 0件 ✅")

# DELETE された項目の監査ログ（PATCH_DELETEの誤登録を検出するため）
print(f"\n=== DELETEされた項目（監査用・{len(deleted_log)}種）===")
if deleted_log:
    for k, v in sorted(deleted_log.items(), key=lambda x: -x[1]):
        print(f"  [{k}] {v}回 → 削除")
else:
    print("  (なし)")

# 月別サマリー
print("\n=== 月別処理結果 ===")
df_v5['ym'] = df_v5['date'].astype(str).str[:6]
monthly = df_v5.groupby('ym').agg(
    total=('date','count'),
    k7_fh=('kamata7_full_half', lambda x: (x.str.strip() != '').sum()),
    k7_norm=('kamata7_full_half_normalized', 'count'),
    k1_fh=('kamata1_full_half', lambda x: (x.str.strip() != '').sum()),
    k1_norm=('kamata1_full_half_normalized', 'count'),
).reset_index()
print(monthly.to_string(index=False))
print("\n完了!")
