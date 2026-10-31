#!/bin/sh
# PreToolUse launcher for the publish guard. It starts Python only for a payload that can
# concern the guard, so an unrelated tool call costs a few milliseconds and no interpreter.
deny() {
  printf '%s\n' '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "stu publish guard: '"$1"'"}}'
  exit 0
}
payload=$(cat)
printf '%s' "$payload" | grep -qiE 'approvals\.tsv|stu-approve|stu_approve|--no-verify|hookspath|"tool_name" *: *"(functions\.)?apply_patch"|"tool_name" *: *"mcp__|(^|[^A-Za-z0-9_])gh([^A-Za-z0-9_]|$)'
[ $? -eq 1 ] && exit 0
self="$0"; while [ -L "$self" ]; do l=$(readlink "$self"); case "$l" in /*) self="$l";; *) self="$(dirname "$self")/$l";; esac; done
command -v python3 >/dev/null 2>&1 || deny "python3 was not found, so this tool call cannot be checked; install Python 3.9 or newer"
out=$(printf '%s' "$payload" | python3 "$(dirname "$self")/../scripts/publish_guard.py")
rc=$?
[ $rc -eq 0 ] || deny "the guard script exited $rc, so this tool call cannot be checked"
[ -n "$out" ] && printf '%s\n' "$out"
exit 0
