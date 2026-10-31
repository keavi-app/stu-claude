# Changelog

## 0.1.4

- `stu:orchestrator` writes its prompt cache with a 1-hour TTL (`experimental: cacheTtl: 1h`
  in its frontmatter), so a wait of 5 to 60 minutes on its children reads its context instead
  of rebuilding it. Every other role keeps the 5-minute default, and the content lint fails if
  another agent takes the key. Rationale, measurements and limits: `docs/design-rationale.md`,
  "Cache TTL".

## 0.1.3

- `stu-run-check` accepts `READY_IDS` for a unit still in `REMAINING_IDS` on a label-handoff row
  under `completion: merged`, as the run contract asks: the entry is checked as a labelled PR and
  the unit prints `OPEN ready-labelled:<slug>#<pr>,auto-merge-<on|off>` until `MERGED_IDS`
  records its landing. A `CLOSED_IDS` entry backed only by it is `BLOCKED
  tracking-field-does-not-close`, and a tracked unit outside `REMAINING_IDS` is `BLOCKED
  tracked-not-remaining`. Before-push, direct and report-only rows still reject it.

## 0.1.2

- The handoff format says run folders hold reports, briefs, logs and handoffs, never build products,
  derived data or source copies.
- The orchestrator no longer waits for CI before the gate on a label-handoff row where the merge
  label also gates CI; the CI evidence is read at the gate's confirm dispatch.
- `stu-run-check` reads a unit in both `CLOSED_IDS` and `MOVED_IDS` as CLOSED, not `OPEN moved`.

## 0.1.1

- `stu-run-check` blocks a return that lists an ID in `REMAINING_IDS` or `PARKED_IDS` and also in
  `CLOSED_IDS` or its row's closing field (`BLOCKED closed-but-remaining`), so a passed unit is
  closed in the cycle that passed it rather than one cycle later.
- The orchestrator puts an ID whose closing field it relays in `CLOSED_IDS`, never in
  `REMAINING_IDS`.
- A gate return saved in an earlier cycle may be relayed only when the unit's head is verified
  unchanged at the gate's sha in the current cycle.

## 0.1.0

- First release as a Claude Code plugin: install with `claude plugin install stu@keavi`.
- Skills `/stu:run`, `/stu:settle` and `/stu:fix-campaign`, and six agents namespaced `stu:`.
- `/stu:init` writes a per-repo config, kept in the repo or in `~/.stu/<project>/`, in place of
  hand-edited `PROJECT-SPECIFIC` blocks.
- The turn guard ships as a plugin hook, with a native `maxTurns` backstop on the
  orchestrator (190) and implementer (220).
- Helper commands on the plugin `PATH`: `stu-env`, `stu-claims`, `stu-ctx`, `stu-ci-wait`,
  `stu-approve`, `stu-forge`, `stu-pre-push`, `stu-run-check`, `stu-verify`.
- `stu-verify --retry` re-runs a failed commit's verification once; the merge gate uses it for a
  suspected flake and treats a second failure as final.
- In a headless session the supervisor relays a nested agent's completion to the orchestrator
  that dispatched it, without reading the agent's result.
- Multi-repo families: a `## repos` table with `### <name>` rows and `## <id> @<name>` sections,
  and merge modes `direct`, `label-handoff`, `report-only` and `direct-push` per row.
- New config keys: `host`, `initial_version`, `merge_method`, `ci_timeout`, `ci_triage_command`,
  `ci_triage_wait`, `ci_no_rerun_branch_prefix`, `ci_gate_source` and `ci_skipped_is_success`.
- The publish guard: a git `pre-push` hook on public and before-push repos (its approval rule
  applies to Claude Code pushes only; the leak scan applies to every push), and a `PreToolUse`
  hook that protects the approvals file.
- Minimum Claude Code version 2.1.310; macOS, Linux and WSL.
