# ダイデータオンライン みとや大森町店 当日収集・分析

store `101309` の21.3円スロットを当日分だけ収集し、続けて分析レポートを作る。
仕様と制約は `.claude/skills/daidata-mitoya-daily/SKILL.md`。日次DBには書き込まない(DBは読み取り専用)。

```powershell
scraper\daidata\run_mitoya_complete.cmd
```

- 収集: 機種ページを直列・3秒間隔で取得。429/403/台数不一致/列ずれで停止し、停止時は分析しない。
- 出力: `output/mitoya_omorimachi_slots_21.3yen_YYYY-MM-DD.csv`、`output/mitoya_daidata_report_YYYY-MM-DD.md`
- 分析: RB単独のz値(自機種の直近90日平均が基準)、ジャグ系の設定推定と全台系判定(`scraper/site777/setting_estimator.py` 再利用)、
  AT機は回転数比のみ、末尾別、台番号連番の並び候補。
- 差枚は取れない。AT機の全台系は判定不能。
- 実行は1日の取得を1回ずつ。Codex/Claudeで同時実行しない。
