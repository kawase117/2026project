---
name: kamata7-data-processing
description: 蒲田七（マルハンメガシティ2000-蒲田7）のデータ処理・セグメント分類の正確な実装を保証するスキル。
evolved_from:
  - correct-segment-classification-floor-atype4
  - kamata7-floor-classification
confidence: 0.99
---

# Kamata7 Data Processing Skill

## トリガー
- 蒲田七のデータをセグメント分類（2F_N/3F_N/3F_A/2F_A）するとき
- machine_detailed_results からフロアを判定するとき
- A型/N型を machine_master のフラグで判定するとき

## 正しい実装

### 1. フロア判定（台番号ベース）
```sql
CASE WHEN CAST(machine_number AS INTEGER) < 3000
     THEN '2F'
     ELSE '3F'
END as floor
```

```python
df['floor'] = ['2F' if int(n) < 3000 else '3F'
               for n in df['machine_number'].astype(str)]
# 2F: 2001-2351付近 / 3F: 3001-3401付近
```

### 2. A/N型判定（machine_master 3フラグ）
```python
# machine_master を JOIN して jug_flag / hana_flag / bt_flag を取得
# A型 = ジャグラー(jug_flag=1) または ハナビ系(hana_flag=1) または BT系(bt_flag=1)
df['is_a_type'] = (
    (df['jug_flag'] == 1) | (df['hana_flag'] == 1) | (df['bt_flag'] == 1)
).astype(int)
df['atype_bucket'] = np.where(df['is_a_type'] == 1, 'A', 'N')
```

### 3. 4セグメント生成
```python
df['segment'] = df['floor'] + '_' + df['atype_bucket']
# 結果: 2F_N / 2F_A / 3F_N / 3F_A
```

### 4. 必要な JOIN
```sql
SELECT mdr.*, mm.jug_flag, mm.hana_flag, mm.bt_flag
FROM machine_detailed_results mdr
LEFT JOIN machine_master mm ON mdr.machine_name = mm.machine_name
```

## 禁止パターン
```
禁止: 台番号の先頭桁だけでA/N型を判定する
  → 台番号はフロアのみを示す。A/N型は machine_master の3フラグで判定。

禁止: machine_number を文字列比較で 2F/3F に分ける
  → 必ず整数変換してから 3000 と比較する。
```

## 進化の背景
2件のインスティンクトから抽出（全件99%・最高信頼度クラス）。
data-processing(2)。2026-05-28 CODEX指摘から生成。
