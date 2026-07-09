# みとや大森町 Phase 4: 耐久性検証

## サマリ

| variable    | section | split_half | iron_exclusion | top2_share | top2_label | 総合判定 |
| ----------- | ------- | ---------- | -------------- | ---------- | ---------- | ---- |
| day_of_week | 501-522 | PASS       | PASS           | 40.901     | FAIL       | ❌却下  |
| day_of_week | 523-556 | FAIL       | PASS           | 134.90     | FAIL       | ⚠️脆弱 |
| day_of_week | 557-590 | FAIL       | PASS           | 24.608     | WARN       | ⚠️脆弱 |
| day_of_week | 591-623 | PASS       | PASS           | 61.362     | FAIL       | ❌却下  |
| day_of_week | 624-657 | PASS       | PASS           | 55.973     | FAIL       | ❌却下  |
| day_of_week | 658-691 | FAIL       | PASS           | 50.596     | FAIL       | ⚠️脆弱 |
| day_of_week | 712-733 | PASS       | PASS           | 36.063     | FAIL       | ❌却下  |
| debut_phase | 501-522 | PASS       | PASS           | 40.901     | FAIL       | ❌却下  |
| debut_phase | 523-556 | PASS       | PASS           | 134.90     | FAIL       | ❌却下  |
| debut_phase | 557-590 | PASS       | PASS           | 24.608     | WARN       | ✅堅牢  |
| debut_phase | 591-623 | PASS       | PASS           | 61.362     | FAIL       | ❌却下  |
| debut_phase | 624-657 | PASS       | PASS           | 55.973     | FAIL       | ❌却下  |
| debut_phase | 712-733 | PASS       | PASS           | 36.063     | FAIL       | ❌却下  |
| debut_phase | 734-755 | PASS       | PASS           | 136.71     | FAIL       | ❌却下  |
