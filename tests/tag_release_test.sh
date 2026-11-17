#!/usr/bin/env bash
# Tests for tools/tag-release.sh, against a temp repo with a local bare remote.
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
tool="$here/tools/tag-release.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail=0
check() { if [ "$2" != "$3" ]; then echo "FAIL: $1 (expected $2, got $3)"; fail=1; else echo "ok: $1"; fi; }
export HOME="$tmp/home" GIT_CONFIG_NOSYSTEM=1; mkdir -p "$HOME"
g() { git -C "$1" -c user.email=t@example.com -c user.name=t -c commit.gpgsign=false -c tag.gpgsign=false "${@:2}"; }

git init -q --bare -b main "$tmp/remote.git"
up="$tmp/up"; git init -q -b main "$up"; g "$up" remote add keavi "$tmp/remote.git"
bump() { # repo version
    mkdir -p "$1/.claude-plugin"; printf '{"name": "stu", "version": "%s"}\n' "$2" > "$1/.claude-plugin/plugin.json"
    g "$1" add -A; g "$1" commit -q -m "release $2"
}
bump "$up" 0.1.0; g "$up" push -q keavi main

# The unit's worktree: a branch that bumps to 0.1.1. It lands as a squash on main, then
# another unit lands 0.1.2 on top before the tag step runs.
wt="$tmp/wt"; git clone -q "$tmp/remote.git" "$wt"; g "$wt" remote rename origin keavi
bump "$wt" 0.1.1
bump "$up" 0.1.1; landed=$(g "$up" rev-parse HEAD)
bump "$up" 0.1.2; g "$up" push -q keavi main

(cd "$wt" && bash "$tool" check) >/dev/null 2>&1; check "check fails before the tag exists" 1 $?
(cd "$wt" && bash "$tool" run) >/dev/null 2>&1; check "run succeeds" 0 $?
peel=$(git -C "$tmp/remote.git" rev-parse "refs/tags/0.1.1^{commit}")
check "tag is on the commit that landed 0.1.1, not the newer tip" "$landed" "$peel"
(cd "$wt" && bash "$tool" check) >/dev/null 2>&1; check "check passes once tagged" 0 $?
(cd "$wt" && bash "$tool" run) >/dev/null 2>&1; check "run again is a no-op success" 0 $?

# A remote tag at the wrong commit fails the check.
tip=$(g "$up" rev-parse HEAD)
g "$up" tag -a 0.1.2 -m 0.1.2 "$landed"; g "$up" push -q keavi refs/tags/0.1.2
wt2="$tmp/wt2"; git clone -q "$tmp/remote.git" "$wt2"; g "$wt2" remote rename origin keavi
(cd "$wt2" && bash "$tool" check) >/dev/null 2>&1; check "check fails on a tag at another commit" 1 $?
(cd "$wt2" && bash "$tool" run) >/dev/null 2>&1; check "run refuses to move an existing tag" 1 $?
check "remote tag untouched" "$landed" "$(git -C "$tmp/remote.git" rev-parse 'refs/tags/0.1.2^{commit}')"
[ "$tip" != "$landed" ]; check "fixture tip differs from landed" 0 $?

# A version not yet on main fails.
wt3="$tmp/wt3"; git clone -q "$tmp/remote.git" "$wt3"; g "$wt3" remote rename origin keavi
bump "$wt3" 0.1.9
(cd "$wt3" && bash "$tool" run) >/dev/null 2>&1; check "run fails when the version has not landed" 1 $?
(cd "$wt3" && bash "$tool" bogus) >/dev/null 2>&1; check "bad mode exits 2" 2 $?

exit $fail
