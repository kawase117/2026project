---
name: update-machine-master
description: machine_masterテーブルのbt_flag/hana_flagを機種名キーワードマッチで更新する手順。新機種追加・表記ゆれ修正時に使用。
evolved_from:
  - machine-master-flag-keyword-based
  - machine-master-insert-vs-update
  - machine-name-hyoki-zure-patterns
  - machine-master-per-hall-db
confidence: 0.95
---

# update-machine-master

新機種がDBに追加されたとき、または bt_flag / hana_flag が 0 のままになっているときに実行する。

## 実行ステップ

### Step 1: フラグ未設定の機種を確認
```sql
SELECT machine_name, bt_flag, hana_flag, COUNT(*) as records
FROM machine_master
WHERE bt_flag = 0 AND hana_flag = 0
GROUP BY machine_name
ORDER BY records DESC;
```

### Step 2: キーワードマッチによるフラグ判定
```python
BT_KEYWORDS = ["バジリスク", "戦国乙女", "北斗", "リング", "Re:ゼロ",
                "まどマギ", "沖ドキ", "ハナビ"]
HANA_KEYWORDS = ["ハナハナ", "花火", "ハナ"]

def classify_machine(machine_name: str) -> dict:
    name_normalized = machine_name.replace(" ", "").replace("　", "")
    return {
        "bt_flag": int(any(kw in name_normalized for kw in BT_KEYWORDS)),
        "hana_flag": int(any(kw in name_normalized for kw in HANA_KEYWORDS))
    }
```

### Step 3: INSERT vs UPDATE の分岐
```sql
-- 既存レコードの場合
UPDATE machine_master SET bt_flag = ?, hana_flag = ? WHERE machine_name = ?;

-- 新規機種の場合（bt_flag=0 のままにしない）
INSERT INTO machine_master (machine_name, bt_flag, hana_flag) VALUES (?, ?, ?);
```

### Step 4: 表記ゆれの確認
```python
NORMALIZATION_MAP = {
    "ハナビ": ["花火", "HANABI", "ハナビTurbo"],
    "バジリスクX": ["バジリスク絆X", "バジリスク−甲賀忍法帖−絆２"],
}
# 正規化後にフラグ判定する
```

### Step 5: ホール別DBの確認
```
machine_master はホール別DBに存在（共通DBではない）。
db/{ホール名}.db を個別に指定すること。
```

## 実行確認
```sql
SELECT machine_name, bt_flag, hana_flag
FROM machine_master
WHERE bt_flag = 1 OR hana_flag = 1
ORDER BY machine_name;
```

## 進化の背景
3件のインスティンクトから抽出（全件信頼度 95%+）。
database-maintenance ドメインのワークフローが完全に固まっているためコマンド化。
