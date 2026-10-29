#!/usr/bin/env bash
# Drives scripts/ci-wait.sh through the real bin/stu-forge against the shared fake `gh`
# (tests/fake_gh.py) and checks the ONE line it prints. Fixtures are raw forge JSON; a
# response list models a PR that changes while the script waits. Requires jq.
set -euo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
command -v jq >/dev/null || { echo "ci_wait_test: jq not installed"; exit 1; }

mkdir -p "$T/bin" "$T/home" "$T/cwd"
ln -s "$KIT/tests/fake_gh.py" "$T/bin/gh"
FX="$T/fx.json"; STATE="$T/state.json"; GHLOG="$T/gh.log"
SL=o/r        # the slug fixtures are keyed on

# ---- fixture builders ----
rsp() { jq -cn --argjson j "$1" '{rc:0,json:$j}'; }
fx_reset() { echo '{}' > "$FX"; rm -f "$STATE" "$GHLOG"; }
fx_put() { jq -c --arg k "$1" --argjson v "$2" '.[$k]=$v' "$FX" > "$FX.tmp" && mv "$FX.tmp" "$FX"; }
prdoc() {  # sha [mergeable] [state] [labels-json] [auto-json] [head-ref]
  jq -cn --arg sha "$1" --arg m "${2:-MERGEABLE}" --arg st "${3:-OPEN}" --argjson l "${4:-[]}" \
    --argjson a "${5:-null}" --arg ref "${6:-b}" --arg sl "$SL" \
    '{state:$st,headRefName:$ref,headRefOid:$sha,baseRefName:"main",mergeCommit:null,labels:$l,
      autoMergeRequest:$a,url:("https://github.com/"+$sl+"/pull/7"),mergeable:$m,mergeStateStatus:"CLEAN"}'
}
put_pr() { fx_put "pr view 7" "$(rsp "$(prdoc "$@")")"; }
cr() {  # name conclusion id [url] [app] [status]
  jq -cn --arg n "$1" --arg c "$2" --argjson id "$3" --arg url "${4:-}" --arg app "${5:-github-actions}" \
    --arg s "${6:-completed}" '{id:$id,name:$n,status:$s,conclusion:(if $c=="" then null else $c end),
      details_url:$url,app:{slug:$app},output:{title:""}}'
}
run_url() { printf 'https://github.com/%s/actions/runs/%s/job/%s' "$SL" "$1" "$2"; }
runs_resp() { rsp "$(jq -cn --argjson r "[${1:-}]" '{check_runs:$r}')"; }
put_runs() { fx_put "api repos/$SL/commits/aaa/check-runs" "$(runs_resp "${1:-}")"; }
st() {  # context state
  jq -cn --arg c "$1" --arg s "$2" '{context:$c,state:$s,creator:{login:"bot"},updated_at:"2026-01-01T00:00:00Z",description:""}'
}
put_stats() { fx_put "api repos/$SL/commits/aaa/statuses" "$(rsp "[[${1:-}]]")"; }
put_rules() {  # names... (none: no rules at all)
  local ctx="[]" n
  for n in "$@"; do ctx=$(jq -c --arg n "$n" '. + [{context:$n}]' <<< "$ctx"); done
  if [ $# -eq 0 ]; then fx_put "api repos/$SL/rules/branches/main" '{"rc":0,"json":[[]]}'
  else fx_put "api repos/$SL/rules/branches/main" "$(rsp "$(jq -cn --argjson c "$ctx" '[[{type:"required_status_checks",parameters:{required_status_checks:$c}}]]')")"; fi
}
put_run() {  # run-id head-sha job-json...  (run view + jobs)
  local id="$1" sha="$2"; shift 2
  fx_put "run view $id" "$(rsp "{\"headSha\":\"$sha\"}")"
  fx_put "api repos/$SL/actions/runs/$id/jobs" "$(rsp "$(jq -cn --argjson j "[$(IFS=,; echo "$*")]" '{jobs:$j}')")"
}
job() { jq -cn --arg n "$1" --arg c "$2" '{id:1,status:"completed",conclusion:$c,name:$n}'; }
base_fx() { fx_reset; put_pr aaa; put_runs; put_stats; put_rules; }

fails=0
# run_case NAME WANT-PREFIX ENV... -- ci-wait args...
run_case() {
  local name="$1" want="$2"; shift 2
  local envs=()
  while [ "$1" != "--" ]; do envs+=("$1"); shift; done; shift
  rm -f "$STATE" "$GHLOG"
  local got
  got=$(cd "$T/cwd" && env PATH="$T/bin:$PATH" HOME="$T/home" FAKE_GH_FIXTURES="$FX" FAKE_GH_STATE="$STATE" \
        FAKE_GH_LOG="$GHLOG" STU_FORGE_REQUERY_DELAY=0 STU_ENV_CMD=true ${envs[@]+"${envs[@]}"} \
        "$KIT/scripts/ci-wait.sh" --slug "$SL" --pr 7 --interval 1 "$@" 2>"$T/stderr")
  if [ "$(printf '%s\n' "$got" | wc -l | tr -d ' ')" != 1 ]; then
    echo "FAIL $name: expected exactly one line, got: $got"; fails=$((fails + 1)); return
  fi
  case "$got" in
    "$want"*) echo "ok   $name: $got" ;;
    *) echo "FAIL $name: want '${want}...', got '$got'"; fails=$((fails + 1)) ;;
  esac
}
pass() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fails=$((fails + 1)); }
expect_stderr() { grep -q -- "$2" "$T/stderr" && pass "$1: stderr names '$2'" || bad "$1: stderr lacks '$2': $(cat "$T/stderr")"; }
expect_log() { grep -q -- "$2" "$GHLOG" && pass "$1: gh saw '$2'" || bad "$1: gh never saw '$2'"; }
expect_no_log() { ! grep -q -- "$2" "$GHLOG" && pass "$1: gh never saw '$2'" || bad "$1: gh saw '$2'"; }

D="--mode daemon-status --status-prefix gate/"

# ---- daemon-status (ported) ----
base_fx; put_pr aaa MERGEABLE MERGED; put_stats "$(st gate/test success)"
run_case daemon-merged "CI: MERGED pr=7 sha=aaa" -- $D --timeout 5

base_fx; put_stats "$(st gate/test failure),$(st gate/lint error),$(st other/x failure),$(st gate/e2e pending)"
run_case daemon-fail "CI: FAIL pr=7 sha=aaa run=- verdict=none reruns=0 failed=gate/lint,gate/test" -- $D --timeout 5

# A quote in the prefix is data, not program text: it once broke the filter, the failure read
# as "nothing failed", and a red PR waited out to TIMEOUT.
base_fx; put_stats "$(st 'q"x/lint' failure)"
run_case daemon-quoted-prefix "CI: FAIL pr=7 sha=aaa run=- verdict=none reruns=0 failed=q\"x/lint" \
  -- --mode daemon-status --status-prefix 'q"x/' --timeout 3

base_fx; put_stats "$(st other/x failure),$(st gate/test pending)"
run_case daemon-ignores-other-prefix "CI: TIMEOUT pr=7 sha=aaa" -- $D --timeout 2

base_fx; put_pr aaa CONFLICTING
run_case daemon-conflict "CI: BLOCKED_CONFLICT pr=7 sha=aaa" -- $D --timeout 5

base_fx; put_stats "$(st gate/test pending)"
fx_put "pr view 7 @state" "[$(rsp "$(prdoc aaa)"),$(rsp "$(prdoc aaa)"),$(rsp "$(prdoc bbb)")]"
run_case daemon-sha-moved "CI: SHA_MOVED pr=7 sha=bbb" -- $D --timeout 20

base_fx; put_stats "$(st gate/test pending)"
run_case daemon-pending-timeout "CI: TIMEOUT pr=7 sha=aaa" -- $D --timeout 2

# The daemon mode refuses an empty prefix rather than gating on every context.
base_fx
if env PATH="$T/bin:$PATH" HOME="$T/home" FAKE_GH_FIXTURES="$FX" STU_ENV_CMD=true \
     "$KIT/scripts/ci-wait.sh" --slug "$SL" --pr 7 --mode daemon-status >/dev/null 2>&1; then
  bad "daemon-empty-prefix: accepted"
else pass "daemon-empty-prefix: refused"; fi

# ---- aggregator (ported) ----
base_fx; put_rules ci; put_runs "$(cr ci success 1 https://example.invalid/x)"
run_case checkrun-pass "CI: PASS pr=7 sha=aaa" -- --timeout 5
base_fx; put_pr aaa CONFLICTING
run_case checkrun-conflict "CI: BLOCKED_CONFLICT pr=7 sha=aaa" -- --timeout 5

# Actions-shaped URLs: the NEWEST run's verdict wins, whatever order the rollup lists them.
base_fx; put_rules ci; put_runs "$(cr ci success 2 "$(run_url 200 5)"),$(cr ci failure 1 "$(run_url 100 9)")"
put_run 200 aaa "$(job ci success)"
run_case checkrun-newest-wins "CI: PASS pr=7 sha=aaa run=200" -- --timeout 5
# A rerun keeps its run id; the later attempt is the newer one.
base_fx; put_rules ci; put_runs "$(cr ci failure 1 "$(run_url 300 1)"),$(cr ci success 2 "$(run_url 300 2)")"
put_run 300 aaa "$(job ci success)"
run_case checkrun-rerun-job "CI: PASS pr=7 sha=aaa run=300" -- --timeout 5
# A CANCELLED newest run is waited past, never read as a verdict and never fallen back from
# to an older run's green: with nothing newer arriving, the wait ends in TIMEOUT, naming the
# cancelled job as it always did.
base_fx; put_rules ci; put_runs "$(cr ci success 1 "$(run_url 100 1)"),$(cr ci cancelled 2 "$(run_url 200 2)")"
put_run 200 aaa "$(job ci cancelled)"
run_case checkrun-cancelled-waits "CI: TIMEOUT pr=7 sha=aaa run=- verdict=none reruns=0 failed=ci" -- --timeout 3
# ...and once the relabel's run reports, its verdict is the answer.
base_fx; put_rules ci
CANC=$(runs_resp "$(cr ci success 1 "$(run_url 100 1)"),$(cr ci cancelled 2 "$(run_url 200 2)")")
RELAB=$(runs_resp "$(cr ci success 1 "$(run_url 100 1)"),$(cr ci cancelled 2 "$(run_url 200 2)"),$(cr ci success 3 "$(run_url 250 3)")")
fx_put "api repos/$SL/commits/aaa/check-runs" "[$CANC,$CANC,$RELAB]"
put_run 250 aaa "$(job ci success)"
run_case checkrun-after-cancel "CI: PASS pr=7 sha=aaa run=250" -- --timeout 10

# REVOKE_FIRST: a conflict on a PR with auto-merge enabled prints the hint line first.
base_fx; put_pr aaa CONFLICTING OPEN '[{"name":"ready"}]' '{"enabledAt":"x"}'
got=$(cd "$T/cwd" && env PATH="$T/bin:$PATH" HOME="$T/home" FAKE_GH_FIXTURES="$FX" STU_ENV_CMD=true CI_MERGE_LABEL=ready \
      "$KIT/scripts/ci-wait.sh" --slug "$SL" --pr 7 --interval 1 --timeout 5 2>/dev/null)
if [ "$(printf '%s\n' "$got" | head -1 | cut -c1-13)" = "REVOKE_FIRST:" ] \
   && printf '%s\n' "$got" | tail -1 | grep -q '^CI: BLOCKED_CONFLICT'; then
  pass "revoke-first: $(printf '%s' "$got" | tr '\n' '|')"
else bad "revoke-first: got '$got'"; fi

# CI_* and the repo come from the resolver when the environment leaves them unset, and the
# environment wins when it sets them. No --slug here: REPO must come from the resolver.
cat > "$T/fake-stu-env" <<'FAKE'
#!/bin/sh
printf "GITHUB_REPO=o/r\nRUN_HOME=%s\nCI_MODE=daemon-status\nCI_STATUS_PREFIX=cfg/\n" "$FAKE_RUN_HOME"
FAKE
chmod +x "$T/fake-stu-env"
base_fx; put_pr aaa MERGEABLE MERGED; put_stats "$(st cfg/test success)"
got=$(cd "$T/cwd" && env PATH="$T/bin:$PATH" HOME="$T/home" FAKE_GH_FIXTURES="$FX" STU_ENV_CMD="$T/fake-stu-env" FAKE_RUN_HOME="$T/rh" \
      "$KIT/scripts/ci-wait.sh" --pr 7 --interval 1 --timeout 5 2>/dev/null)
case "$got" in "CI: MERGED pr=7 sha=aaa"*) pass "config-from-stu-env: $got" ;; *) bad "config-from-stu-env: got '$got'" ;; esac
got=$(cd "$T/cwd" && env PATH="$T/bin:$PATH" HOME="$T/home" FAKE_GH_FIXTURES="$FX" STU_ENV_CMD="$T/fake-stu-env" FAKE_RUN_HOME="$T/rh" \
      CI_MODE=check-run "$KIT/scripts/ci-wait.sh" --pr 7 --interval 1 --timeout 2 2>/dev/null)
case "$got" in "CI: MERGED"*) bad "env-wins-over-config: got '$got'" ;; *) pass "env-wins-over-config: $got" ;; esac
# No repo from any source: usage error, exit 2.
env PATH="$T/bin:$PATH" HOME="$T/home" STU_ENV_CMD=true GITHUB_REPO= "$KIT/scripts/ci-wait.sh" --pr 7 >/dev/null 2>&1 && rc=0 || rc=$?
[ "$rc" = 2 ] && pass "no-repo-exits-2" || bad "no-repo-exits-2: rc=$rc"

# ---- new: --repo is gone ----
base_fx
env PATH="$T/bin:$PATH" HOME="$T/home" STU_ENV_CMD=true "$KIT/scripts/ci-wait.sh" --repo o/r --pr 7 >/dev/null 2>"$T/stderr" && rc=0 || rc=$?
{ [ "$rc" = 2 ] && grep -q -- '--slug' "$T/stderr"; } && pass "repo_flag_is_usage_error" || bad "repo_flag_is_usage_error: rc=$rc $(cat "$T/stderr")"

# ---- new: list mode ----
L="CI_KIND=list REQUIRED_CHECKS=build%20/%20unit,lint"
base_fx; put_rules "build / unit" lint; put_runs "$(cr 'build / unit' success 1),$(cr lint success 2)"
run_case list_all_success_passes "CI: PASS pr=7 sha=aaa run=- verdict=none reruns=0 failed=none" $L -- --timeout 5
base_fx; put_runs "$(cr 'build / unit' success 1)"
run_case list_one_missing_waits_then_timeout "CI: TIMEOUT pr=7 sha=aaa run=- verdict=none reruns=0 failed=none" $L -- --timeout 2
base_fx; put_runs "$(cr 'build / unit' failure 1),$(cr lint success 2)"
run_case list_failure_reports_encoded_name "CI: FAIL pr=7 sha=aaa run=- verdict=none reruns=0 failed=build%20/%20unit" $L -- --timeout 5
run_case verdict_words_unchanged_fail_not_failed "CI: FAIL " $L -- --timeout 5
grep -q 'emit "FAILED"' "$KIT/scripts/ci-wait.sh" && bad "verdict_words: script emits FAILED" || pass "verdict_words: script never emits FAILED"
base_fx; put_runs "$(cr 'build / unit' success 1),$(cr lint skipped 2)"
run_case list_skipped_is_not_success "CI: FAIL pr=7 sha=aaa run=- verdict=skipped" $L -- --timeout 5
run_case list_skipped_fails_fast_with_name "CI: FAIL pr=7 sha=aaa run=- verdict=skipped reruns=0 failed=lint" $L -- --timeout 60
expect_stderr list_skipped_fails_fast_with_name ci_skipped_is_success
run_case list_skipped_opt_in_passes "CI: PASS pr=7 sha=aaa" $L CI_SKIPPED_IS_SUCCESS=true -- --timeout 5
base_fx; put_runs "$(cr 'build / unit' success 1),$(cr lint neutral 2)"
run_case list_neutral_is_not_success "CI: FAIL pr=7 sha=aaa run=- verdict=neutral reruns=0 failed=lint" $L -- --timeout 5
base_fx; put_runs "$(cr 'build / unit' success 1),$(cr lint success 2),$(cr lint failure 3 '' other-app)"
run_case list_duplicate_name_one_failing_fails "CI: FAIL pr=7 sha=aaa run=- verdict=none reruns=0 failed=lint" $L -- --timeout 5
base_fx; put_rules "build / unit"
run_case list_cross_check_omits_required "CI: FAIL pr=7 sha=aaa run=- verdict=config-omits-required reruns=0 failed=build%20/%20unit" \
  CI_KIND=list REQUIRED_CHECKS=lint -- --timeout 5
base_fx
run_case empty_rollup_never_passes_list "CI: TIMEOUT pr=7 sha=aaa run=- verdict=none" $L -- --timeout 2
base_fx
run_case empty_rollup_never_passes_aggregator "CI: TIMEOUT pr=7 sha=aaa run=- verdict=none" -- --timeout 2

# ---- new: aggregator gate states and the forge cross-check ----
base_fx; put_rules ci; put_runs "$(cr ci skipped 1 "$(run_url 200 1)")"
run_case aggregator_skipped_gate_check_not_success "CI: FAIL pr=7 sha=aaa run=200 verdict=skipped reruns=0 failed=ci" -- --timeout 5
base_fx; put_rules ci extra; put_runs "$(cr ci success 1)"
run_case config_omits_forge_required_fails "CI: FAIL pr=7 sha=aaa run=- verdict=config-omits-required reruns=0 failed=extra" -- --timeout 5
base_fx; put_rules other; put_runs "$(cr ci success 1)"
run_case aggregator_forge_requires_other_check_fails "CI: FAIL pr=7 sha=aaa run=- verdict=config-omits-required reruns=0 failed=other" -- --timeout 5
base_fx; put_runs "$(cr ci success 1)"
fx_put "api repos/$SL/rules/branches/main" '{"rc":1,"stdout":"","stderr":"gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)"}'
run_case flat_aggregator_on_free_private_repo_passes "CI: PASS pr=7 sha=aaa run=- verdict=none" -- --timeout 5
expect_stderr flat_aggregator_on_free_private_repo_passes "none readable (plan)"
base_fx; fx_put "api repos/$SL/commits/aaa/check-runs" '{"rc":1,"stdout":"","stderr":"gh: Bad credentials (HTTP 401)"}'
run_case forge_error_is_unknown "CI: UNKNOWN pr=7 sha=aaa run=- verdict=forge-auth reruns=0 failed=none" -- --timeout 5

# CI_GATE_SOURCE: a same-named check from another app cannot pass the gate.
base_fx; put_runs "$(cr ci success 1 '' evil-app)"
run_case gate_source_unpinned_takes_the_check "CI: PASS pr=7 sha=aaa" -- --timeout 5
run_case gate_source_pins_app "CI: TIMEOUT pr=7 sha=aaa" CI_GATE_SOURCE=app:github-actions -- --timeout 2

# The gate workflow: empty in the environment disables the read, unset lets config supply it.
cat > "$T/wf-stu-env" <<'FAKE'
#!/bin/sh
printf "GITHUB_REPO=o/r\nCI_GATE_WORKFLOW=build.yml\n"
FAKE
chmod +x "$T/wf-stu-env"
WFKEY="api repos/$SL/actions/workflows/build.yml/runs?head_sha=aaa&event=pull_request"
base_fx; put_runs "$(cr ci success 1 "$(run_url 200 1)")"; put_run 200 aaa "$(job ci success)"
fx_put "$WFKEY" "$(rsp '{"workflow_runs":[{"id":201,"status":"in_progress","conclusion":null},{"id":200,"status":"completed","conclusion":"success"}]}')"
run_case empty_gate_workflow_disables_check "CI: PASS pr=7 sha=aaa run=200" STU_ENV_CMD="$T/wf-stu-env" CI_GATE_WORKFLOW= -- --timeout 5
expect_no_log empty_gate_workflow_disables_check "workflows/build.yml"
run_case unset_gate_workflow_uses_config "CI: TIMEOUT pr=7 sha=aaa" STU_ENV_CMD="$T/wf-stu-env" -- --timeout 2
expect_log unset_gate_workflow_uses_config "event=pull_request"
# Only pull_request runs gate: the read names that event, so push-event runs never enter.
fx_put "$WFKEY" "$(rsp '{"workflow_runs":[{"id":200,"status":"completed","conclusion":"success"}]}')"
run_case aggregator_push_event_runs_ignored "CI: PASS pr=7 sha=aaa run=200" STU_ENV_CMD="$T/wf-stu-env" -- --timeout 5
expect_log aggregator_push_event_runs_ignored "head_sha=aaa&event=pull_request"
# Many open runs at the head and none a completed gating run: still pending, never a verdict.
RUNS=$(jq -cn '{workflow_runs: [range(1000;1150) | {id: ., status: "in_progress", conclusion: null}]}')
fx_put "$WFKEY" "$(rsp "$RUNS")"
run_case aggregator_full_page_stays_pending "CI: TIMEOUT pr=7 sha=aaa" STU_ENV_CMD="$T/wf-stu-env" -- --timeout 2

# ---- new: ci none ----
base_fx
run_case ci_none_short_circuits "CI: NONE pr=7 sha=aaa run=- verdict=none reruns=0 failed=none" CI_KIND=none -- --timeout 5
expect_no_log ci_none_short_circuits "check-runs"

# ---- new: triage seam ----
mk_triage() { printf '#!/bin/sh\necho "$@" > "%s"\necho "%s"\n' "$T/triage.args" "$2" > "$T/$1"; chmod +x "$T/$1"; }
mk_triage t-flaky flaky; mk_triage t-real real; mk_triage t-unparsed unparsed; mk_triage t-banana banana
FAILRUN=$(cr ci failure 1 "$(run_url 200 1)")
red_fx() { base_fx; put_rules ci; put_runs "$FAILRUN"; put_run 200 aaa "$(job ci failure)"; }
red_fx
fx_put "api repos/$SL/commits/aaa/check-runs" "[$(runs_resp "$FAILRUN"),$(runs_resp "$(cr ci success 2 "$(run_url 200 2)")")]"
put_run 200 aaa "$(job ci success)"; fx_put "run rerun 200" '{"rc":0,"stdout":""}'
run_case triage_flaky_reruns_once "CI: FLAKY_RERUN_PASSED pr=7 sha=aaa run=200 verdict=flaky reruns=1 failed=none" CI_TRIAGE_COMMAND="$T/t-flaky" -- --timeout 20
[ "$(grep -c 'run rerun 200' "$GHLOG")" = 1 ] && pass "triage_flaky_reruns_once: exactly one rerun" || bad "triage_flaky_reruns_once: reruns != 1"
[ "$(cat "$T/triage.args")" = "o/r 7 200" ] && pass "triage called with slug pr run" || bad "triage args: $(cat "$T/triage.args")"
red_fx; put_pr aaa MERGEABLE OPEN '[]' null owned/feature; fx_put "run rerun 200" '{"rc":0,"stdout":""}'
run_case triage_flaky_on_owned_branch_is_flaky_owned "CI: FAIL pr=7 sha=aaa run=200 verdict=flaky-owned reruns=0 failed=ci" \
  CI_TRIAGE_COMMAND="$T/t-flaky" CI_NO_RERUN_BRANCH_PREFIX=owned/ -- --timeout 20
expect_no_log triage_flaky_on_owned_branch_is_flaky_owned "run rerun"
red_fx
run_case triage_real_is_fail "CI: FAIL pr=7 sha=aaa run=200 verdict=real reruns=0 failed=ci" CI_TRIAGE_COMMAND="$T/t-real" -- --timeout 20
run_case triage_unparsed_is_unknown "CI: UNKNOWN pr=7 sha=aaa run=200 verdict=triage-unparsed" CI_TRIAGE_COMMAND="$T/t-unparsed" -- --timeout 20
run_case triage_other_output_is_unparsed "CI: UNKNOWN pr=7 sha=aaa run=200 verdict=triage-unparsed" CI_TRIAGE_COMMAND="$T/t-banana" -- --timeout 20
SECONDS=0
run_case triage_wait_defaults_zero_without_command "CI: UNKNOWN pr=7 sha=aaa run=200 verdict=triage-absent" -- --timeout 20
[ "$SECONDS" -lt 10 ] && pass "triage_wait_defaults_zero_without_command: no 900s wait" || bad "triage wait took ${SECONDS}s"

# The rerun ledger entry lands under RUN_HOME with ~ expanded, never in a directory named ~.
red_fx
fx_put "api repos/$SL/commits/aaa/check-runs" "[$(runs_resp "$FAILRUN"),$(runs_resp "$(cr ci success 2 "$(run_url 200 2)")")]"
put_run 200 aaa "$(job ci success)"; fx_put "run rerun 200" '{"rc":0,"stdout":""}'
run_case ledger_path_has_no_literal_tilde "CI: FLAKY_RERUN_PASSED" CI_TRIAGE_COMMAND="$T/t-flaky" RUN_HOME='~/rh' -- --timeout 20
{ ls "$T/home/rh/ledger-inbox"/*ci-wait-rerun-pr7.md >/dev/null 2>&1 && [ ! -e "$T/cwd/~" ]; } \
  && pass "ledger_path_has_no_literal_tilde: entry under HOME" || bad "ledger_path_has_no_literal_tilde"

# ---- new: row-selection exit-code table (stu-env rows / plain) ----
cat > "$T/rc-stu-env" <<'FAKE'
#!/bin/sh
exit "${FAKE_RC:-0}"
FAKE
chmod +x "$T/rc-stu-env"
for _rc in 1 4; do
  base_fx; put_rules ci; put_runs "$(cr ci success 1)"
  run_case "rows_exit_${_rc}_with_STU_CONFIG_is_no_config" "CI: UNKNOWN pr=7 sha=- run=- verdict=no-config" \
    STU_ENV_CMD="$T/rc-stu-env" FAKE_RC=$_rc STU_CONFIG="$T/none.md" -- --timeout 3
  run_case "rows_exit_${_rc}_without_STU_CONFIG_falls_back" "CI: PASS pr=7 sha=aaa" \
    STU_ENV_CMD="$T/rc-stu-env" FAKE_RC=$_rc STU_CONFIG= -- --timeout 3
done
base_fx; put_rules ci; put_runs "$(cr ci success 1)"
run_case rows_exit_2_falls_back_even_with_STU_CONFIG "CI: PASS pr=7 sha=aaa" \
  STU_ENV_CMD="$T/rc-stu-env" FAKE_RC=2 STU_CONFIG="$T/none.md" -- --timeout 3

# ---- new: required-checks read errors fail closed ----
base_fx; put_runs "$(cr ci success 1)"
fx_put "api repos/$SL/rules/branches/main" '{"rc":1,"stdout":"","stderr":"gh: Bad credentials (HTTP 401)"}'
run_case required_checks_error_is_unknown_aggregator "CI: UNKNOWN pr=7 sha=aaa run=- verdict=forge-auth reruns=0 failed=none" -- --timeout 3
base_fx; put_runs "$(cr 'build / unit' success 1),$(cr lint success 2)"
fx_put "api repos/$SL/rules/branches/main" '{"rc":1,"stdout":"","stderr":"gh: Bad credentials (HTTP 401)"}'
run_case required_checks_error_is_unknown_list "CI: UNKNOWN pr=7 sha=aaa run=- verdict=forge-auth reruns=0 failed=none" $L -- --timeout 3

# ---- new: aggregator neutral, duplicate gate names, a second flake ----
base_fx; put_rules ci; put_runs "$(cr ci neutral 1 "$(run_url 200 1)")"
run_case aggregator_neutral_gate_check_not_success "CI: FAIL pr=7 sha=aaa run=200 verdict=neutral reruns=0 failed=ci" -- --timeout 5
mk_triage t-real2 real
base_fx; put_rules ci; put_runs "$(cr ci success 1),$(cr ci failure 2 '' other-app)"
run_case gate_duplicate_name_one_failing_fails "CI: FAIL pr=7 sha=aaa run=- verdict=real" CI_TRIAGE_COMMAND="$T/t-real2" -- --timeout 5
base_fx; put_rules ci; put_runs "$(cr ci success 1),$(cr ci success 2 '' other-app)"
run_case gate_duplicate_name_all_success_passes "CI: PASS pr=7 sha=aaa" -- --timeout 5
mk_triage t-flaky2 flaky
FAILRUN2=$(cr ci failure 1 "$(run_url 200 1)")
base_fx; put_rules ci; put_runs "$FAILRUN2"; put_run 200 aaa "$(job ci failure)"; fx_put "run rerun 200" '{"rc":0,"stdout":""}'
run_case triage_flaky_twice_fails_without_second_rerun "CI: FAIL pr=7 sha=aaa run=200 verdict=flaky-twice reruns=1 failed=ci" CI_TRIAGE_COMMAND="$T/t-flaky2" -- --timeout 20
[ "$(grep -c 'run rerun 200' "$GHLOG")" = 1 ] && pass "flaky_twice: exactly one rerun" || bad "flaky_twice: reruns != 1"

# ---- new: config resolution ----
cat > "$T/bad-stu-env" <<'FAKE'
#!/bin/sh
echo "stu: config error: the fix is here" >&2
exit 3
FAKE
chmod +x "$T/bad-stu-env"
base_fx
run_case invalid_config_verdict_is_config_error "CI: UNKNOWN pr=7 sha=- run=- verdict=config-error reruns=0 failed=none" STU_ENV_CMD="$T/bad-stu-env" -- --timeout 5
expect_stderr invalid_config_verdict_is_config_error "the fix is here"

# A real family through the real stu-env: repos are plain git repos; the config is found by scan.
mkrepo() { mkdir -p "$1" && git -C "$1" init -q && git -C "$1" -c user.name=T -c user.email=t@e commit -q --allow-empty -m init; }
FH="$T/fam/home"; mkdir -p "$FH/.stu/fam"
mkrepo "$T/fam/app"; mkrepo "$T/fam/lib"
APP=$(cd "$T/fam/app" && pwd -P); LIB=$(cd "$T/fam/lib" && pwd -P)
fam_cfg() {  # lib-extra-line
  cat > "$FH/.stu/fam/stu.md" <<CFG
---
owner: o
ci_gate_check: build
---

## repos
### app
path: $APP
slug: acme/app
remote: origin
base: main
visibility: public
mode: work
merge_mode: direct
ci: aggregator

### lib
path: $LIB
slug: acme/lib
remote: origin
base: main
visibility: private
mode: work
merge_mode: report-only
ci: aggregator
$1

## verification-commands
\`\`\`
make test
\`\`\`

## verification-commands @lib
\`\`\`
./check
\`\`\`
CFG
}
fam_run() {  # name want cwd [ci-wait args...]
  local name="$1" want="$2" cwd="$3"; shift 3
  rm -f "$STATE" "$GHLOG"
  local got
  got=$(cd "$cwd" && env PATH="$T/bin:$PATH" HOME="$FH" GIT_CONFIG_GLOBAL="$FH/.gitconfig" FAKE_GH_FIXTURES="$FX" FAKE_GH_STATE="$STATE" \
        FAKE_GH_LOG="$GHLOG" STU_FORGE_REQUERY_DELAY=0 "$KIT/scripts/ci-wait.sh" --pr 7 --interval 1 "$@" 2>"$T/stderr")
  case "$got" in "$want"*) echo "ok   $name: $got" ;; *) echo "FAIL $name: want '${want}...', got '$got'"; fails=$((fails + 1)) ;; esac
}
fam_cfg "ci_gate_check: unit"
SL=acme/lib; base_fx; put_rules unit; put_runs "$(cr unit success 1)"
fam_run sibling_slug_maps_to_own_row "CI: PASS pr=7 sha=aaa" "$APP" --slug acme/lib --timeout 3
SL=acme/app; base_fx; put_rules build; put_runs "$(cr build success 1)"
fam_run home_slug_maps_to_home_row "CI: PASS pr=7 sha=aaa" "$APP" --slug acme/app --timeout 3
fam_run slug_not_in_family_is_unknown "CI: UNKNOWN pr=7 sha=- run=- verdict=no-config reruns=0 failed=none" "$APP" --slug acme/other --timeout 3
fam_run no_slug_with_family_is_unknown "CI: UNKNOWN pr=7 sha=- run=- verdict=no-config reruns=0 failed=none" "$APP" --timeout 3
# A broken family (ci: list with no required_checks) read by scan, no STU_CONFIG: UNKNOWN, never defaults.
fam_cfg "ci: list"
fam_run invalid_family_without_STU_CONFIG_is_unknown "CI: UNKNOWN pr=7 sha=- run=- verdict=config-error reruns=0 failed=none" "$APP" --slug acme/lib --timeout 3
[ -s "$T/stderr" ] && pass "invalid_family: stu-env message reaches stderr" || bad "invalid_family: empty stderr"
SL=o/r

[ "$fails" = 0 ] || { echo "ci_wait_test: $fails failed"; exit 1; }
echo "ci_wait_test: all checks passed"
