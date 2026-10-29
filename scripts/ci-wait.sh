#!/usr/bin/env bash
# ci-wait — block until a PR's CI is decided, then print ONE machine-readable line.
#
# Run it once, in the background, and read the final line:
#   Bash(command="stu-ci-wait --pr 123",
#        run_in_background=true)
#
# That is the whole point: N polls become ONE agent turn. A turn re-pays the entire
# context, so a poll loop in the agent costs far more than the same loop in here.
# On one project an orchestrator spent most of its wall clock in `sleep` calls,
# polling CI one turn at a time.
#
# THE LINE IS THE CONTRACT, NOT THE EXIT CODE. Every convenience wrapper we tried
# returned a wrong exit code in both directions (`gh run watch --exit-status` exited 1
# on a successful run; `gh pr checks --watch | tail` exited 0 while jobs failed).
# This script always exits 0 except on usage error.
#
#   REVOKE_FIRST: …   (optional, printed BEFORE the CI: line, only with BLOCKED_CONFLICT or
#                      SHA_MOVED on a PR carrying MERGE_LABEL or auto-merge; see the
#                      project's delivery guide for the revoke sequence)
#   CI: PASS | FAIL | FLAKY_RERUN_PASSED | UNKNOWN | TIMEOUT | SHA_MOVED | BLOCKED_CONFLICT
#       | MERGED | NONE
#       pr=… sha=… run=… verdict=… reruns=N failed=…   (failed= names are percent-encoded:
#       only %, space, comma, tab and newline are escaped)
#   Row selection: --slug OWNER/REPO (never --repo) picks the config row; a family that cannot
#   be resolved is `CI: UNKNOWN … verdict=no-config` or `verdict=config-error`, never a default.
#   Every forge read goes through stu-forge (STU_FORGE_CMD overrides it); a forge error is
#   `CI: UNKNOWN … verdict=forge-<class>`. CI_KIND: aggregator (one gating check), list
#   (every REQUIRED_CHECKS name must be success, no reruns), none (`CI: NONE`; the gate runs
#   the repo's verification commands itself, see stu-verify).
#
# A CANCELLED newest GATE_CHECK is never a verdict: it is waited past. A bare cancel with
# no newer run therefore ends in TIMEOUT (5400s by default), not UNKNOWN.
#
# Flake-vs-real is NOT decided here — see `triage_verdict_for_run` below. With no
# triage configured the script fails closed to UNKNOWN and never reruns anything.
#
# Two modes (CI_MODE / --mode, chosen in the PROJECT-SPECIFIC block below):
#   check-run      (default) wait for ONE gating check's conclusion; PASS/FAIL/…
#   daemon-status  for a repo where a separate auto-merge service, not you, merges
#                  on green, and reports through commit statuses that share a name
#                  prefix. Success is the merge: MERGED when the PR merges, FAIL
#                  failed=<contexts> as soon as a status under the prefix fails,
#                  BLOCKED_CONFLICT on a conflict, SHA_MOVED if the head changes,
#                  TIMEOUT otherwise. Never reruns: the service owns reruns.
set -uo pipefail

PR=""
SLUG_ARG=""
INTERVAL=45
TIMEOUT=5400        # 90 min. Raise it if your slowest matrix runs longer (CI_TIMEOUT).
TIMEOUT_SET=0
TRIAGE_WAIT=""      # seconds; default 0 with no CI_TRIAGE_COMMAND (nothing can post), else 900
MAX_RERUNS=1
CHECK_ARG=""
MODE_ARG=""
PREFIX_ARG=""

ENV_ERR=$(mktemp "${TMPDIR:-/tmp}/ci-wait-env.XXXXXX")
trap 'rm -f "$ENV_ERR"' EXIT

# Header lines 2..HEADER_END are the usage text.
usage() { sed -n '2,/^set -uo/p' "$0" | sed '$d'; exit 2; }
say() { printf '[ci-wait] %s\n' "$*" >&2; }
bad() { printf '%s\n' "$*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --pr) PR="${2:-}"; shift 2 ;;
    --slug) SLUG_ARG="${2:-}"; shift 2 ;;
    --repo) bad "ci-wait: --repo is gone; pass --slug OWNER/REPO (--repo now means a config row name elsewhere)" ;;
    --check) CHECK_ARG="${2:-}"; shift 2 ;;
    --interval) INTERVAL="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT="${2:-}"; TIMEOUT_SET=1; shift 2 ;;
    --max-reruns) MAX_RERUNS="${2:-}"; shift 2 ;;
    --triage-wait) TRIAGE_WAIT="${2:-}"; shift 2 ;;
    --mode) MODE_ARG="${2:-}"; shift 2 ;;
    --status-prefix) PREFIX_ARG="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$PR" ] || bad "--pr is required"

RERUNS=0
SHA0=""
BRANCH=""
BASE_REF=""

# One `CI:` line, then exit 0. A BLOCKED_CONFLICT or SHA_MOVED on an armed PR prints the
# revoke hint first (see revoke_hint).
emit() {
  case "$1" in BLOCKED_CONFLICT | SHA_MOVED) revoke_hint ;; esac
  printf 'CI: %s pr=%s sha=%s run=%s verdict=%s reruns=%s failed=%s\n' \
    "$1" "$PR" "${2:--}" "${3:--}" "${4:-none}" "$RERUNS" "${5:-none}"
  exit 0
}

# ---- config: row selection and the environment-first overlay -------------------------------

# Resolver. STU_ENV_CMD overrides it; the tests point it at `true` or a fake.
STU_ENV_CMD="${STU_ENV_CMD:-$(dirname "$0")/../bin/stu-env}"
stu_env() { "$STU_ENV_CMD" "$@" 2>"$ENV_ERR"; }
config_error() {
  head -n 1 "$ENV_ERR" >&2
  emit "UNKNOWN" "-" "-" "config-error" "none"
}
no_config() { emit "UNKNOWN" "-" "-" "no-config" "none"; }

# Value of KEY in the resolver's output (empty if absent). The output is shell-quoted
# KEY=value lines, so it is evaluated in a subshell that prints only the one key.
STU_ENV_OUT=""
se() { [ -n "$STU_ENV_OUT" ] || return 0; ( eval "$STU_ENV_OUT" >/dev/null 2>&1; eval "printf '%s' \"\${$1:-}\"" ); }

# Row selection. A family (two or more rows) needs --slug to name one of them; a flat
# config or no config behaves as before. Only stu-env exit 2 may fall back to defaults.
ROWS_OUT=$(stu_env rows); rc=$?
NROWS=0
case "$rc" in
  0) NROWS=$(printf '%s\n' "$ROWS_OUT" | awk -F'\t' 'NF >= 5' | wc -l | tr -d ' ') ;;
  2) ROWS_OUT="" ;;
  3) config_error ;;
  1|4) ROWS_OUT=""; [ -z "${STU_CONFIG:-}" ] || no_config ;;
  *) no_config ;;
esac
FAMILY=0
[ "$NROWS" -lt 2 ] || FAMILY=1

if [ "$FAMILY" = 1 ]; then
  [ -n "$SLUG_ARG" ] || no_config
  ROW=$(printf '%s\n' "$ROWS_OUT" | awk -F'\t' -v s="$SLUG_ARG" 'NF >= 5 && $3 == s { print $1; exit }')
  [ -n "$ROW" ] || no_config
  STU_ENV_OUT=$(stu_env --repo "$ROW"); rc=$?
  case "$rc" in 0) ;; 3) config_error ;; *) no_config ;; esac
else
  STU_ENV_OUT=$(stu_env); rc=$?
  case "$rc" in
    0) ;;
    2) STU_ENV_OUT="" ;;
    3) config_error ;;
    1|4) STU_ENV_OUT=""; [ -z "${STU_CONFIG:-}" ] || no_config ;;
    *) no_config ;;
  esac
fi

# Config only fills what the environment left unset: env wins, then config, then defaults.
for _k in CI_GATE_CHECK CI_MERGE_LABEL CI_MODE CI_STATUS_PREFIX CI_KIND CI_TIMEOUT \
          CI_TRIAGE_COMMAND CI_TRIAGE_WAIT CI_NO_RERUN_BRANCH_PREFIX CI_GATE_SOURCE \
          CI_SKIPPED_IS_SUCCESS REQUIRED_CHECKS GH_HOST; do
  if [ -z "$(eval "printf '%s' \"\${$_k:-}\"")" ]; then
    _v=$(se "$_k"); [ -z "$_v" ] || export "$_k=$_v"
  fi
done
# An empty CI_GATE_WORKFLOW in the environment disables the workflow check outright; unset
# lets the config supply it.
if [ -z "${CI_GATE_WORKFLOW+set}" ]; then
  _v=$(se CI_GATE_WORKFLOW); [ -z "$_v" ] || export CI_GATE_WORKFLOW="$_v"
fi
if [ "$FAMILY" = 1 ]; then
  REPO="$SLUG_ARG"
else
  REPO="${SLUG_ARG:-${GITHUB_REPO:-$(se GITHUB_REPO)}}"
fi
_rh="${RUN_HOME:-$(se RUN_HOME)}"
case "$_rh" in "~/"*) _rh="$HOME/${_rh#\~/}" ;; "~") _rh="$HOME" ;; esac
LEDGER="${_rh:-$HOME/.stu/unresolved}/ledger-inbox"

[ -n "$REPO" ] || bad "no repo: pass --slug, set GITHUB_REPO, or run /stu:init"

# > PROJECT-SPECIFIC (config key ci_gate_check -> CI_GATE_CHECK, default ci): the ONE check whose conclusion gates merge. Not a count of
# > pending checks. If your branch protection requires several checks, either name an
# > aggregating check here or use `ci: list` with required_checks.
GATE_CHECK="${CI_GATE_CHECK:-ci}"
[ -z "$CHECK_ARG" ] || GATE_CHECK="$CHECK_ARG"
# > PROJECT-SPECIFIC, optional: the workflow file that posts GATE_CHECK (e.g. build.yml).
# > While any run of it at the head SHA is unfinished, the verdict is still pending,
# > even when an older run's GATE_CHECK has already reported. Empty skips the check.
GATE_WORKFLOW="${CI_GATE_WORKFLOW:-}"
# > Optional ci_gate_source (e.g. app:github-actions): only that source's newest gating
# > check counts, so a same-named check from another app cannot pass the gate.
GATE_SOURCE="${CI_GATE_SOURCE:-}"
SKIPPED_OK="${CI_SKIPPED_IS_SUCCESS:-false}"

# > PROJECT-SPECIFIC, optional: the label that tells an auto-merge actor to merge on green.
# > When set, a BLOCKED_CONFLICT or SHA_MOVED on a PR carrying it, or with auto-merge
# > enabled, prints a REVOKE_FIRST line before the CI: line. Empty still checks auto-merge.
MERGE_LABEL="${CI_MERGE_LABEL:-}"

KIND="${CI_KIND:-aggregator}"
case "$KIND" in aggregator|list|none) ;; *) bad "unknown CI_KIND: $KIND (aggregator | list | none)" ;; esac

# > CI_MODE (check-run | daemon-status) selects how an AGGREGATOR check is read; it is
# > ignored for list and none. daemon-status: a separate auto-merge service merges on green
# > and reports through commit statuses sharing a name prefix; success is the merge.
CI_MODE="${MODE_ARG:-${CI_MODE:-check-run}}"
STATUS_PREFIX="${PREFIX_ARG:-${CI_STATUS_PREFIX:-}}"
if [ "$KIND" = aggregator ]; then
  case "$CI_MODE" in
    check-run) ;;
    daemon-status)
      # An empty prefix would match every context, including ones that do not gate.
      [ -n "$STATUS_PREFIX" ] || bad "daemon-status mode needs --status-prefix" ;;
    *) bad "unknown mode: $CI_MODE (check-run | daemon-status)" ;;
  esac
fi

[ "$TIMEOUT_SET" = 1 ] || [ -z "${CI_TIMEOUT:-}" ] || TIMEOUT="$CI_TIMEOUT"
if [ -z "$TRIAGE_WAIT" ]; then
  if [ -n "${CI_TRIAGE_WAIT:-}" ]; then TRIAGE_WAIT="$CI_TRIAGE_WAIT"
  elif [ -n "${CI_TRIAGE_COMMAND:-}" ]; then TRIAGE_WAIT=900
  else TRIAGE_WAIT=0; fi
fi
for _n in "$INTERVAL" "$TIMEOUT" "$TRIAGE_WAIT" "$MAX_RERUNS"; do
  case "$_n" in ''|*[!0-9]*) bad "ci-wait: not a number of seconds/count: '$_n'" ;; esac
done

# ---- forge reads ---------------------------------------------------------------------------

FORGE_CMD="${STU_FORGE_CMD:-$(dirname "$0")/../bin/stu-forge}"
FORGE_OUT=""
FORGE_ERR=""
# Run a stu-forge verb. Success (return 0) needs exit 0 AND a terminal `OK` line; FORGE_OUT
# then holds the result lines. Anything else returns 1 with FORGE_ERR set to the error class.
forge() {
  local out rc last
  FORGE_OUT=""; FORGE_ERR=""
  out=$("$FORGE_CMD" "$@" ${GH_HOST:+--host "$GH_HOST"} 2>/dev/null); rc=$?
  last=${out##*$'\n'}
  if [ "$rc" -eq 0 ] && [ "$last" = "OK" ]; then
    if [ "$out" = "OK" ]; then FORGE_OUT=""; else FORGE_OUT=${out%$'\n'OK}; fi
    return 0
  fi
  FORGE_ERR=$(printf '%s\n' "$last" | awk '$1 == "ERROR" { print $2; exit }' | tr -c 'a-z\n-' '-')
  [ -n "$FORGE_ERR" ] || FORGE_ERR="forge"
  return 1
}
# Fail closed: a forge read that failed is never "nothing happened".
forge_unknown() { emit "UNKNOWN" "${SHA0:--}" "-" "forge-$FORGE_ERR" "none"; }
fv() { printf '%s\n' "$FORGE_OUT" | awk -v k="$1" '$1 == k { $1 = ""; sub(/^ /, ""); print; exit }'; }

# Percent-encode a check name the way stu-forge prints it: only % space comma tab newline.
enc() {
  local s="$1"
  s=${s//%/%25}; s=${s// /%20}; s=${s//,/%2C}; s=${s//$'\t'/%09}; s=${s//$'\n'/%0A}
  printf '%s' "$s"
}
GATE_ENC=$(enc "$GATE_CHECK")

read_pr() { forge pr-state --slug "$REPO" --pr "$PR" || forge_unknown; }

# A PR that carries MERGE_LABEL or has auto-merge on merges a later push unevaluated
# (auto-merge binds no SHA). Print a hint BEFORE the CI: line; never mutate the PR.
revoke_hint() {
  local labels auto armed=0
  if forge pr-state --slug "$REPO" --pr "$PR"; then
    labels=",$(fv LABELS),"; auto=$(fv AUTO_MERGE)
    [ "$auto" != "on" ] || armed=1
    [ -z "$MERGE_LABEL" ] || case "$labels" in *",$MERGE_LABEL,"*) armed=1 ;; esac
  else
    armed=1   # cannot tell: say so rather than stay silent
  fi
  [ "$armed" = 1 ] || return 0
  printf 'REVOKE_FIRST: #%s carries %s - run the revoke sequence in the delivery guide (take the PR off auto-merge) before any push\n' "$PR" "${MERGE_LABEL:+$MERGE_LABEL/}auto-merge"
}

# Names of failing checks in CHECKS lines: encoded, sorted, comma-joined ("" if none).
failed_names() {
  printf '%s\n' "$1" | awk '$1 == "CHECK" && $2 == "failure" { print $5 }' | LC_ALL=C sort -u | paste -sd, -
}

# The gate check's state and newest run id from CHECKS lines, as "<state> <run|->".
# Every matching line must agree: a failure anywhere is a failure, a pending one waits,
# neutral and (unless opted in) skipped are never success. No line at all is "none".
gate_summary() {
  printf '%s\n' "$1" | awk -v name="$GATE_ENC" -v src="$GATE_SOURCE" -v skipok="$SKIPPED_OK" '
    $1 == "CHECK" && $5 == name && (src == "" || $3 == src) {
      n++; st[$2]++
      if ($4 ~ /^[0-9]+$/ && $4 + 0 > rid) rid = $4 + 0
    }
    END {
      if (n == 0) s = "none"
      else if (st["failure"]) s = "failure"
      else if (st["pending"]) s = "pending"
      else if (st["neutral"]) s = "neutral"
      else if (st["skipped"] && skipok != "true") s = "skipped"
      else s = "success"
      printf "%s %s\n", s, (rid > 0 ? sprintf("%d", rid) : "-")
    }'
}

# True (0) while the gate workflow still has a run at the head that could change the verdict:
# the run that posted the verdict or any newer one still open, or a newer finished run that
# has a job named like the gate check. Reads are fail-closed.
gate_unsettled() {
  local rid="$1" id st concl jid
  [ -n "$GATE_WORKFLOW" ] || return 1
  [ "$rid" != "-" ] || return 0
  forge workflow-runs --slug "$REPO" --workflow "$GATE_WORKFLOW" --sha "$SHA0" --event pull_request || forge_unknown
  local runs="$FORGE_OUT"
  while read -r _ id st concl; do
    [ -n "$id" ] || continue
    [ "$id" -ge "$rid" ] 2>/dev/null || continue
    [ "$st" = "completed" ] || return 0
    [ "$id" = "$rid" ] && continue
    forge run-jobs --slug "$REPO" --run "$id" || forge_unknown
    printf '%s\n' "$FORGE_OUT" | awk -v n="$GATE_ENC" '$1 == "JOB" && $5 == n { f = 1 } END { exit !f }' && return 0
  done <<< "$runs"
  return 1
}

# At a timeout, a cancelled newest run reads as pending in CHECKS; report its cancelled
# jobs as failed= the way a bare cancel always did. Best effort: errors add nothing.
cancelled_names() {
  local rid seen=" " out=""
  for rid in $(printf '%s\n' "$1" | awk '$1 == "CHECK" && $2 == "pending" && $4 ~ /^[0-9]+$/ { print $4 }'); do
    case "$seen" in *" $rid "*) continue ;; esac
    seen="$seen$rid "
    forge run-jobs --slug "$REPO" --run "$rid" || continue
    out="$out"$'\n'"$(printf '%s\n' "$FORGE_OUT" | awk '$1 == "JOB" && $4 == "cancelled" { print $5 }')"
  done
  printf '%s\n' "$out"
}
timeout_failed() {
  { printf '%s\n' "$(printf '%s\n' "$1" | awk '$1 == "CHECK" && $2 == "failure" { print $5 }')"; cancelled_names "$1"; } \
    | awk 'NF' | LC_ALL=C sort -u | paste -sd, -
}

# > PROJECT-SPECIFIC seam: decide whether THIS run's failure is a real defect or a flake.
# > CI_TRIAGE_COMMAND (an executable) is called with `<slug> <pr> <run-id>` and prints one of:
# >   real | flaky | absent | stale | unparsed
# > Anything else is read as `unparsed`. Only `flaky` reruns. Without the key there is no
# > triage: `absent`, which fails closed to UNKNOWN and never reruns.
# > A verdict that does not name THIS run id is stale: the command must fail closed on it.
triage_verdict_for_run() {
  local run_id="$1" out w
  if [ -z "${CI_TRIAGE_COMMAND:-}" ]; then echo "absent"; return; fi
  out=$("$CI_TRIAGE_COMMAND" "$REPO" "$PR" "$run_id" 2>/dev/null) || { echo "unparsed"; return; }
  w=$(printf '%s\n' "$out" | head -n 1 | tr -d '[:space:]')
  case "$w" in real|flaky|absent|stale|unparsed) echo "$w" ;; *) echo "unparsed" ;; esac
}

record_rerun() {
  mkdir -p "$LEDGER" 2>/dev/null
  local f="$LEDGER/$(date -u +%Y-%m-%d-%H%M)-ci-wait-rerun-pr$PR.md"
  {
    printf '# ci-wait reran failed jobs on PR #%s\n\n' "$PR"
    printf -- '- sha: %s\n- run: %s\n- failed: %s\n- triage verdict: flaky\n\n' "$1" "$2" "$3"
    printf 'A rerun unblocked the PR. The flake itself is NOT fixed, and absence of a\n'
    printf 'tracking issue is not evidence it never flaked. Root-cause it rather than\n'
    printf 'leaving the retry as the fix.\n'
  } > "$f" 2>/dev/null && say "recorded rerun to $f"
}

# ---- start: the PR, conflicts, ci none, the forge cross-check ------------------------------

read_pr
SHA0=$(fv HEAD_SHA)
BRANCH=$(fv HEAD_REF)
BASE_REF=$(fv BASE_REF)
[ -n "$SHA0" ] || emit "UNKNOWN" "-" "-" "no-pr-head" "none"

# A CONFLICTING PR fires no CI at all — waiting for it would hang until timeout.
forge mergeable --slug "$REPO" --pr "$PR" || forge_unknown
_m=$(printf '%s\n' "$FORGE_OUT" | awk '$1 == "MERGEABLE" { print $2; exit }')
[ "$_m" != "CONFLICTING" ] || emit "BLOCKED_CONFLICT" "$SHA0" "-" "none" "none"

# ci: none — the gate runs the repo's verification commands itself (stu-verify).
[ "$KIND" != none ] || emit "NONE" "$SHA0" "-" "none" "none"

# Spec B2: every check the forge requires for the base must be in the configured set.
if [ "$KIND" = list ] || { [ "$KIND" = aggregator ] && [ "$CI_MODE" = check-run ]; }; then
  if [ "$KIND" = list ]; then
    [ -n "${REQUIRED_CHECKS:-}" ] || bad "ci-wait: ci list needs REQUIRED_CHECKS"
    ALLOWED=",$REQUIRED_CHECKS,"
  else
    ALLOWED=",$GATE_ENC,"
  fi
  forge required-checks --slug "$REPO" --base "$BASE_REF" || forge_unknown
  OMITTED=""
  while read -r _k _n _rest; do
    case "$_k" in
      REQUIRED) case "$ALLOWED" in *",$_n,"*) ;; *) OMITTED="${OMITTED:+$OMITTED,}$_n" ;; esac ;;
      REQUIRED_NONE_READABLE) say "forge cross-check: none readable ($_n)" ;;
    esac
  done <<< "$FORGE_OUT"
  [ -z "$OMITTED" ] || emit "FAIL" "$SHA0" "-" "config-omits-required" "$OMITTED"
fi

START=$(date +%s)
CHECKS=""

# Re-read the PR; a moved head ends the wait (evidence for the old SHA proves nothing now).
check_head() {
  read_pr
  local sha; sha=$(fv HEAD_SHA)
  if [ -n "$sha" ] && [ "$sha" != "$SHA0" ]; then emit "SHA_MOVED" "$sha" "-" "none" "none"; fi
}
# Read the checks at the head; ERROR empty keeps the wait going, any other error is UNKNOWN.
# Sets CHECKS and returns 1 when there is nothing to judge yet.
read_checks() {
  if forge checks --slug "$REPO" --sha "$SHA0"; then CHECKS="$FORGE_OUT"; return 0; fi
  [ "$FORGE_ERR" = "empty" ] || forge_unknown
  CHECKS=""
  return 1
}

# ---- daemon-status: success is the merge ---------------------------------------------------

if [ "$KIND" = aggregator ] && [ "$CI_MODE" = daemon-status ]; then
  PREFIX_ENC=$(enc "$STATUS_PREFIX")
  say "pr #$PR branch=$BRANCH sha=$SHA0 mode=daemon-status prefix=$STATUS_PREFIX"
  while :; do
    # Merged first: a squash merge leaves the head where it was, and a merged PR is the
    # only success this mode knows.
    read_pr
    [ "$(fv STATE)" != "merged" ] || emit "MERGED" "$SHA0" "-" "none" "none"
    SHA=$(fv HEAD_SHA)
    if [ -n "$SHA" ] && [ "$SHA" != "$SHA0" ]; then emit "SHA_MOVED" "$SHA" "-" "none" "none"; fi
    forge mergeable --slug "$REPO" --pr "$PR" || forge_unknown
    [ "$(printf '%s\n' "$FORGE_OUT" | awk '$1 == "MERGEABLE" { print $2; exit }')" != "CONFLICTING" ] || \
      emit "BLOCKED_CONFLICT" "$SHA0" "-" "none" "none"
    if read_checks; then
      FAILED=$(printf '%s\n' "$CHECKS" | awk -v p="$PREFIX_ENC" '
        $1 == "CHECK" && $2 == "failure" && $3 ~ /^status:/ && index($5, p) == 1 { print $5 }' \
        | LC_ALL=C sort -u | paste -sd, -)
      [ -z "$FAILED" ] || emit "FAIL" "$SHA0" "-" "none" "$FAILED"
    fi
    NOW=$(date +%s)
    [ $((NOW - START)) -lt "$TIMEOUT" ] || emit "TIMEOUT" "$SHA0" "-" "none" "none"
    sleep "$INTERVAL"
  done
fi

# ---- list: every required name must be success ---------------------------------------------

if [ "$KIND" = list ]; then
  say "pr #$PR branch=$BRANCH sha=$SHA0 required=$REQUIRED_CHECKS"
  while :; do
    NOW=$(date +%s)
    [ $((NOW - START)) -lt "$TIMEOUT" ] || emit "TIMEOUT" "$SHA0" "-" "none" "none"
    check_head
    if read_checks; then
      RES=$(printf '%s\n' "$CHECKS" | awk -v req="$REQUIRED_CHECKS" -v skipok="$SKIPPED_OK" '
        BEGIN { n = split(req, R, ",") }
        $1 == "CHECK" { cnt[$5]++; st[$5, $2]++ }
        END {
          for (i = 1; i <= n; i++) {
            nm = R[i]; if (nm == "") continue
            if (st[nm, "failure"]) f = f (f == "" ? "" : ",") nm
            else if (st[nm, "neutral"]) ne = ne (ne == "" ? "" : ",") nm
            else if (st[nm, "skipped"] && skipok != "true") sk = sk (sk == "" ? "" : ",") nm
            else if (cnt[nm] == 0 || st[nm, "pending"]) w = 1
          }
          if (f != "") print "fail " f
          else if (ne != "") print "neutral " ne
          else if (sk != "") print "skipped " sk
          else if (w) print "wait"
          else print "pass"
        }')
      case "$RES" in
        pass) emit "PASS" "$SHA0" "-" "none" "none" ;;
        "fail "*) emit "FAIL" "$SHA0" "-" "none" "${RES#fail }" ;;
        "neutral "*) say "required check ${RES#neutral } concluded neutral, which is not success"
                     emit "FAIL" "$SHA0" "-" "neutral" "${RES#neutral }" ;;
        "skipped "*) say "required check ${RES#skipped } was skipped; set ci_skipped_is_success: true if this repo path-filters its checks"
                     emit "FAIL" "$SHA0" "-" "skipped" "${RES#skipped }" ;;
      esac
    fi
    sleep "$INTERVAL"
  done
fi

# ---- aggregator (check-run): one gating check ----------------------------------------------

say "pr #$PR branch=$BRANCH sha=$SHA0 check=$GATE_CHECK"
while :; do
  NOW=$(date +%s)
  [ $((NOW - START)) -lt "$TIMEOUT" ] || emit "TIMEOUT" "$SHA0" "-" "none" "$(timeout_failed "$CHECKS")"

  check_head

  if ! read_checks; then sleep "$INTERVAL"; continue; fi
  read -r GSTATE RUN_ID <<< "$(gate_summary "$CHECKS")"
  case "$GSTATE" in none|pending) sleep "$INTERVAL"; continue ;; esac
  # The rollup can lag the runs: a still-open or newer gate run means the verdict is not in.
  if gate_unsettled "$RUN_ID"; then sleep "$INTERVAL"; continue; fi
  say "$GATE_CHECK=$GSTATE run=$RUN_ID"

  case "$GSTATE" in
    skipped)
      say "gate check $GATE_CHECK was skipped; set ci_skipped_is_success: true if this repo path-filters its checks"
      emit "FAIL" "$SHA0" "$RUN_ID" "skipped" "$GATE_ENC" ;;
    neutral)
      emit "FAIL" "$SHA0" "$RUN_ID" "neutral" "$GATE_ENC" ;;
  esac

  if [ "$GSTATE" = "success" ]; then
    # Authoritative confirmation: the run's own jobs, at the SHA we started on.
    # A green rollup over red jobs is a real state, not a theoretical one.
    if [ "$RUN_ID" != "-" ]; then
      forge run-head --slug "$REPO" --run "$RUN_ID" || forge_unknown
      RSHA=$(fv HEAD_SHA)
      if [ -n "$RSHA" ] && [ "$RSHA" != "$SHA0" ]; then
        emit "UNKNOWN" "$SHA0" "$RUN_ID" "run-sha-mismatch" "none"
      fi
      forge run-jobs --slug "$REPO" --run "$RUN_ID" || forge_unknown
      RFAIL=$(printf '%s\n' "$FORGE_OUT" | awk '$1 == "JOB" && $4 == "failure" { print $5 }' | paste -sd, -)
      if [ -n "$RFAIL" ]; then
        emit "FAIL" "$SHA0" "$RUN_ID" "green-rollup-red-jobs" "$RFAIL"
      fi
    fi
    if [ "$RERUNS" -gt 0 ]; then
      emit "FLAKY_RERUN_PASSED" "$SHA0" "$RUN_ID" "flaky" "none"
    fi
    emit "PASS" "$SHA0" "$RUN_ID" "none" "none"
  fi

  # Red. Ask the triage that already ran.
  FAILED=$(failed_names "$CHECKS")
  say "failed: ${FAILED:-unknown}"

  TSTART=$(date +%s)
  VERDICT="absent"
  while :; do
    VERDICT=$(triage_verdict_for_run "$RUN_ID")
    case "$VERDICT" in
      real|flaky|unparsed) break ;;
    esac
    NOW=$(date +%s)
    [ $((NOW - TSTART)) -lt "$TRIAGE_WAIT" ] || break
    sleep $((INTERVAL < 30 ? INTERVAL : 30))
  done
  say "triage verdict: $VERDICT"

  case "$VERDICT" in
    real)
      emit "FAIL" "$SHA0" "$RUN_ID" "real" "$FAILED" ;;
    flaky)
      if [ -n "${CI_NO_RERUN_BRANCH_PREFIX:-}" ]; then
        case "$BRANCH" in
          "$CI_NO_RERUN_BRANCH_PREFIX"*) emit "FAIL" "$SHA0" "$RUN_ID" "flaky-owned" "$FAILED" ;;
        esac
      fi
      if [ "$RERUNS" -ge "$MAX_RERUNS" ]; then
        # Same test failing again after a rerun is not a flake.
        emit "FAIL" "$SHA0" "$RUN_ID" "flaky-twice" "$FAILED"
      fi
      [ "$RUN_ID" != "-" ] || emit "UNKNOWN" "$SHA0" "-" "flaky-no-run-id" "$FAILED"
      say "rerunning failed jobs (same sha) — attempt $((RERUNS + 1))/$MAX_RERUNS"
      if forge rerun-failed --slug "$REPO" --run "$RUN_ID"; then
        RERUNS=$((RERUNS + 1))
        record_rerun "$SHA0" "$RUN_ID" "$FAILED"
        sleep "$INTERVAL"
        continue
      fi
      emit "FAIL" "$SHA0" "$RUN_ID" "rerun-failed-to-dispatch" "$FAILED" ;;
    *)
      # Fail closed. No triage, no guess, no rerun.
      emit "UNKNOWN" "$SHA0" "$RUN_ID" "triage-$VERDICT" "$FAILED" ;;
  esac
done
