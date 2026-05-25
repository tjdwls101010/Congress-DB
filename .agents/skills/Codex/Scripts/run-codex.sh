#!/usr/bin/env bash
set -euo pipefail

# Codex CLI wrapper — combines system prompts with user queries,
# filters JSONL output, and manages sessions.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROMPTS_DIR="$(cd "$SCRIPT_DIR/../Prompts" && pwd)"

# macOS APFS stores filenames in NFD; codex emits paths in NFD.
# bash's $PWD is NFC, so byte-level prefix matching in jq fails on Korean/CJK
# directory names. Normalize PWD to NFD so the relpath function in JQ_FILTER
# can correctly strip the workspace prefix from file_change paths.
CODEX_CWD_NFD=$(printf '%s' "$PWD" | python3 -c "import sys, unicodedata; sys.stdout.write(unicodedata.normalize('NFD', sys.stdin.read()))" 2>/dev/null || printf '%s' "$PWD")

# Defaults
MODEL="gpt-5.5"
EFFORT="xhigh"
SANDBOX="workspace-write"
PROMPT_FILE=""
RESUME_ID=""
RESUME_LAST=false
CANCEL=false
QUERY=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prompt)
      PROMPT_FILE="$2"
      shift 2
      ;;
    --resume)
      RESUME_ID="$2"
      shift 2
      ;;
    --resume-last)
      RESUME_LAST=true
      shift
      ;;
    --sandbox)
      SANDBOX="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --effort)
      EFFORT="$2"
      shift 2
      ;;
    --cancel)
      CANCEL=true
      shift
      ;;
    *)
      if [[ -z "$QUERY" ]]; then
        QUERY="$1"
      else
        QUERY="$QUERY $1"
      fi
      shift
      ;;
  esac
done

# --- Cancel mode ---
if $CANCEL; then
  PIDS=$(pgrep -f "codex exec" 2>/dev/null || true)
  if [[ -z "$PIDS" ]]; then
    echo '{"type":"cancel","status":"no_running_process"}'
  else
    kill $PIDS 2>/dev/null || true
    echo "{\"type\":\"cancel\",\"status\":\"killed\",\"pids\":\"$PIDS\"}"
  fi
  exit 0
fi

# --- Validate query ---
if [[ -z "$QUERY" ]]; then
  echo '{"type":"error","message":"No query provided. Usage: run-codex.sh [options] \"your query\""}' >&2
  exit 1
fi

# --- Build combined prompt ---
COMBINED=""

if [[ -n "$PROMPT_FILE" ]]; then
  # Resolve prompt file path
  if [[ -f "$PROMPT_FILE" ]]; then
    PROMPT_PATH="$PROMPT_FILE"
  elif [[ -f "$PROMPTS_DIR/$PROMPT_FILE" ]]; then
    PROMPT_PATH="$PROMPTS_DIR/$PROMPT_FILE"
  else
    echo "{\"type\":\"error\",\"message\":\"Prompt file not found: $PROMPT_FILE\"}" >&2
    exit 1
  fi

  SYSTEM_CONTENT=$(cat "$PROMPT_PATH")
  COMBINED="<SystemPrompt>
${SYSTEM_CONTENT}
</SystemPrompt>
<UserPrompt>
${QUERY}
</UserPrompt>"
else
  COMBINED="$QUERY"
fi

# --- jq filter for JSONL output ---
# Strips full file contents from logs (aggregated_output) while keeping
# enough metadata — commands, exit codes, edited paths, agent messages —
# for Claude Code to reason about what Codex did.
JQ_FILTER='
def strip_wrapper:
  if test("^/bin/.+ -lc ") then
    sub("^/bin/[^ ]+ -lc "; "")
    | sub("^[\"\\x27]"; "")
    | sub("[\"\\x27]$"; "")
    | gsub("\\\\\""; "\"")
  else . end;

def relpath($cwd):
  if ($cwd != "" and startswith($cwd + "/")) then .[($cwd | length) + 1:]
  else . end;

if .type == "thread.started" then {type, thread_id}
elif .type == "turn.completed" then {type, usage}
elif (.type == "item.completed" and .item.type == "agent_message") then {type: "agent_message", text: .item.text}
elif (.type == "item.completed" and .item.type == "command_execution") then
  {type: "command", cmd: (.item.command | strip_wrapper), exit_code: .item.exit_code}
elif (.type == "item.completed" and .item.type == "file_change") then
  {type: "file_change", changes: [.item.changes[] | {path: (.path | relpath($ENV.CODEX_CWD // "")), kind}]}
else empty end
'

# --- Execute codex ---
if [[ -n "$RESUME_ID" ]]; then
  printf '%s' "$COMBINED" | codex exec resume "$RESUME_ID" --json -m "$MODEL" - \
    2>/dev/null | CODEX_CWD="$CODEX_CWD_NFD" jq -c --unbuffered "$JQ_FILTER"

elif $RESUME_LAST; then
  printf '%s' "$COMBINED" | codex exec resume --last --json -m "$MODEL" - \
    2>/dev/null | CODEX_CWD="$CODEX_CWD_NFD" jq -c --unbuffered "$JQ_FILTER"

else
  printf '%s' "$COMBINED" | codex exec --json \
    -m "$MODEL" \
    -c "model_reasoning_effort=\"${EFFORT}\"" \
    -s "$SANDBOX" \
    - 2>/dev/null | CODEX_CWD="$CODEX_CWD_NFD" jq -c --unbuffered "$JQ_FILTER"
fi
