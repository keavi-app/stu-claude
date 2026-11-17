#!/usr/bin/env bash
# Usage: tools/tag-release.sh run|check [remote] [branch]   (defaults: keavi main)
# The merge gate's `tag-release` after-pass step. Run from the unit's worktree.
#
# The version is the one in this checkout's .claude-plugin/plugin.json (the unit's own). The
# tag target is the first commit on <remote>/<branch> whose plugin.json carries that version:
# the commit that landed the bump, whatever has landed after it. Tags are plain <version>.
#   run    create the annotated tag at the target if it is missing locally, then push it
#   check  exit 0 only when the remote tag exists and peels to the target
# Exits 1 when the version is not on <remote>/<branch> yet, when a tag of that name already
# names another commit, or on any git failure. Never moves an existing tag.
set -u
mode="${1:-}"; remote="${2:-keavi}"; branch="${3:-main}"
case "$mode" in run|check) ;; *) echo "usage: tools/tag-release.sh run|check [remote] [branch]" >&2; exit 2 ;; esac

ver_of() { # <rev>: the plugin.json version at <rev>, empty when unreadable
    git show "$1:.claude-plugin/plugin.json" 2>/dev/null |
        python3 -c 'import json,sys;print(json.load(sys.stdin)["version"])' 2>/dev/null
}

v=$(ver_of HEAD)
[ -n "$v" ] || { echo "tag-release: cannot read the version from .claude-plugin/plugin.json" >&2; exit 1; }
git fetch -q "$remote" "$branch" || { echo "tag-release: fetch $remote $branch failed" >&2; exit 1; }

target=""
for h in $(git log --reverse --format=%H "$remote/$branch" -- .claude-plugin/plugin.json); do
    if [ "$(ver_of "$h")" = "$v" ]; then target=$h; break; fi
done
[ -n "$target" ] || { echo "tag-release: version $v is not on $remote/$branch yet" >&2; exit 1; }

remote_peel() {
    git ls-remote --tags "$remote" "refs/tags/$v" "refs/tags/$v^{}" |
        awk -v t="refs/tags/$v" '$2==t"^{}"{p=$1} $2==t{l=$1} END{print (p!="")?p:l}'
}

if [ "$mode" = check ]; then
    got=$(remote_peel) || exit 1
    [ "$got" = "$target" ] && exit 0
    echo "tag-release: remote tag $v ${got:+is at $got, }expected at $target" >&2
    exit 1
fi

local_peel=$(git rev-parse -q --verify "refs/tags/$v^{commit}" 2>/dev/null || true)
if [ -z "$local_peel" ]; then
    git tag -a "$v" -m "$v" "$target" || exit 1
elif [ "$local_peel" != "$target" ]; then
    echo "tag-release: local tag $v is at $local_peel, not $target; refusing to move it" >&2
    exit 1
fi
git push -q "$remote" "refs/tags/$v" || exit 1
[ "$(remote_peel)" = "$target" ] || { echo "tag-release: pushed tag $v does not peel to $target" >&2; exit 1; }
echo "tag-release: $v -> $target"
