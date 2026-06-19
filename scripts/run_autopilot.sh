#!/usr/bin/env bash
# Launch the autonomous research agent via Microsoft `agency` Copilot CLI in autopilot mode.
#
# Usage:
#   ./scripts/run_autopilot.sh [path-to-prompt-file] [max-continues]
#
# Defaults: prompts/example_goal.txt and 300 continues (good for ~8-16h runs).
#
# Requires: `agency` CLI installed and authenticated.

set -euo pipefail

PROMPT_FILE="${1:-prompts/example_goal.txt}"
MAX_CONT="${2:-300}"
MODEL="${MODEL:-claude-opus-4.7}"

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "Prompt file not found: $PROMPT_FILE" >&2
  exit 1
fi

PROMPT_TEXT="$(cat "$PROMPT_FILE")"

echo "Launching agency copilot in autopilot mode"
echo "  prompt file:    $PROMPT_FILE"
echo "  max continues:  $MAX_CONT"
echo "  model:          $MODEL"
echo

exec agency copilot \
  --autopilot \
  --max-autopilot-continues "$MAX_CONT" \
  --model "$MODEL" \
  --log-level info \
  -p "$PROMPT_TEXT"
