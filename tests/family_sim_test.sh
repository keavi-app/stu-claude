#!/usr/bin/env bash
# Two-repo family simulation: a public report-only repo (app, before-push) and a private
# direct-push repo (lib, tagged by stu), real git repos with bare remotes under a temp dir, the
# real bin/ wrappers, the real git pre-push hook, the shared fake `gh` (tests/fake_gh.py), a
# temp HOME. Nothing outside the temp dir is touched and nothing is pushed anywhere else.
# Requires jq. Cases print `ok   <name>` / `FAIL <name>`; exit 1 if any failed.
set -euo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; T="$(cd -P "$T" && pwd -P)"; trap 'rm -rf "$T"' EXIT
command -v jq >/dev/null || { echo "family_sim_test: jq not installed"; exit 1; }
B="$KIT/bin"
STARTED=$(date +%s)

mkdir -p "$T/home" "$T/bin" "$T/x" "$T/remotes" "$T/wt"
ln -s "$KIT/tests/fake_gh.py" "$T/bin/gh"
printf '[init]\n\tdefaultBranch = main\n' > "$T/home/.gitconfig"
for v in $(env | sed -n 's/^\(GIT_[A-Z_]*\)=.*/\1/p'); do unset "$v"; done
unset STU_CONFIG STU_ENV_CMD RUN_CLAIMS_FILE CLAUDECODE  # the baseline is a human; agent pushes set it
export HOME="$T/home" GIT_CONFIG_GLOBAL="$T/home/.gitconfig" GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=T GIT_AUTHOR_EMAIL=t@e GIT_COMMITTER_NAME=T GIT_COMMITTER_EMAIL=t@e
export PATH="$T/bin:$PATH" FAKE_GH_FIXTURES="$T/fx.json" FAKE_GH_STATE="$T/ghstate"
export STU_FORGE_REQUERY_DELAY=0
FX="$T/fx.json"

# ---- counters and assertions ----
PASSES=0; FAILS=0
ok() { PASSES=$((PASSES + 1)); echo "ok   $1"; }
bad() { FAILS=$((FAILS + 1)); echo "FAIL $1"; }
check() {  # name got want
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1: got '$2', want '$3'"; fi
}
check_has() {  # name haystack needle
  case "$2" in *"$3"*) ok "$1" ;; *) bad "$1: '$3' not in '$2'" ;; esac
}

# ---- fake gh fixtures (builders copied from tests/ci_wait_test.sh) ----
rsp() { jq -cn --argjson j "$1" '{rc:0,json:$j}'; }
fx_reset() { echo '{}' > "$FX"; rm -f "$T/ghstate"; }
fx_put() { jq -c --arg k "$1" --argjson v "$2" '.[$k]=$v' "$FX" > "$FX.tmp" && mv "$FX.tmp" "$FX"; }
put_pr_doc() {  # pr slug head [state] [base] [merge-oid] [labels-json]
  local pr="$1" sl="$2" head="$3" state="${4:-OPEN}" base="${5:-main}" merge="${6:-}" labels="${7:-[]}"
  fx_put "pr view $pr" "$(rsp "$(jq -cn --arg sha "$head" --arg st "$state" --arg sl "$sl" --argjson n "$pr" \
    --arg base "$base" --arg m "$merge" --argjson l "$labels" \
    '{state:$st,headRefName:"b",headRefOid:$sha,baseRefName:$base,
      mergeCommit:(if $m=="" then null else {oid:$m} end),labels:$l,autoMergeRequest:null,
      url:("https://github.com/"+$sl+"/pull/"+($n|tostring)),mergeable:"MERGEABLE",mergeStateStatus:"CLEAN"}')")"
}
cr() {  # name conclusion id
  jq -cn --arg n "$1" --arg c "$2" --argjson id "$3" \
    '{id:$id,name:$n,status:"completed",conclusion:$c,details_url:"",app:{slug:"github-actions"},output:{title:""}}'
}

# ---- git helpers ----
g() { git -C "$@"; }
mkbare() { git init -q --bare -b main "$T/remotes/$1.git"; }
forge() { "$B/stu-forge" "$@"; }

# ---- the world: app (public, report-only, before-push) and lib (private, direct-push) ----
APP="$T/x/app"; LIB="$T/x/lib"; W="$T/wt/lib-1"
git init -q -b main "$APP"; echo init > "$APP/Package.resolved"
g "$APP" add Package.resolved; g "$APP" commit -qm init
mkbare app; g "$APP" remote add origin "$T/remotes/app.git"; g "$APP" push -q origin main
git init -q -b main "$LIB"; mkdir "$LIB/src"; echo 'x = 1' > "$LIB/src/module_a.py"
g "$LIB" add .; g "$LIB" commit -qm init
mkbare lib; g "$LIB" remote add origin "$T/remotes/lib.git"; g "$LIB" push -q origin main
g "$LIB" tag -a 1.4.0 -m 1.4.0; g "$LIB" push -q origin refs/tags/1.4.0
g "$LIB" worktree add -q "$W" -b feat

RH="$T/home/.stu/fam"; CFG="$RH/stu.md"; mkdir -p "$RH"
fam_cfg() {  # app-merge-mode  app-extra-line  lib-tag_by
  cat <<CFG
---
owner: o
---

## repos
### app
slug: acme/app
remote: origin
base: main
visibility: public
mode: work
merge_mode: $1
ci: none
$2
pin_files: Package.resolved
path: $APP

### lib
slug: acme/lib
remote: origin
base: main
visibility: private
mode: work
merge_mode: direct-push
ci: none
tag_by: $3
tag_format: {version}
path: $LIB

## verification-commands
\`\`\`
true
\`\`\`

## verification-commands @lib
\`\`\`
true
test ! -e BROKEN
\`\`\`
CFG
}
fam_cfg report-only "human_checkpoints: before-push" stu > "$CFG"
HUMAN="$T/human/stu.md"; mkdir -p "$T/human"
fam_cfg report-only "human_checkpoints: before-push" human > "$HUMAN"
LABEL="$T/label/stu.md"; mkdir -p "$T/label"
fam_cfg label-handoff "ci_merge_label: go" stu > "$LABEL"
REPORT="$T/report/stu.md"; mkdir -p "$T/report"
fam_cfg report-only "ci_merge_label: go" stu > "$REPORT"

# The hook goes in after the first push: a before-push row refuses every unapproved push.
"$B/stu-pre-push" --install --path "$APP" >/dev/null

# ---- run-check helpers ----
OBJ="$T/objective.md"; RET="$T/return.txt"; OUT=""; RC=0
objv() {  # rows(newline-separated '| id | repo | after |') [scoreboard-lines] [extra]
  { printf '# Objective: sim\n\nWritten 2026-10-26. Mode: plain.\n%s\n\n## Units\n\n' "${3:-}"
    printf '| ID | Repo | After |\n|---|---|---|\n%s\n' "$1"
    printf '\n## Scoreboard\n\nUnits issued: %s\n%s\n' \
      "$(printf '%s\n' "$1" | awk -F'|' '{gsub(/ /,"",$2); printf "%s%s", (n++ ? ", " : ""), $2}')" "${2:-}"; } > "$OBJ"
}
retv() {  # 'FIELD: value'...
  { printf 'STATUS: CONTINUE\nCYCLE: 1\n'; printf '%s\n' "$@"; } > "$RET"
}
runchk() { RC=0; OUT=$("$B/stu-run-check" --objective "$OBJ" --return "$RET" 2>"$T/err") || RC=$?; }
st() { printf '%s\n' "$OUT" | awk -v id="$1" '$1==id{r=$3; if ($2=="BLOCKED") sub(/:.*/,"",r); print $2" "r; exit}'; }
term() { printf '%s\n' "$OUT" | tail -n 1; }

# ---- lib helpers ----
LN=0; LANDED=""; TAGNAME=""
land_lib() {  # commit message -> LANDED (a commit landed on lib's base via the compare-and-swap push)
  LN=$((LN + 1)); echo "$LN" > "$W/f$LN.txt"; g "$W" add "f$LN.txt"; g "$W" commit -qm "$1"
  local s b; s=$(g "$W" rev-parse HEAD); b=$(g "$W" ls-remote origin refs/heads/main | cut -f1)
  forge push-if-base-equals --path "$W" --remote origin --base main --sha "$s" --expect "$b" >/dev/null
  LANDED="$s"
}
gate_tag() {  # sha -> TAGNAME: the gate's tag sequence (tag-for, else next-version + tag-create)
  local o n
  o=$(forge tag-for --path "$W" --remote origin --sha "$1" --format '{version}')
  n=$(printf '%s\n' "$o" | awk '$1=="TAG" && $2!="NONE"{print $2}')
  if [ -z "$n" ]; then
    n=$(forge next-version --path "$W" --remote origin --sha "$1" --format '{version}' | awk '$1=="VERSION"{print $2}')
    forge tag-create --path "$W" --remote origin --sha "$1" --name "$n" --message "$n" >/dev/null
  fi
  TAGNAME="$n"
}
tags_at() {  # sha -> number of distinct tag names peeling to it on the remote
  git ls-remote --tags "$T/remotes/lib.git" | awk -v s="$1" '$1==s && $2 ~ /\^\{\}$/{print $2}' | sort -u | wc -l | tr -d ' '
}
app_branch() {  # name -> prints the sha of a new unpushed commit on a side branch of app
  g "$APP" checkout -q -b "$1" main
  echo "$1" > "$APP/$1.txt"; g "$APP" add "$1.txt"; g "$APP" commit -qm "$1"
  g "$APP" rev-parse HEAD; g "$APP" checkout -q main
}
pin_commit() {  # message line... -> prints the sha of a commit on app main changing the pin file
  local m="$1"; shift
  printf '%s\n' "$@" > "$APP/Package.resolved"; g "$APP" add Package.resolved; g "$APP" commit -qm "$m"
  g "$APP" rev-parse HEAD
}
PUSHRC=0; PUSHERR=""
app_push() { PUSHRC=0; PUSHERR=$(CLAUDECODE=1 g "$APP" push origin main 2>&1) || PUSHRC=$?; }
verdict() { if [ "$1" -ne 0 ]; then echo refused; else echo pushed; fi; }
H40=$(printf 'a%.0s' $(seq 40)); H40B=$(printf 'b%.0s' $(seq 40)); H40C=$(printf 'c%.0s' $(seq 40))

# ============================================================================================
# sibling_resolution
# ============================================================================================
E=$(cd "$W" && "$B/stu-env" 2>/dev/null)
envv() { printf '%s\n' "$E" | sed -n "s/^$1=//p" | head -1; }
check "sibling_resolution: main checkout" "$(envv MAIN_CHECKOUT)" "$(cd -P "$LIB" && pwd -P)"
check "sibling_resolution: family run home" "$(envv RUN_HOME)" "$RH"
check "sibling_resolution: merge mode" "$(envv MERGE_MODE)" "direct-push"
check "sibling_resolution: row" "$(envv REPO_NAME)" "lib"
check "sibling_resolution: not home" "$(envv IS_HOME)" "0"
check "sibling_resolution: resolved by discovery" "$(env | grep -c '^STU_CONFIG=')" "0"

# ============================================================================================
# lib_direct_push_tag_and_retry
# ============================================================================================
land_lib $'Add the first change\n\nRelease: patch'; C1="$LANDED"
check "lib_direct_push: remote main is the landed sha" "$(git ls-remote "$T/remotes/lib.git" refs/heads/main | cut -f1)" "$C1"
check_has "lib_direct_push: landed" "$(forge landed --path "$W" --remote origin --base main --sha "$C1" --branch feat)" "LANDED $C1"
gate_tag "$C1"; check "lib_direct_push: first tag" "$TAGNAME" "1.4.1"
check "lib_direct_push: tag peels to the landed sha" \
  "$(git ls-remote --tags "$T/remotes/lib.git" | awk '$2=="refs/tags/1.4.1^{}"{print $1}')" "$C1"
gate_tag "$C1"; check "lib_direct_push: retry reuses the tag" "$TAGNAME" "1.4.1"
check "lib_direct_push: exactly one tag at the landed sha" "$(tags_at "$C1")" "1"

# ============================================================================================
# tag_collision_refused
# ============================================================================================
land_lib $'Add the second change\n\nRelease: patch'; C2="$LANDED"
NEXT=$(forge next-version --path "$W" --remote origin --sha "$C2" --format '{version}' | awk '$1=="VERSION"{print $2}')
check "tag_collision: next version" "$NEXT" "1.4.2"
git clone -q "$T/remotes/lib.git" "$T/x/lib-other"
g "$T/x/lib-other" tag -a "$NEXT" "$C1" -m "concurrent tagger"
g "$T/x/lib-other" push -q origin "refs/tags/$NEXT"
CONC=$(git ls-remote --tags "$T/remotes/lib.git" | awk -v t="refs/tags/$NEXT^{}" '$2==t{print $1}')
RCX=0; OUTX=$(forge tag-create --path "$W" --remote origin --sha "$C2" --name "$NEXT" --message "$NEXT" 2>&1) || RCX=$?
check "tag_collision: refused" "$RCX" "3"
check_has "tag_collision: reason" "$OUTX" "ERROR tag-exists"
check "tag_collision: remote tag unchanged" \
  "$(git ls-remote --tags "$T/remotes/lib.git" | awk -v t="refs/tags/$NEXT^{}" '$2==t{print $1}')" "$CONC"

# ============================================================================================
# app: the hook enforces real pushes
# ============================================================================================
check "app_hook: installed" "$("$B/stu-pre-push" --check --path "$APP")" "INSTALLED"
PIN1=$(pin_commit "Bump the library pin" "lib https://github.com/acme/lib.git $H40 version 1.4.1")
app_push
check "app_pin_bump_unapproved_refused: push fails" "$(verdict $PUSHRC)" "refused"
check_has "app_pin_bump_unapproved_refused: says not approved" "$PUSHERR" "is not approved"
# A forced internal error (an unreadable approvals record) must refuse too, never wave through.
mkdir "$RH/approvals.tsv"
app_push
check "app_pin_bump_unapproved_refused: internal error refuses" "$(verdict $PUSHRC)" "refused"
check_has "app_pin_bump_unapproved_refused: names the internal error" "$PUSHERR" "internal error"
rmdir "$RH/approvals.tsv"
check "app_pin_bump_unapproved_refused: remote still at the initial commit" \
  "$(git ls-remote "$T/remotes/app.git" refs/heads/main | cut -f1)" "$(g "$APP" rev-parse origin/main)"

(cd "$APP" && "$B/stu-approve" app#1 "$PIN1") >/dev/null
app_push
check "app_pin_bump_approved_allowed: push lands" "$PUSHRC" "0"
check "app_pin_bump_approved_allowed: remote is the approved sha" \
  "$(git ls-remote "$T/remotes/app.git" refs/heads/main | cut -f1)" "$PIN1"

# Approval never excuses a leak: a private path, then an issue reference to the private repo.
PIN2=$(pin_commit "Pin bump with a path" "lib https://github.com/acme/lib.git $H40B uses module_a.py")
(cd "$APP" && "$B/stu-approve" app#1 "$PIN2") >/dev/null
app_push
check "app_leak_refused_even_when_approved: private path in a pin file" "$(verdict $PUSHRC)" "refused"
check_has "app_leak_refused_even_when_approved: names the path" "$PUSHERR" "module_a.py"
g "$APP" reset -q --hard "$PIN1"
PIN3=$(pin_commit "Pin bump with a reference" "lib https://github.com/acme/lib.git $H40C see acme/lib#9")
(cd "$APP" && "$B/stu-approve" app#1 "$PIN3") >/dev/null
app_push
check "app_leak_refused_even_when_approved: issue reference in a pin file" "$(verdict $PUSHRC)" "refused"
check_has "app_leak_refused_even_when_approved: names the reference" "$PUSHERR" "acme/lib#9"
g "$APP" reset -q --hard "$PIN1"
echo "notes" > "$APP/notes.txt"; g "$APP" add notes.txt
g "$APP" commit -qm "work around acme/lib#12"; MSGSHA=$(g "$APP" rev-parse HEAD)
(cd "$APP" && "$B/stu-approve" app#1 "$MSGSHA") >/dev/null
app_push
check "app_leak_refused_even_when_approved: message reference" "$(verdict $PUSHRC)" "refused"
g "$APP" reset -q --hard "$PIN1"

# A scripted push goes through the same hook.
pin_commit "Another bump" "lib https://github.com/acme/lib.git $H40B version 1.4.2" >/dev/null
cat > "$T/script-push.sh" <<SCRIPT
#!/bin/sh
git -C "$APP" push origin main
SCRIPT
SRC=0; SERR=$(CLAUDECODE=1 sh "$T/script-push.sh" 2>&1) || SRC=$?
check "app_scripted_push_refused: push fails" "$(verdict $SRC)" "refused"
check_has "app_scripted_push_refused: from the hook" "$SERR" "is not approved"
g "$APP" reset -q --hard "$PIN1"

# A fresh clone has no hook.
git clone -q "$T/remotes/app.git" "$T/x/app-fresh"
check "app_hook_missing_detected" "$("$B/stu-pre-push" --check --path "$T/x/app-fresh" || true)" "MISSING"

# ============================================================================================
# run_check_dependent_order: app#1 after lib#1 (landed, tagged)
# ============================================================================================
land_lib $'Add the third change\n\nRelease: patch'; C3="$LANDED"
APPB_SHA=$(app_branch app-pin)
ROWS=$'| lib#1 | lib | - |\n| app#1 | app | lib#1 (landed, tagged) |'
SB1="Merged: lib#1@$C3"$'\n'"Closed: lib#1"
objv "$ROWS" "$SB1"; retv "CLOSED_IDS: app#1" "APPROVAL_IDS: app#1@app-pin@$APPB_SHA"
runchk
check "run_check_dependent_order: blocked before the tag" "$(st app#1)" "BLOCKED predecessor-not-tagged"
check "run_check_dependent_order: terminal BLOCKED" "$(term):$RC" "BLOCKED:1"
gate_tag "$C3"; T3="$TAGNAME"
objv "$ROWS" "$SB1"$'\n'"Tagged: lib#1=$T3@$C3"; runchk
check "run_check_dependent_order: closed after the tag" "$(st app#1)" "CLOSED approval-branch-at-sha"
check "run_check_dependent_order: terminal OK" "$(term):$RC" "OK:0"

# ============================================================================================
# waiting_claim_hold
# ============================================================================================
claims() { (cd "$APP" && "$B/stu-claims" "$@" 2>/dev/null); }
claims hold app#1 run1 >/dev/null
claims release run1 >/dev/null
check "waiting_claim_hold" "$(claims list --runs | grep -x 'run1 waiting' || true)" "run1 waiting"

# ============================================================================================
# lib_ci_none_gate_substitute
# ============================================================================================
"$B/stu-verify" --repo lib --sha "$C3" --start >/dev/null 2>&1
V1=$("$B/stu-verify" --repo lib --sha "$C3" --wait 30 2>/dev/null)
check_has "lib_ci_none_gate_substitute: passes at the landed sha" "$V1" "VERIFY: PASS sha=$C3 cmds=2 failed=none"
echo broken > "$W/BROKEN"; g "$W" add BROKEN; g "$W" commit -qm "Break the build"; CB=$(g "$W" rev-parse HEAD)
"$B/stu-verify" --repo lib --sha "$CB" --start >/dev/null 2>&1
V2=$("$B/stu-verify" --repo lib --sha "$CB" --wait 30 2>/dev/null) || true
check_has "lib_ci_none_gate_substitute: a failing command fails with its index" "$V2" "VERIFY: FAIL sha=$CB cmds=2 failed=2"
g "$W" reset -q --hard "$C3"

# ============================================================================================
# app_before_push_two_legs
# ============================================================================================
LEG_SHA=$(app_branch app-leg)
fx_reset
put_pr_doc 5 acme/app "$LEG_SHA" OPEN
UNIT=$'| app#2 | app | - |'
objv "$UNIT" ""; retv "CLOSED_IDS: app#2" "APPROVAL_IDS: app#2@app-leg@$LEG_SHA"; runchk
check "app_before_push_two_legs: leg 1 closes" "$(st app#2)" "CLOSED approval-branch-at-sha"
(cd "$APP" && "$B/stu-approve" app#2 "$LEG_SHA") >/dev/null
objv "$UNIT" "Awaiting approval: app#2@app-leg@$LEG_SHA"
A=$("$B/stu-run-check" --approved --objective "$OBJ" 2>/dev/null) || true
check_has "app_before_push_two_legs: the approval is listed" "$A" "app#2 APPROVED $LEG_SHA"
objv "$UNIT" ""; retv "CLOSED_IDS: app#2" "PASSED_IDS: app#2@acme/app#5@$LEG_SHA"; runchk
check "app_before_push_two_legs: leg 2 at the approved sha closes" "$(st app#2 | cut -d: -f1)" "CLOSED passed"
OTHER_SHA=$(app_branch app-leg-b)
put_pr_doc 5 acme/app "$OTHER_SHA" OPEN
retv "CLOSED_IDS: app#2" "PASSED_IDS: app#2@acme/app#5@$OTHER_SHA"; runchk
check "app_before_push_two_legs: leg 2 at another sha is blocked" "$(st app#2)" "BLOCKED leg2-unapproved"

# ============================================================================================
# predecessor_moved_head_blocked: app#3 passed at one head, the PR merged with another
# ============================================================================================
GATED=$(printf 'd%.0s' $(seq 40))
fx_reset; put_pr_doc 5 acme/app "$H40C" MERGED main "$PIN1"
ROWS=$'| app#3 | app | - |\n| lib#2 | lib | app#3 (landed) |'
objv "$ROWS" "Passed: app#3@acme/app#5@$GATED"$'\n'"Closed: app#3"
retv "CLOSED_IDS: lib#2" "MERGED_IDS: lib#2@$C3"; runchk
check "predecessor_moved_head_blocked" "$(st lib#2)" "BLOCKED predecessor-moved-head"

# ============================================================================================
# human_tag_waiting: a tag_by human variant of lib
# ============================================================================================
land_lib $'Add the fourth change\n\nRelease: patch'; C4="$LANDED"
ROWS=$'| lib#5 | lib | - |\n| app#4 | app | lib#5 (landed, tagged) |'
objv "$ROWS" "Merged: lib#5@$C4"$'\n'"Closed: lib#5"
HB_SHA=$(app_branch app-human)
retv "WAITING_IDS: app#4 needs: tag lib at $C4"
STU_CONFIG="$HUMAN" runchk
check "human_tag_waiting: waits before the tag" "$(st app#4 | cut -d' ' -f1):$RC:$(term)" "WAITING:0:OK"
git clone -q "$T/remotes/lib.git" "$T/x/lib-human"
g "$T/x/lib-human" tag -a 1.5.0 "$C4" -m 1.5.0; g "$T/x/lib-human" push -q origin refs/tags/1.5.0
STU_CONFIG="$HUMAN" runchk
check "human_tag_waiting: no longer waiting once tagged" "$(st app#4)" "BLOCKED waiting-predecessor-landed"
retv "CLOSED_IDS: app#4" "APPROVAL_IDS: app#4@app-human@$HB_SHA"
STU_CONFIG="$HUMAN" runchk
check "human_tag_waiting: closes after the tag" "$(st app#4)" "CLOSED approval-branch-at-sha"

# ============================================================================================
# close_paths_by_mode
# ============================================================================================
# direct-push (lib): MERGED_IDS closes, PASSED_IDS is the wrong field.
objv $'| lib#7 | lib | - |' ""
retv "CLOSED_IDS: lib#7" "MERGED_IDS: lib#7@$C4"; runchk
check "close_paths_by_mode: direct-push closes on MERGED_IDS" "$(st lib#7 | cut -d' ' -f1)" "CLOSED"
fx_reset; put_pr_doc 6 acme/lib "$C4" OPEN
retv "CLOSED_IDS: lib#7" "PASSED_IDS: lib#7@acme/lib#6@$C4"; runchk
check "close_paths_by_mode: direct-push rejects PASSED_IDS" "$(st lib#7)" "BLOCKED wrong-field-for-mode"
# report-only (app, no before-push checkpoint in this variant): PASSED_IDS closes, MERGED_IDS is
# the wrong field.
APP_HEAD=$(app_branch app-pass)
fx_reset; put_pr_doc 7 acme/app "$APP_HEAD" OPEN
objv $'| app#8 | app | - |' ""
retv "CLOSED_IDS: app#8" "PASSED_IDS: app#8@acme/app#7@$APP_HEAD"
STU_CONFIG="$REPORT" runchk
check "close_paths_by_mode: report-only closes on PASSED_IDS" "$(st app#8 | cut -d' ' -f1)" "CLOSED"
retv "CLOSED_IDS: app#8" "MERGED_IDS: app#8@$PIN1"
STU_CONFIG="$REPORT" runchk
check "close_paths_by_mode: report-only rejects MERGED_IDS" "$(st app#8)" "BLOCKED wrong-field-for-mode"
# label-handoff (app in the label variant): READY_IDS closes, MERGED_IDS is the wrong field.
fx_reset; put_pr_doc 8 acme/app "$APP_HEAD" OPEN main "" '[{"name":"go"}]'
objv $'| app#9 | app | - |' "" "completion: ready"
retv "CLOSED_IDS: app#9" "READY_IDS: app#9@acme/app#8@$APP_HEAD"
STU_CONFIG="$LABEL" runchk
check "close_paths_by_mode: label-handoff closes on READY_IDS" "$(st app#9 | cut -d' ' -f1)" "CLOSED"
retv "CLOSED_IDS: app#9" "MERGED_IDS: app#9@$PIN1"
STU_CONFIG="$LABEL" runchk
check "close_paths_by_mode: label-handoff rejects MERGED_IDS" "$(st app#9)" "BLOCKED wrong-field-for-mode"
# Under completion: merged a labelled, unlanded PR is tracked in READY_IDS beside REMAINING_IDS.
objv $'| app#9 | app | - |' "" "completion: merged"
retv "REMAINING_IDS: app#9" "READY_IDS: app#9@acme/app#8@$APP_HEAD"
STU_CONFIG="$LABEL" runchk
check "close_paths_by_mode: label-handoff tracks READY_IDS under merged" \
  "$RC $(st app#9 | cut -d' ' -f1) $(printf '%s\n' "$OUT" | tail -1)" "0 OPEN OK"

# ============================================================================================
# flat_label_handoff_unchanged: the one-row regression (switchover guard)
# ============================================================================================
FLAT="$T/flat"; EPIC="epic/x"
git init -q -b main "$FLAT"; echo init > "$FLAT/README.txt"; g "$FLAT" add .; g "$FLAT" commit -qm init
mkbare flat; g "$FLAT" remote add origin "$T/remotes/flat.git"; g "$FLAT" push -q origin main
g "$FLAT" checkout -q -b "$EPIC"; g "$FLAT" push -q origin "$EPIC"
g "$FLAT" checkout -q -b b; echo w > "$FLAT/w.txt"; g "$FLAT" add w.txt; g "$FLAT" commit -qm work
FHEAD=$(g "$FLAT" rev-parse HEAD)
mkdir -p "$FLAT/.claude"
cat > "$FLAT/.claude/stu.md" <<FLATCFG
---
owner: o
github_repo: o/r
ci_gate_check: build
ci_merge_label: go
---

## merge-mode

Mode: label-handoff. Label \`go\`.
FLATCFG
FLATCFGP="$FLAT/.claude/stu.md"
FRC=0; FE=$(cd "$FLAT" && STU_CONFIG="$FLATCFGP" "$B/stu-env" 2>/dev/null) || FRC=$?
fenv() { printf '%s\n' "$FE" | sed -n "s/^$1=//p" | head -1; }
check "flat: stu-env exits 0" "$FRC" "0"
check "flat: MERGE_MODE" "$(fenv MERGE_MODE)" "label-handoff"
check "flat: VISIBILITY unset" "$(fenv VISIBILITY)" "unset"
check "flat: one row" "$(fenv FAMILY_ROWS)" "1"

# stu-ci-wait on a PR into the epic branch
fx_reset
put_pr_doc 7 o/r aaa OPEN "$EPIC"
fx_put "api repos/o/r/commits/aaa/check-runs" "$(rsp "$(jq -cn --argjson r "[$(cr build success 1)]" '{check_runs:$r}')")"
fx_put "api repos/o/r/commits/aaa/statuses" "$(rsp '[[]]')"
fx_put "api repos/o/r/rules/branches/$EPIC" '{"rc":0,"json":[[]]}'
CIW=$(cd "$FLAT" && STU_CONFIG="$FLATCFGP" "$B/stu-ci-wait" --slug o/r --pr 7 --interval 1 --timeout 10 2>/dev/null) || true
check_has "flat: stu-ci-wait on an epic-branch PR" "$CIW" "CI: PASS pr=7 sha=aaa"

# gate-preflight against the epic base
put_pr_doc 7 o/r "$FHEAD" OPEN "$EPIC"
PF=$(forge gate-preflight --path "$FLAT" --slug o/r --base "$EPIC" --pr 7 2>&1) || true
check_has "flat: gate-preflight --base epic passes" "$PF" "PREFLIGHT ok"

# stu-run-check closes a READY_IDS unit and a no-PR CLOSED_IDS unit
fx_reset; put_pr_doc 7 o/r "$FHEAD" OPEN "$EPIC" "" '[{"name":"go"}]'
{ printf '# Objective: flat\n\nWritten 2026-10-26. Mode: plain.\nBase branch: %s\ncompletion: ready\n\n## Units\n\n' "$EPIC"
  printf '| ID | What it is | Contended resource |\n|---|---|---|\n| 101 | the thing | src/ |\n| 102 | the other | docs/ |\n'
  printf '\n## Scoreboard\n\nUnits issued: 101, 102\n'; } > "$OBJ"
retv "CLOSED_IDS: 101, 102" "READY_IDS: 101@o/r#7@$FHEAD"
FRCK=0; OUT=$(cd "$FLAT" && STU_CONFIG="$FLATCFGP" "$B/stu-run-check" --objective "$OBJ" --return "$RET" 2>/dev/null) || FRCK=$?
check "flat: stu-run-check exits 0" "$FRCK" "0"
check "flat: READY_IDS unit closes" "$(st 101 | cut -d, -f1)" "CLOSED ready-labelled:o/r#7"
check "flat: no-PR unit closes" "$(st 102)" "CLOSED no-pr"

# the publish guard allows the flat flows
guard() {  # json payload -> its stdout
  printf '%s' "$1" | (cd "$FLAT" && STU_CONFIG="$FLATCFGP" sh "$KIT/hooks/publish-guard.sh" 2>&1)
}
pl_bash() { jq -cn --arg c "$1" --arg cwd "$FLAT" '{session_id:"s",cwd:$cwd,hook_event_name:"PreToolUse",tool_name:"Bash",tool_input:{command:$c}}'; }
pl_write() { jq -cn --arg p "$1" --arg cwd "$FLAT" '{session_id:"s",cwd:$cwd,hook_event_name:"PreToolUse",tool_name:"Write",tool_input:{file_path:$p,content:"x = 1\n"}}'; }
check "flat: gh pr create with a heredoc body allowed" \
  "$(guard "$(pl_bash $'gh pr create --title t --body "$(cat <<\'EOF\'\nsummary\nEOF\n)"')")" ""
check "flat: git -C push allowed" "$(guard "$(pl_bash "git -C \"$FLAT\" push")")" ""
check "flat: push --no-verify allowed" "$(guard "$(pl_bash "git push --no-verify")")" ""
check "flat: unrelated approvals.py write allowed" "$(guard "$(pl_write "$FLAT/approvals.py")")" ""
check_has "flat: a write to the approvals file itself is denied (control)" \
  "$(guard "$(pl_write "$FLAT/approvals.tsv")")" '"permissionDecision": "deny"'
# no pre-push hook is required or installed
check "flat: no hook installed" "$(cd "$FLAT" && STU_CONFIG="$FLATCFGP" "$B/stu-pre-push" --check 2>/dev/null || true)" "MISSING"
check "flat: no hook file" "$([ -e "$FLAT/.git/hooks/pre-push" ] && echo present || echo absent)" "absent"
HOOKRC=0; printf 'refs/heads/b %s refs/heads/b %s\n' "$FHEAD" "$(printf '0%.0s' $(seq 40))" \
  | (cd "$FLAT" && STU_CONFIG="$FLATCFGP" "$B/stu-pre-push" origin "$T/remotes/flat.git") >/dev/null 2>&1 || HOOKRC=$?
check "flat: the hook entry allows a push" "$HOOKRC" "0"

# ============================================================================================
echo "family_sim_test: $PASSES ok, $FAILS failed, $(( $(date +%s) - STARTED )) s"
[ "$FAILS" -eq 0 ]
