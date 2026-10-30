# 10月振り返りの改善 実装計画

作成 2026-10-30。根拠は `document/reviews/2026-10-monthly-retrospective.md`(先に全文を読む)。
ユーザー指示: 振り返りの推奨をすべて実装する(ジャグラー規則の変更を含む)。学びが予測に反映されない問題を最優先とする。文脈は整理・分割し、必要なときに読みに行く作りにする。

作業は3つ。編集するファイルが重ならないので、別々のセッションで並行して進められる。各セッションは、自分の担当ファイルだけを編集・コミットする。

---

## 作業1: 学びの台帳と凍結前の点検(最優先)

担当ファイル: `document/registry/LESSONS.jsonl`(新規)、`backtest/prediction_ledger.py`、`scripts/run_morning_docs.py`、関連テスト。

1. **学びの台帳** `document/registry/LESSONS.jsonl`
   - 1行1件。項目: id(L001…)、rule、basis_type(prev_day / small_n_models / few_past_events / midday_rb など)、検出用キーワード・正規表現、first_seen、reconfirmed(日付リスト)、exceptions、source。
   - 登録は**2回以上確認したもの、または統計の裏づけがあるものだけ**。1日の観察(例: 10/17「HALF BURST 3連続赤字は確定的」)は入れない。
   - 10月の答え合わせの「学び」「反省」節から6件前後を初期登録する(前日継続なし、少台数機種、過去回3回以下で避ける、途中の高RBは回帰、言葉遊び抽出、標本3回で弱い日と決めない)。
   - `add` / `reconfirm` / `list` / 月次集計のCLIを付ける。追加前に `backtest-module-guide` スキルで既存モジュールと重複しないか確認する。
2. **凍結前の点検**(`prediction_ledger freeze-doc`)
   - 「判断:」と「避ける」の行の根拠を台帳の型と照らす。根拠が台帳の型だけの行があれば、**警告ではなく凍結を止めて**、行とLESSONのidを表示する。
   - `--allow L003:理由` で通せる。理由は凍結JSONに残す。`--dry-run` も付ける。
3. **自動の答え合わせ**(`scripts/run_morning_docs.py`、448-481行付近のプロンプトと405行付近の検証)
   - プロンプトには、台帳の要約(idとruleだけ)を渡す。既知の学びは「既知(L00x)を再確認」と書かせ、新しい学びだけを本文にする。
   - 「今日の予測への示唆」は、予告の有無・イベント日か・当日見る指標に限る。前日の機種・末尾・列の継続を根拠にした示唆は、検証で不合格にする。
4. 月次集計: 学びごとに、凍結で止めた回数・`--allow` で通した回数・再確認した回数を出す。

完了条件: テストを追加して `venv\Scripts\python.exe -m pytest test/ -q` が通る。`document/reviews/2026-10-30-prediction.md` にdry-runをかけ、止まる行を報告する。

## 作業2: 予測の形・採点

担当ファイル: `backtest/scoreboard.py` とテスト、予測手順のスキル・テンプレート、定期タスク `C:\Users\apto117\.claude\scheduled-tasks\daily-prediction-review\SKILL.md`。CLAUDE.mdは作業3の担当なので、規則の本文は作業3で書く。

1. **予測の形**(手順書・テンプレート)
   - 各ホールの最初に、基準 `*_model_term60_top3` の3機種をそのまま載せる。予告・イベントで差し替える機種だけに理由を書く。
   - 蒲田7は、予告のない日は機種を推さない。鉄台2026とRB判別機の自動候補だけ。
   - 「避ける」は構造の理由(機械割の低さ・稼働不足・台数の変化)だけ。前日・過去回の負けを理由にしない。
   - 台番号の名指しは `backtest/rb_candidates.py` の自動候補に一本化する。手で選ぶのは、予告で台が指定された日だけ。
   - 予告がある日は、筆頭名指し・公約機種・先バレを主にし、同系列の過去回は従にする。言葉遊びの抽出は判断行に入れない。
   - 判断行は少数にとどめ、文書を短く保つ。
2. **採点**(`backtest/scoreboard.py`)
   - 「手書きの推し − 基準」を、ホール別・日別に出す(同じホール・同じ日の `*_model_term60_top3` のedgeを引く)。
   - 「避ける」を、開店前の凍結分と、当日・事後の分に分けて出す。
   - RB判別機ではRB比を主にする。読み方に「月次はRB比で判定、差枚は3か月単位」と書く。
   - 振り返り文書5節の11月検証計画の各項目を、どの表で判定するかの対応表を付ける。

完了条件: テストが通る。`venv\Scripts\python.exe -m backtest.scoreboard` で新しい表が出る。

## 作業3: 文脈の整理と分割(ユーザー指示 2026-10-30)

担当ファイル: `CLAUDE.md`、メモリ `MEMORY.md`(`C:\Users\apto117\.claude\projects\C--Users-apto117-Documents-pachinko-analyzer-src-2026project\memory\`)、新規の手順書。

**ねらい**: 毎セッション読み込むのは「索引と鉄則」だけにする。詳細は、作業の種類に応じて必要なときに読みに行く。今は、CLAUDE.mdに手順の細部(ジャグラー候補の手順など)が直書きされ、MEMORY.mdも約150行が毎回読み込まれている。そのため文脈が早く埋まり、肝心の学びが埋もれる。

1. **CLAUDE.mdを索引に縮める**
   - 残すもの: 最重要ルール、Python実行環境、DB型の注意、GitHub運用、「作業の種類 → 読む文書」の対応表。
   - 移すもの: 予測の手順(ジャグラー候補の規則を含む) → `document/procedures/PREDICTION.md`、答え合わせの手順 → `document/procedures/ANSWERCHECK.md`、イベント登録 → `document/procedures/EVENTS.md`。
   - ジャグラー規則は新しい内容で書く: みとやは継続。蒲田7は候補表をやめ「候補を出さない(10月は有害、差枚edge −141・CI上限 −15)」と書く。楽園は11月末まで続け、差を検出できなければ止める。蒲田1は現状のまま。変更日と根拠を添える。
   - 作業2で決めた予測の形も、PREDICTION.mdに書く。冒頭に「`document/registry/LESSONS.jsonl` を読む」を入れる。
2. **MEMORY.mdを分割する**
   - 索引には、全作業に効く方針(15〜20行)だけを残す。
   - ホール別のメモ(蒲田7・蒲田1・楽園・みとや・ヒロキほか)は `memory/halls/<ホール>.md` の小索引に移す。MEMORY.mdには「ホール◯◯を扱うときに読む」の1行だけを置く。
   - 答え合わせの方法論メモのうち、2回以上確認した規則は `LESSONS.jsonl` に移し、メモ側からは消す(重複させない)。
   - `consolidate-memory` スキルがあれば、それを使う。
3. **作業の種類 → 読む文書** の対応表(CLAUDE.mdに置く)
   - 予測: PREDICTION.md、LESSONS.jsonl、対象ホールの `memory/halls/`
   - 答え合わせ: ANSWERCHECK.md、LESSONS.jsonl
   - 予告の登録: EVENTS.md、`announce-prep` スキル
   - ホール分析: `hall-analysis-checklist` / `hall-axis-scan` スキル

完了条件: CLAUDE.mdとMEMORY.mdの行数を、変更前後で報告する。移した内容が消えていないことを照合する(移動前の見出しの一覧と、移動先の見出しの一覧を突き合わせる)。

---

## 進め方

- 作業1・2・3は担当ファイルが重ならないので、並行してよい。
- 各作業は、自分の変更だけをコミットしてmainにプッシュする(force不可)。
- 実装はCLAUDE.mdの分担に従い、Codex(`codex:rescue`)に委任してよい。
