---
name: agent-orchestration
description: このプロジェクトで実際に起動できるサブエージェントとレビュー用スキルの一覧と選び方。「どのエージェントに投げるか」「並列に回すべきか」を判断するときに参照する。存在しないエージェント名を呼んで失敗するのを防ぐことが主目的。
---

# Agent Orchestration

> **2026-09-11 全面改訂**
> 旧版は `everything-claude-code:planner` など汎用エージェント10種を掲載していたが、
> **これらは起動できない**。プラグイン `everything-claude-code@2.0.0-rc.1` の
> `.claude-plugin/plugin.json` は `skills` と `commands` しか宣言しておらず、
> `agents/` 配下の48ファイルは登録されていない。旧版の表は全滅していた。

## 実在するサブエージェント

### プロジェクト固有（実体は `.claude/agents/` — ユーザーグローバルではない）

| Agent | 用途 |
|---|---|
| `pachinko-domain-analyst` | ホール行動・ゾロ目・曜日・DD・異常検知のドメイン解釈 |
| `pachinko-ml-strategist` | 仮説設計→特徴量→訓練→評価→解釈のMLサイクル統括 |
| `simulator-calibration-agent` | シミュレーターの設計・キャリブレーション・Layer構成 |

### 組み込み

| Agent | 用途 |
|---|---|
| `Explore` | 多数のファイル・命名規約を横断する読み取り専用の探索。結論だけ欲しいとき |
| `Plan` | 実装方針の設計。手順・重要ファイル・トレードオフを返す |
| `general-purpose` | 上記に当てはまらない多段タスク |
| `claude-code-guide` | Claude Code / Agent SDK / Claude API 自体の使い方 |
| `codex:codex-rescue` | Codexへの委任（**read-onlyサンドボックス**。調査・レビュー限定、書き込み不可） |

## レビューはエージェントでなくスキルで行う

旧版が挙げていた `code-reviewer` / `security-reviewer` / `build-error-resolver` /
`python-reviewer` は **いずれも存在しない**。代わりに以下を使う。

| やりたいこと | 使うもの |
|---|---|
| 変更差分のレビュー | `/code-review`（level: low〜max、`ultra` はクラウド多エージェント） |
| セキュリティレビュー | `/security-review` |
| 重複・冗長の整理と適用 | `/simplify` |

## 起動の判断

**サブエージェントは、ユーザー・CLAUDE.md・スキルのいずれかが求めたときにだけ起動する。**
旧版の「プロンプト不要で常に planner を起動」「独立操作は常に並列Task」は現在の運用と衝突するので破棄した。
各起動はコンテキストをゼロから作り直すため、こちらで持っている情報で足りる作業は自分で片付ける。

起動を検討してよい場面:

- 探索範囲が広く、ファイル本文ではなく結論だけが要る → `Explore`
- ドメイン解釈そのものが成果物 → `pachinko-domain-analyst`
- 実装の丸投げ、または第二の診断が欲しい → `codex:codex-rescue`
  （委任前に `codex-prompt-precision` スキルでプロンプトを自己チェックする）

複数を同時に走らせるのは、互いに依存がなく、かつユーザーが並列を望んでいるときに限る。

## 関連

- `codex-prompt-precision` — Codex委任前のプロンプト自己チェック（必須）
- `development-workflow`（グローバル）— リサーチ→計画→TDD→レビュー→コミットの流れ
