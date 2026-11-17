#!/usr/bin/env bash
# Tests for tools/roborev-push-guard.sh. A fake `roborev` on PATH models the CLI; nothing
# real is queried. State files in $st: down, fix_out, list_queued, list_running, list_done.
# The fake answers a job listing only when it asks for every job (--limit 0), as on a long
# branch whose jobs sit beyond any page size.
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
guard="$here/tools/roborev-push-guard.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail=0
check() { if [ "$2" != "$3" ]; then echo "FAIL: $1 (expected $2, got $3)"; fail=1; else echo "ok: $1"; fi; }
has() { case "$2" in *"$3"*) check "$1" 0 0;; *) check "$1" 0 1; echo "    output: $2";; esac; }

st="$tmp/state"; bin="$tmp/bin"; mkdir -p "$st" "$bin"
cat > "$bin/roborev" <<SHIM
#!/usr/bin/env bash
S="$st"
if [ -e "\$S/down" ]; then echo "Error: connection refused" >&2; exit 1; fi
[ "\$1" = job ] && shift
case "\$1" in
fix) if [ -s "\$S/fix_out" ]; then cat "\$S/fix_out" >&2; else echo "No open jobs found." >&2; fi ;;
list) s=""; l=50; while [ \$# -gt 0 ]; do [ "\$1" = --status ] && s="\$2"; [ "\$1" = --limit ] && l="\$2"; shift; done
      # Every fixture job is older than any page: only an unlimited listing (--limit 0) sees it.
      if [ "\$l" = 0 ] && [ -s "\$S/list_\$s" ]; then cat "\$S/list_\$s"; else echo "[]"; fi ;;
*) exit 2 ;;
esac
SHIM
chmod +x "$bin/roborev"

SHA=1111111111111111111111111111111111111111
ZERO=0000000000000000000000000000000000000000
line="refs/heads/feat $SHA refs/heads/feat $ZERO"
reset() { rm -f "$st"/*; }
done_at() { printf '[\n  {\n    "git_ref": "%s",\n    "status": "done"\n  }\n]\n' "$1" > "$st/list_done"; }
run() { out=$(printf '%s\n' "$1" | PATH="$bin:$PATH" bash "$guard" 2>&1); rc=$?; }

reset; done_at "$SHA"; run "$line"
check "done review at the SHA, nothing open: pass" 0 "$rc"

reset; run "$line"
check "no review for the SHA: refused" 1 "$rc"
has "names the never-reviewed rule" "$out" "no done review job for this SHA"

reset; done_at "$SHA"; echo "Found 2 open job(s):" > "$st/fix_out"; run "$line"
check "open job on the branch: refused" 1 "$rc"
has "names the open-job rule" "$out" "open review job"

reset; done_at "$SHA"; printf '[{"git_ref": "%s"}]\n' "$SHA" > "$st/list_running"; run "$line"
check "running review for the SHA: refused" 1 "$rc"
has "says to wait" "$out" "running review job exists"

reset; done_at "2222222222222222222222222222222222222222"; run "$line"
check "done review only at another SHA: refused" 1 "$rc"

reset; echo "Something new" > "$st/fix_out"; run "$line"
check "unrecognised fix --list output: unguarded pass" 0 "$rc"
has "warns loudly" "$out" "could NOT check this push"

reset; touch "$st/down"; run "$line"
check "roborev down: unguarded pass" 0 "$rc"
has "warns when down" "$out" "WARNING"

reset; run "refs/tags/0.2.23 $SHA refs/tags/0.2.23 $ZERO"
check "tag push: pass" 0 "$rc"

reset; run "refs/tags/0.2.23 $SHA refs/heads/feat $ZERO"
check "tag source pushed to a branch ref: still checked, refused" 1 "$rc"

reset; run "(delete) $ZERO refs/heads/feat $SHA"
check "branch delete: pass" 0 "$rc"

reset; out=$(printf '%s\n' "$line" | STU_SKIP_ROBOREV_PUSH_GUARD=1 PATH="$bin:$PATH" bash "$guard" 2>&1); rc=$?
check "human override: pass" 0 "$rc"
has "override is announced" "$out" "skipped"

reset; done_at "$SHA"; run "$SHA $SHA refs/heads/feat $ZERO"
check "bare-sha source pushed to a branch ref: pass" 0 "$rc"

exit $fail
