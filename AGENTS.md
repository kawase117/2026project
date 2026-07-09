# AGENTS.md

**Rule:** In each command, define then use. Do not escape `$`. Use generic `'path/to/file.ext'`.

Read `CLAUDE.md` and `CONTEXT.md` at the start of work. When editing inside a subtree, read the nearest `CLAUDE.md` first. If guidance conflicts, follow direct user instructions, then this file, then the nearest `CLAUDE.md`, then root `CLAUDE.md`, then `CONTEXT.md`.

Keep this file short. Put recurring procedures in `~/.codex/prompts/`, task workflows in skills, and special-purpose delegation in subagents.

If the task depends on Codex/Claude coordination, use the repo's agreed agent-messaging flow and keep the conversation traceable in the project docs or task file.
