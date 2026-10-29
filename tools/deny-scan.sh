#!/usr/bin/env bash
# Usage: tools/deny-scan.sh [--staged | -0 | <path>...]
# -0 reads a NUL-separated file list on stdin (e.g. git ls-files -z | ...).
# Fails (exit 1) on any case-insensitive whole-word hit from the deny list,
# printing file:line:term. Exit 2 if the deny list is missing; 0 when clean.
# The list lives outside the repo; DENYLIST overrides the path (tests only).
# An optional allow list beside it exempts one term in one file, one
# "<path> <term>" pair per line, the path as the scan is given it; a malformed
# line exits 2. DENYALLOW overrides its path (tests only).
set -u
list="${DENYLIST:-$HOME/.config/stu-claude/denylist.txt}"
allow="${DENYALLOW:-$HOME/.config/stu-claude/denyallow.txt}"
if [ ! -f "$list" ]; then
  echo "deny list missing: $list" >&2
  exit 2
fi

if [ "${1:-}" = "--staged" ]; then
  files=()
  while IFS= read -r f; do files+=("$f"); done < <(git diff --cached --name-only --diff-filter=ACMR)
elif [ "${1:-}" = "-0" ]; then
  files=()
  while IFS= read -r -d '' f; do files+=("$f"); done
else
  files=("$@")
fi
[ "${#files[@]}" -gt 0 ] || exit 0

# Fail closed on inputs we cannot read (directories, e.g. submodules, are skipped).
scan=()
for f in "${files[@]}"; do
  if [ -d "$f" ] && [ ! -L "$f" ]; then continue; fi
  if [ ! -r "$f" ]; then echo "unreadable: $f" >&2; exit 2; fi
  scan+=("$f")
done
[ "${#scan[@]}" -gt 0 ] || exit 0

# Drop blank lines and comments so an empty pattern can't match everything.
pat="$(mktemp)"; allowpat="$(mktemp)"; trap 'rm -f "$pat" "$allowpat"' EXIT
grep -v -e '^[[:space:]]*$' -e '^[[:space:]]*#' "$list" > "$pat"
[ -s "$pat" ] || exit 0
if [ -f "$allow" ]; then
  grep -v -e '^[[:space:]]*$' -e '^[[:space:]]*#' "$allow" > "$allowpat"
  if ! awk 'NF != 2 { bad = 1 } END { exit bad }' "$allowpat"; then
    echo "deny-scan: malformed allow list, want '<path> <term>' per line: $allow" >&2
    exit 2
  fi
fi

raw="$(grep -HInwoiF -f "$pat" -- "${scan[@]}")"; grc=$?
if [ "$grc" -gt 1 ]; then echo "deny-scan: grep failed (rc=$grc)" >&2; exit 2; fi
hits="$(printf '%s' "$raw" | awk -F: -v allow="$allowpat" '
  BEGIN { while ((getline l < allow) > 0) { split(l, f, " "); ok[f[1] SUBSEP tolower(f[2])] = 1 } }
  { t=$3; for (i=4;i<=NF;i++) t=t":"$i; t=tolower(t); if (($1 SUBSEP t) in ok) next; print $1":"$2":"t }')"
if [ -n "$hits" ]; then
  echo "$hits"
  exit 1
fi
exit 0
