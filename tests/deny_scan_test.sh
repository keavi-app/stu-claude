#!/usr/bin/env bash
# Tests for tools/deny-scan.sh
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
scan="$here/tools/deny-scan.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail=0
check() { if [ "$2" != "$3" ]; then echo "FAIL: $1 (expected $2, got $3)"; fail=1; else echo "ok: $1"; fi; }

echo acmecorp > "$tmp/list"
printf 'AcmeCorp rules\n' > "$tmp/bad.txt"
printf 'nothing here\nacmecorporation is not a whole-word hit\n' > "$tmp/clean.txt"

out="$(DENYLIST="$tmp/list" bash "$scan" "$tmp/bad.txt" 2>&1)"; rc=$?
check "hit exits 1" 1 "$rc"
case "$out" in *":1:acmecorp"*) check "output has :1:acmecorp" 0 0;; *) check "output has :1:acmecorp" 0 1;; esac

DENYLIST="$tmp/list" bash "$scan" "$tmp/clean.txt" >/dev/null 2>&1; check "clean exits 0" 0 $?

out="$(DENYLIST="$tmp/nope" bash "$scan" "$tmp/clean.txt" 2>&1)"; rc=$?
check "missing list exits 2" 2 "$rc"
case "$out" in *"deny list missing: $tmp/nope"*) check "missing message" 0 0;; *) check "missing message" 0 1;; esac
DENYLIST="$tmp/list" bash "$scan" "$tmp/does-not-exist" >/dev/null 2>&1; check "nonexistent path exits 2" 2 $?

printf 'AcmeCorp here\n' > "$tmp/has space.txt"
printf '%s\0%s\0' "$tmp/clean.txt" "$tmp/has space.txt" | DENYLIST="$tmp/list" bash "$scan" -0 >/dev/null 2>&1
check "-0 list with spaced filename hit exits 1" 1 $?
printf '%s\0' "$tmp/clean.txt" | DENYLIST="$tmp/list" bash "$scan" -0 >/dev/null 2>&1; check "-0 clean exits 0" 0 $?

# Allow list: <path> <term> exempts that term in that one file only.
echo umbrella >> "$tmp/list"
printf 'AcmeCorp on the site\n' > "$tmp/site.html"
printf '%s acmecorp\n' "$tmp/site.html" > "$tmp/allow"
DENYLIST="$tmp/list" DENYALLOW="$tmp/allow" bash "$scan" "$tmp/site.html" >/dev/null 2>&1
check "allowed term in allowed file exits 0" 0 $?
DENYLIST="$tmp/list" DENYALLOW="$tmp/allow" bash "$scan" "$tmp/bad.txt" >/dev/null 2>&1
check "allowed term in another file exits 1" 1 $?
printf 'AcmeCorp and Umbrella\n' > "$tmp/site.html"
out="$(DENYLIST="$tmp/list" DENYALLOW="$tmp/allow" bash "$scan" "$tmp/site.html" 2>&1)"; rc=$?
check "other term in allowed file exits 1" 1 "$rc"
case "$out" in *"acmecorp"*) check "allowed term not reported" 0 1;; *) check "allowed term not reported" 0 0;; esac
printf '%s\n' "$tmp/site.html" > "$tmp/allow-bad"
DENYLIST="$tmp/list" DENYALLOW="$tmp/allow-bad" bash "$scan" "$tmp/site.html" >/dev/null 2>&1
check "malformed allow line exits 2" 2 $?
DENYLIST="$tmp/list" DENYALLOW="$tmp/no-allow" bash "$scan" "$tmp/bad.txt" >/dev/null 2>&1
check "missing allow list exempts nothing" 1 $?

exit $fail
