---
# stu per-repo config. Delete a line to fall back to its derived default.
owner:
project:
# The project guide file the agents read. A CLAUDE.md that only @-imports another file does not
# carry the guide: name the imported file here instead.
guide:
run_home:
worktrees_dir:
github_repo:
# ci_* keys are exported by stu-env as CI_* and read by stu-ci-wait (defaults shown).
# The ONE check whose conclusion gates merge:
ci_gate_check: ci
# Workflow file that posts it (e.g. build.yml); empty skips the check:
ci_gate_workflow:
# Label that arms an auto-merge actor; empty means none:
ci_merge_label:
# check-run | daemon-status (a separate auto-merge service merges on green):
ci_mode: check-run
# daemon-status only: the gating context-name prefix:
ci_status_prefix:
# Extra issue-search qualifiers /stu:fix-campaign's triage filter appends (e.g. -label:wontfix):
triage_extra:
# More ci_* keys, all optional; a blank or absent key means derive (defaults shown):
#   ci_timeout: 5400                seconds stu-ci-wait waits for a verdict; blank means 5400
#                                   there. stu-verify bounds each command by this key too, and
#                                   uses 1800 when it is blank
#   ci_triage_command:              an executable called `<slug> <pr> <run-id>` for a red run;
#                                   its first output word is one of real|flaky|absent|stale|
#                                   unparsed, and only flaky is rerun
#   ci_triage_wait: 900             seconds to wait for the triage command; 0 when there is no
#                                   triage command
#   ci_no_rerun_branch_prefix:      a flaky verdict on a branch with this prefix is reported,
#                                   never rerun
#   ci_gate_source:                 e.g. app:github-actions; only that source's newest gating
#                                   check counts
#   ci_skipped_is_success: false    true|false; whether a skipped gating check passes
# Row keys. A flat config (no repos table) may set every one of them here in the frontmatter;
# a multi-repo config sets them per repo (see the comment below). Blank means derive:
#   host:                           the forge host; derived from the remote URL, else github.com
#                                   (set it for GitHub Enterprise Server)
#   initial_version:                the version of a repo's first release, used when it has no
#                                   earlier tag
#   slug, remote, base, visibility (public|private|unset), mode (work|pr-only|park),
#   merge_mode, merge_method (default squash), ci (aggregator|list|none), required_checks,
#   tag_by, tag_format, version_rule, pin_files, human_checkpoints, issues_repo
---

<!--
Each section below answers one question the plugin asks about this repo. Write the answer
under its heading, in plain Markdown. Leave a section empty (comments do not count) and the
plugin uses the default named in its question. Examples are for shape only; use your own.

A family of repos worked as one run is configured in one config file with a repos table. It is
documentation only here: this template is a flat config, so write the table into your own
config, never into this comment. Shape (every line indented; use your own names):

  ## repos

  ### app
    path: ~/Dev/app
    slug: acme/app
    remote: origin
    base: <base>
    visibility: public
    mode: work
    merge_mode: direct
    ci: aggregator

  ### lib
    path: ~/Dev/lib
    slug: acme/lib
    ...

The first row is home. In a family of two or more repos each row needs path, slug, remote, base,
visibility, mode, merge_mode and ci (merge_mode is not needed in mode pr-only), and a
`verification-commands` section with at least one fenced command (written `## verification-commands`
for home, `## verification-commands @<name>` for the others); the other row
keys above are optional. A section
that answers a question for one repo only is written `## <id> @<name>` (for example
`## verification-commands @lib`), where <name> is a row; the unsuffixed section belongs to the
home row. completion-mode, stop-condition-2 and deep-pass-model are family-only and cannot take
an `@<name>` suffix, and the keys owner, project, run_home and triage_extra stay in the
frontmatter, never on a row.
-->

## merge-mode
<!--
How does the merge gate act on a passing unit? The mode itself is not written here: it is the
`merge_mode` key on the repo's row (direct, label-handoff, report-only or direct-push), and the
merge label is the row's `ci_merge_label` key. A repo with a single flat config and no row may
instead give the mode as a `Mode: <word>` line in this section; that is the only mode input this
section carries. In a flat config an empty section means direct; a non-empty section needs a
`Mode: <word>` line (a lone mode word in prose is read as the mode, with a warning), or the
config is an error.

This section supplies only the detail around the mode, and only for label-handoff:
- the provenance-comment prefix the gate writes just before labelling (followed by the full SHA);
- whether the auto-merge actor is GitHub native auto-merge, which the gate then enables through
  `arm` (say so in plain words; otherwise the gate arms the label only);
- anything about a separate auto-merge service the gate cannot learn elsewhere, such as whether
  the label also gates CI (then no CI evidence exists before the label).
The gate builds the merge and arm commands itself; do not give one here.

For shape (an illustration of the actor, not something the gate runs):
  Mode: label-handoff
  Provenance prefix `gate-approved:`. The actor is GitHub native auto-merge. The label does not
  gate CI.

  # GitHub example
  gh pr merge <pr> --auto --squash --match-head-commit <sha>
-->

## after-pass-steps
<!--
What must happen after a unit passes the gate or lands, and how is each step proved to have
worked? Empty means nothing beyond the tag the plugin itself creates when `tag_by` is `stu`.

One record per step, written `### <step name>`, then these keys, one per line:
  when: pass | landed       -- `pass` runs when the gate passes, `landed` only once the work
                               is on the base branch
  run: <command>            -- run from the repo's worktree
  check: <command>          -- exits 0 only when the step took effect; it is also the retry
                               test: a step whose check already passes is not run again
  required: true | false    -- default true; a failed `false` step is reported and never keeps
                               the unit open
Every key but `required` is mandatory. A step must not be named `tag` (the plugin's own tag
step) and its name must not contain a comma.

For shape (indented so it is not a heading):
  ### notify-board
  when: landed
  run: scripts/post-release-note
  check: scripts/release-note-posted
  required: false
-->

## extra-gate-rows
<!--
Does the merge gate check anything beyond its built-in rows? Empty means no.

One record per row, written `### <row name>`, then:
  run: <command>                  -- run from the repo's worktree at the evaluated commit
  pass: exit0 | contains <text>   -- `exit0`: the command exits 0; `contains <text>`: its
                                     output contains the text
  also: brief, implementer, reviewer   -- optional; the other seats a rule also applies to
Both `run` and `pass` are mandatory; a row missing one fails the gate as a config error.

For shape (indented so it is not a heading):
  ### docs-built
  run: scripts/build-docs --check
  pass: exit0
-->

## auto-merge-setup
<!--
If an auto-merge actor merges PRs here, how is it set up? Empty means none: skip every
daemon step, and a label-handoff run has no extra commands beyond `merge-mode`.

Name which actor this repo runs; the command that cancels its evaluation of one PR and the
one that shows its status (daemon only); the label it treats as a merge instruction; where
its expected-checks configuration lives; how the gate takes a PR off it ("Revoke a claim"
in the merge gate). Then the read-only commands for a PR still open a cycle after `READY:`:
one for overall status, one that diagnoses a single PR. None may change state.

For shape (GitHub native auto-merge, no daemon):
  Label `ready-to-merge` arms GitHub auto-merge; required check `ci`, posted by the
  `build.yml` workflow. Revoke: `gh pr merge <pr> --disable-auto`, then remove the label.
  Stuck PR: `gh pr view <n> --json labels,autoMergeRequest,mergeable,mergeStateStatus` and
  `gh pr checks <n> --required`; a red check is read with `gh run view <id> --log-failed`
  before any rerun.
-->

## review-evidence
<!--
How does the merge gate establish review rows 2-4 (a review exists at the head SHA, no
finding is still open, declined findings are disclosed)? Empty means reviews come only from
the stu:reviewer agent: the review file for the PR must name the head SHA as its reviewed
SHA with a verdict of APPROVE (or APPROVE WITH FIXES, every fix re-reviewed at the later
SHA), files under RUN_HOME's run directory, and row 4 does not apply.

With an automated review tool, name: the command that lists finished reviews for a branch
with their git ref; the command that lists OPEN findings for a branch, and any default that
under-reports (e.g. a missing branch flag that reports "no open jobs" while some sit open);
the read-only commands that list a branch's closed review jobs and print each job's
comments, for row 4. Never a command that comments on or closes a job. A per-commit review
tool that is clean at the head has reviewed one commit, not the branch: ask for one job per
commit, so the listing the gate reads covers every commit of the change.

For shape:
  Finished: `review-tool list --branch <b> --done`. Open: `review-tool list --branch <b>
  --open` (without `--branch` it only shows the current checkout). Closed jobs:
  `review-tool list --branch <b> --closed`; comments: `review-tool show <job>`.
-->

## review-tool
<!--
Does this repo use an automated review tool as a second opinion beside stu:reviewer? Empty
means no: the stu:reviewer file at the reviewed SHA is the only review record.

If yes: the exact command that lists OPEN findings for a BRANCH; how to wait for a review
to finish; what to do when it reports no job for HEAD; and any default that under-reports.

For shape:
  `review-tool wait --sha <sha> --timeout 900`, then `review-tool list --branch <b> --open`.
  No job for HEAD: trigger one with `review-tool run <sha>`; never treat "none" as clean.
-->

## pre-push-guard
<!--
Does a pre-push hook refuse a push while the review is unfinished (an open finding, a
review of the pushed SHA still running, or no finished review for that SHA)? Empty means
none: the implementer enforces the push rule by its own check.

If yes: its name, how it is installed, what it lets through when the review tool is down
(the implementer then confirms review state itself), and its human-only override, which
agents never set.

For shape:
  `.githooks/pre-push`, installed by `git config core.hooksPath .githooks`. Fails open when
  the review tool is unreachable. Override: `SKIP_REVIEW_GUARD=1`, owner only.
-->

## escalation-core-computation
<!--
What is this project's core computation, the logic whose change earns a top-tier model
(orchestrator Opus-escalation condition 1)? Empty means whatever the project guide names as
core logic counts; if it names none, the orchestrator judges and records its call in the
`ESCALATION:` line. Reading, storing or displaying such a value does not count.

For shape:
  The module the project guide names as its core logic.
-->

## escalation-security-boundary
<!--
Which code paths form this project's security boundary (orchestrator Opus-escalation
condition 2)? Empty means whatever the project guide names as a security boundary counts;
if it names none, the orchestrator judges and records its call in the `ESCALATION:` line.
Working inside an existing boundary-scoped path does not count.

For shape:
  A new admin command, a change to how credentials are loaded, a new way to bypass a
  permission check.
-->

## escalation-count-command
<!--
Is there a command that counts escalations per day: dispatches on the top-tier model, the
agent-issued share, and how many carried the `ESCALATION:` line? Empty means none; the
orchestrator keeps the count by hand in the scoreboard.

For shape:
  `tools/escalations.sh --since 1d`
-->

## park-or-decide-rows
<!--
How do the orchestrator's park-or-decide rows apply here? Empty means only the generic
rows: production is whatever the project guide calls production, row 3 parks on the core
computation named in `escalation-core-computation` (or the guide's core logic), and row 5
covers screens and navigation.

Name which environments count as production for row 2 (anything serving real users,
whatever it is called), and which other actions count, e.g. adding or widening a CI
workflow when CI minutes are paid; what the core computation's semantics are for row 3;
and which surfaces count for row 5 beyond the obvious screens.

For shape:
  Row 2: any environment other people rely on. Row 5: anything a user can see or reach.
-->

## reviewer-invariants
<!--
Which two to four invariants must a reviewer check on every diff, the ones whose
violation fails silently? Empty means the reviewer checks the project guide's
non-negotiables instead.

For shape:
  - Every external input is validated where it is used, not only at the edge.
  - Every file write goes through the atomic-write helper, never a direct open-and-write.
  - Every new config key gets a default and a validation test.
-->

## reviewer-provisioning
<!--
What Bash command provisions and tears down a private database or service instance for a
reviewer, and which argument scopes it to a directory? It must run from Bash: the
reviewer's tool list is fixed, so provisioning must be a Bash command: an MCP tool cannot be
granted to the reviewer by config. Empty means there is none, and a finding that needs one is
reported UNVERIFIED.

For shape:
  `<your provision command> <name> <path>` and `<your teardown command> <name>`; for example
  `make -C <detached checkout> <target>` to provision against the reviewed checkout.
-->

## implementer-traps
<!--
Which five to ten rules from the project guide does an implementer break most often
without noticing, the ones whose violation fails silently? Empty means the implementer
reads the project guide's non-negotiables instead.

For shape:
  - Input validation is defence in depth: never rely on a single layer.
  - Generated files come from the generator, never from hand edits.
  - Never clear the shared build cache; use the project's cleanup target.
  - No backticks, `$(...)` or `$VAR` in an issue or PR title: they execute as shell.
-->

## repo-map
<!--
A five-line map of the repo for the scout: which directories hold which layer, which names
collide across layers, where guards and specs live. Empty means the scout maps the repo
itself from the project guide and the top-level directories.

For shape:
  Some names repeat across layers; narrow by directory before by term. `src/` core,
  `tools/` scripts, `tests/` guards, `docs/specs/` specs.
-->

## language-servers
<!--
Which languages here have a language server configured, and which do not (so the scout
knows when grep is the only route)? Empty means unknown: the scout tries LSP and falls back
to grep as its rules describe.

For shape:
  The main source language has a server. Shell scripts and config files do not: grep only.
-->

## verification-commands
<!--
What exact commands verify a change here, and every way a run here can look green while
proving nothing? Empty means the implementer and orchestrator use the commands the project
guide names, and the generic traps.

Name: the CI lanes, their commands and path selectors (or the guide that owns them), and
which ones a change touches; the test command with an explicit timeout (macOS ships no
`timeout`; use the runner's own flag); a typecheck that covers test files; the lint
invocation in the exact form that works; the formatter check on changed files only;
whether the build tool exits 0 on a failed or zero-test run; any blocking lane easy to
forget locally; the test framework and required file header for new tests; the
integration suite and its command, or a statement that none is required. Run everything
from the worktree, never piped through `tail`.

Put every command to run in a fenced block, one command per line (a line starting with `#`
is a comment). `stu-env commands verification-commands` reads only fenced lines, and
`stu-verify` runs exactly those for a repo with no CI; a repo row in a multi-repo family
needs at least one.

For shape:
  `make fmt`, `make lint`, `make test` (with the runner's own timeout flag); the
  integration suite `make test-integration` when behaviour across components changed, from
  the worktree. The linter reports clean when pointed at the wrong path; plant a violation
  once to confirm it is live. Count tests from the results file. CI lanes are documented in
  `docs/ci.md`.
-->

## verification-setup
<!--
What must run once in a fresh checkout before the verification commands can pass (install
dependencies, generate code, build a tool)? Empty means nothing: the verification commands
run in the fresh checkout as it is.

Fenced block, one command per line (a line starting with `#` is a comment), run from the
checkout root before `verification-commands` by `stu-verify`, the merge gate's runner for a
repo whose `ci:` is `none`. `stu-env commands verification-setup` reads only fenced lines.

For shape (written inside a fenced block):
  make deps
-->

## ci-traps
<!--
Which traps has this repo's own CI produced, beyond the merge gate's six? Empty means none
recorded yet.

Name where the authoritative list of expected contexts lives (and anything that reads like
it but is not); how a skipped
check's path selectors are resolved and matched; the branch CI filters against, if not
`main`; and which logs are archived rather than live.

For shape:
  Expected contexts: the branch protection settings. Path selectors live in
  `ci/paths.yml`. Saved logs can be stale; read the live run.
-->

## tooling-traps
<!--
Which traps has this repo's tooling actually produced in a fix campaign, beyond the
generic table in /stu:fix-campaign? One row each: the trap, then what to do. Empty means
the generic table is the whole list.

For shape:
  | A test runner truncates its results when killed | Retry after a clean reset; count from the results artifact |
  | The editor's language server floods false errors | Ignore; the CLI test target is the authority |
  | Two test runs contend for one shared resource | Serialize them; never delete the other run's lock |
  | Clearing the shared build cache | Never. Use the project's cleanup target |
-->

## stop-condition-2
<!--
Which disagreements between two sources of truth must always stop a run (stop condition 2),
the ones where picking wrong enshrines a wrong value in code and nothing fails? Empty means
only the ones the project guide names.

For shape:
  Which of two config files wins when both set the same key.
-->

## completion-mode
<!--
What completion mode does an objective file with no `completion:` line default to? This
section is family-only: one answer for the whole config, and a per-repo `@<name>` form is an
error. Empty means `merged`, the only value a direct-merge or report-only gate can mean.
`ready` is read against the merge mode of each unit's own repo row, and only means something
for a row whose gate runs in label-handoff mode; a run whose PRs should end once every PR
carries the label at a verified SHA names it. `integrated` is never a sensible default: it
needs an epic branch and a `Final unit:` in the objective.

For shape:
  ready
-->

## deep-pass-model
<!--
Is a large model available for one deep pass over a large context that emits little (the
last row of the run skill's routing table)? Empty means no: that row does not apply, and the
pass runs on the row its agent would otherwise use.

If yes: its exact model ID; its prices relative to the default driver (cache read, input,
output); the cache-read share above which it wins and the output ratio at which it breaks
even; any near-identical model ID never to use in its place; and the price of the mid-tier
model against the top tier. Date the numbers; prices move.

For shape:
  As of <date>: `<model-id>`. Cache reads 0.5x the driver, input 2x, output 3x; wins above
  90% cache reads with output under 2% of input. Never `<sibling-id>` (cache reads priced
  4x). Mid tier is 0.2x the top tier.
-->

## product-taste
<!--
What is the project's tiebreaker when two implementations are both correct? Link the taste
guide if one exists. Empty means no tiebreaker: the orchestrator decides on the merits and
records the decision.

For shape:
  When two implementations are both correct, ship the one that leaves the user less to look
  at and less to decide. See `docs/taste.md`.
-->

## delivery-guide
<!--
Where is the project's delivery guide (branches, commits, PRs, merging, the review cycle),
and which review tool does it use? Its shape should be: nothing is pushed until its review
is clean. Empty means there is none: follow the push rule and the review cycle in the
dispatch prompt.

For shape:
  `docs/delivery.md`; reviews by the stu:reviewer agent.
-->

## routed-skills
<!--
Which other project skills does a run route to? One line each, with what it is for. Empty
means none.

For shape:
  - `/<your-skill>` — what it is for.
-->

## publishable-note
<!--
For a private repo whose released tag a public repo's brief must mention: what single line may
the public brief carry beyond the tag? Give ONE command, in a fenced block, that prints that
line, with the literal placeholder {tag} where the tag name goes. The orchestrator fills it in
and uses only the first line of the output. Empty means the public brief carries the tag alone.

For shape (written inside a fenced block):
  git log -1 --format=%s {tag}
-->

## fix-when-touched
<!--
How does this project list deferred findings, so a run can find the ones on files a unit
edits, and mark one resolved once the unit lands? Empty means none: no deferred finding is
folded into a unit's brief. A prose-only answer is read as none: write records.

One record per finding source, written `### <source name>`, then these keys, one per line:
  match: <command with {paths}>      -- lists the deferred findings on the unit's paths; the
                                        orchestrator puts the unit's paths where {paths} is
  resolve: <command with {finding}>  -- marks one finding resolved once the unit lands
Both keys are mandatory.

For shape (indented so it is not a heading):
  ### deferred-list
  match: scripts/deferred list --paths {paths}
  resolve: scripts/deferred resolve {finding}
-->

## id-numbering
<!--
Does this project number things in order (migrations, fixtures, test files) with an allocator
an implementer must use instead of counting by eye? Empty means no allocator: the implementer
follows the numbering rule in the project guide, if it has one, then the lane's pre-allocated
range.

One record per kind of identifier, written `### <kind>`, then ONE of:
  run: <command>     -- a shell command that prints the next identifier, run from the worktree
  tool: <tool name>  -- an MCP tool the implementer calls, for a project whose allocator is not
                        a shell command

For shape (indented so it is not a heading):
  ### migration
  run: scripts/next-migration-number
-->

## brief-preflight-rows
<!--
Does this project have checks a brief writer must make before dispatching a unit, beyond the
built-in pre-flight table? Empty means no.

One row per check, written as a plain line `- <the question> -> <the miss it prevents>`. The
brief writer treats each as one more row of the pre-flight table.

For shape (indented so it is not a heading):
  - Does the unit change a generated file? -> Name the generator command; a hand edit is overwritten.
-->

## implementer-blocking-rules
<!--
Which project rules stop a unit when broken, beyond the traps already listed under
`implementer-traps`? Empty means none beyond those.

One rule per line, written `- <the rule>: <what to do instead>`. The implementer treats a
broken rule as a stop and reports it, not as a note.

For shape (indented so it is not a heading):
  - Never edit a generated file by hand: regenerate it with the project's generator.
-->
