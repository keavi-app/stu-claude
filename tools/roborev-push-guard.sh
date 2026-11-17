#!/usr/bin/env bash
# RoboRev push guard: refuse a branch push until RoboRev is clean for the pushed SHA.
# Order is commit -> RoboRev clean -> push (once) -> PR.
#
# Reads git's pre-push lines (<local ref> <local sha> <remote ref> <remote sha>) on stdin.
# Refuses a branch push when any of:
#   1. `roborev fix --list --branch <b>` reports an open job;
#   2. a queued or running review job exists for the pushed SHA;
#   3. no `done` review job exists for the pushed SHA (never reviewed, or only failed).
# Passes: deletes, pushes whose destination is a tag (a tag names a commit already on a
# branch), and
# STU_SKIP_ROBOREV_PUSH_GUARD=1 (humans only; agents never set it).
# Fails open, loudly, when roborev is absent or a query fails or prints something unknown:
# the push proceeds with a warning, and the pusher confirms review state by hand.
#
# The branch reviewed is the pushed source ref when it is refs/heads/*, else the destination
# ref when that is refs/heads/* (`git push keavi <sha>:refs/heads/b`).
#
# Exit: 0 pass (or unguarded), 1 refused.

set -u

ZERO=0000000000000000000000000000000000000000
RC=0
WARNED=0
REASON=""

warn_unguarded() {
    if [ "$WARNED" = 0 ]; then
        {
            echo "WARNING: the RoboRev push guard could NOT check this push ($1)."
            echo "         The push is proceeding unguarded. Confirm review state by hand:"
            echo "         roborev job list --branch <branch>"
        } >&2
    fi
    WARNED=1
}

refuse() { # branch sha reason
    {
        echo "REFUSED: RoboRev is not clean for this push."
        echo "  branch: $1"
        echo "  sha:    $2"
        echo "  rule:   $3"
        echo "Inspect (read-only): roborev fix --list --branch $1"
        echo "                     roborev job list --branch $1"
        echo "Human override: STU_SKIP_ROBOREV_PUSH_GUARD=1 git push ..."
    } >&2
    RC=1
}

push_branch() { # local_ref remote_ref -> branch name to review
    case "$1" in refs/heads/*) printf '%s\n' "${1#refs/heads/}"; return ;; esac
    case "$2" in refs/heads/*) printf '%s\n' "${2#refs/heads/}"; return ;; esac
    printf '%s\n' "${1#refs/heads/}"
}

# clean_status <branch> <full sha>: 0 clean, 1 dirty, 2 unknown; REASON says why.
# Each query's exit status is taken first: a nonzero exit is unknown whatever it printed.
# `fix --list` writes both of its forms to stderr, so it is read with stderr merged; the
# `job list --json` queries keep stderr out of the JSON; `--limit 0` lists every job, so an old
# branch's reviewed SHA is never cut off by a page size.
clean_status() {
    local branch="$1" sha="$2" out status
    REASON=""
    if ! command -v roborev > /dev/null 2>&1; then
        REASON="roborev is not on PATH"
        return 2
    fi
    out=$(roborev fix --list --branch "$branch" 2>&1 </dev/null) || {
        REASON="roborev fix --list failed"
        return 2
    }
    if grep -qE 'Found [0-9]+ open job' <<<"$out"; then
        REASON="open review job on the branch (roborev fix --list reports findings)"
        return 1
    fi
    # Only the known empty form is clean. Anything else is unknown, never a quiet pass.
    if ! grep -qF 'No open jobs found' <<<"$out"; then
        REASON="roborev fix --list printed text this check does not recognise"
        return 2
    fi
    for status in queued running; do
        out=$(roborev job list --branch "$branch" --status "$status" --json --limit 0 2>/dev/null </dev/null) || {
            REASON="roborev job list --status $status failed"
            return 2
        }
        if grep -qE "\"git_ref\": *\"$sha\"" <<<"$out"; then
            REASON="a $status review job exists for this SHA; wait for it (roborev job wait $sha)"
            return 1
        fi
    done
    out=$(roborev job list --branch "$branch" --status done --json --limit 0 2>/dev/null </dev/null) || {
        REASON="roborev job list --status done failed"
        return 2
    }
    if ! grep -qE "\"git_ref\": *\"$sha\"" <<<"$out"; then
        REASON="no done review job for this SHA (never reviewed, or only failed)"
        return 1
    fi
    return 0
}

if [ "${STU_SKIP_ROBOREV_PUSH_GUARD:-}" = 1 ]; then
    echo "STU_SKIP_ROBOREV_PUSH_GUARD=1: RoboRev push guard skipped." >&2
    cat > /dev/null
    exit 0
fi

while read -r local_ref local_sha remote_ref remote_sha; do
    [ -n "${local_ref:-}" ] || continue
    [ "$local_sha" != "$ZERO" ] || continue
    # The destination decides: a tag source pushed to a branch ref still lands commits there.
    case "$remote_ref" in refs/tags/*) continue ;; esac
    branch=$(push_branch "$local_ref" "$remote_ref")
    clean_status "$branch" "$local_sha"
    case $? in
        0) ;;
        1) refuse "$branch" "$local_sha" "$REASON" ;;
        *) warn_unguarded "$REASON" ;;
    esac
done

exit "$RC"
