---
name: Codex
description: |
  Delegate coding tasks to OpenAI Codex CLI (GPT-5.5). Handles task execution, session
  resume, progress tracking, and system prompt injection.
  Use when the user asks to run Codex, delegate work to GPT, or when an independent
  coding task benefits from a second agent. Also use for Codex setup and auth checks.
  Triggers: codex, GPT로 시켜, 코덱스, delegate to GPT, run with codex, 코덱스로 실행
---

# Codex — GPT Task Delegation via CLI

Delegate coding work to Codex CLI and track results. The wrapper script at
`Scripts/run-codex.sh` handles prompt assembly, JSONL filtering, and session management.

## Calling the wrapper

```bash
"${CLAUDE_SKILL_DIR}/Scripts/run-codex.sh" [options] "query"
```

### Examples

New task with system prompt:
```bash
"${CLAUDE_SKILL_DIR}/Scripts/run-codex.sh" --prompt tdd.md "Implement a user auth module with full test coverage"
```

Minimal call (defaults: gpt-5.5, xhigh, workspace-write):
```bash
"${CLAUDE_SKILL_DIR}/Scripts/run-codex.sh" "Review the error handling in src/api/handler.ts"
```

Resume previous session:
```bash
"${CLAUDE_SKILL_DIR}/Scripts/run-codex.sh" --resume 019dfb52-070d-7ef0-a87e-bdca97fb5b87 "Add edge case tests"
```

Read-only analysis:
```bash
"${CLAUDE_SKILL_DIR}/Scripts/run-codex.sh" --sandbox read-only "Explain the architecture of this codebase"
```

Cancel a running task:
```bash
"${CLAUDE_SKILL_DIR}/Scripts/run-codex.sh" --cancel
```

### Parameters

| Flag | Default | Notes |
|------|---------|-------|
| `--prompt <file>` | none | Markdown file from `Prompts/` — injected as system prompt |
| `--resume <id>` | new session | Thread ID from previous run |
| `--resume-last` | new session | Continue most recent session |
| `--sandbox <mode>` | workspace-write | read-only, workspace-write, danger-full-access |
| `--model <model>` | gpt-5.5 | |
| `--effort <level>` | xhigh | Reasoning depth |
| `--cancel` | — | Kill running codex process |

## Output format

The script filters Codex JSONL output. You will see compact JSON lines:

```jsonl
{"type":"thread.started","thread_id":"019d..."}
{"type":"command","cmd":"find . -name '*.ts'","exit_code":0}
{"type":"agent_message","text":"Here is the implementation..."}
{"type":"turn.completed","usage":{"input_tokens":30000,"output_tokens":500,...}}
```

Command outputs (file contents, build logs) are stripped to keep context small.
For full detail, read the session file at `~/.codex/sessions/` — Codex writes
raw JSONL there in real time, even while the task is still running.

The wrapper streams its filtered output line-by-line. To watch a long-running
task without blocking, redirect to a file and tail it from a separate call:

```bash
"${CLAUDE_SKILL_DIR}/Scripts/run-codex.sh" "long task" > /tmp/codex.log &
tail -f /tmp/codex.log
```

## Session management

Every run returns a `thread_id` in the first output line. Remember it — passing it
back via `--resume` lets Codex continue with full prior context instead of starting
from scratch.

**Good pattern**: new task → note thread_id → user wants changes → resume with that id.

**Anti-pattern**: creating a new session every time when the user is iterating on
the same task. This loses all accumulated context.

## System prompts

`Prompts/` contains reusable instruction files that guide Codex behavior for specific
methodologies. Pass them via `--prompt`:

```bash
"${CLAUDE_SKILL_DIR}/Scripts/run-codex.sh" --prompt tdd.md "Build feature X"
```

The prompt file content is wrapped in `<SystemPrompt>` tags and the query in
`<UserPrompt>` tags before being piped to Codex.

## What this skill is NOT

- Not for interactive Codex TUI sessions
- Not for Codex Cloud tasks
- Not for direct code implementation — delegate to Codex, don't do it yourself
