---
name: agent-orchestration
description: エージェント選択・並列実行・マルチパースペクティブ分析の手順ガイド。複雑な実装やレビュー時に使用。
---

# Agent Orchestration

## Available Agents

### プロジェクト固有エージェント(`~/.claude/agents/`に実体あり)

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| pachinko-domain-analyst | ホール行動・ゾロ目・曜日・DD・異常検知の解釈 | ドメイン固有の統計解釈が必要な時 |
| pachinko-ml-strategist | 仮説設計→特徴量→訓練→評価→解釈の全サイクル | MLサイクル全体を回す時 |
| simulator-calibration-agent | シミュレーターの設計・キャリブレーション・Layer構成 | シミュレーター設計時 |

### 汎用エージェント(`everything-claude-code`プラグイン提供、`everything-claude-code:<name>`形式で起動)

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| everything-claude-code:planner | Implementation planning | Complex features, refactoring |
| everything-claude-code:architect | System design | Architectural decisions |
| everything-claude-code:tdd-guide | Test-driven development | New features, bug fixes |
| everything-claude-code:code-reviewer | Code review | After writing code |
| everything-claude-code:security-reviewer | Security analysis | Before commits |
| everything-claude-code:build-error-resolver | Fix build errors | When build fails |
| everything-claude-code:e2e-runner | E2E testing | Critical user flows |
| everything-claude-code:refactor-cleaner | Dead code cleanup | Code maintenance |
| everything-claude-code:doc-updater | Documentation | Updating docs |
| everything-claude-code:rust-reviewer | Rust code review | Rust projects(本プロジェクトはPython中心のため出番は稀) |

## Immediate Agent Usage

No user prompt needed:
1. Complex feature requests - Use **everything-claude-code:planner**
2. Code just written/modified - Use **everything-claude-code:code-reviewer**
3. Bug fix or new feature - Use **everything-claude-code:tdd-guide**
4. Architectural decision - Use **everything-claude-code:architect**
5. パチンコ分析ドメインの解釈が必要 - Use **pachinko-domain-analyst** / **pachinko-ml-strategist** / **simulator-calibration-agent**

## Parallel Task Execution

ALWAYS use parallel Task execution for independent operations:

```markdown
# GOOD: Parallel execution
Launch 3 agents in parallel:
1. Agent 1: Security analysis of auth module
2. Agent 2: Performance review of cache system
3. Agent 3: Type checking of utilities

# BAD: Sequential when unnecessary
First agent 1, then agent 2, then agent 3
```

## Multi-Perspective Analysis

For complex problems, use split role sub-agents:
- Factual reviewer
- Senior engineer
- Security expert
- Consistency reviewer
- Redundancy checker
