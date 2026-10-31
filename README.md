# stu

Made by [Keavi](https://keavi.app)

**Let it stew.**

stu is a Claude Code plugin for long autonomous runs. Your main session becomes a blind
supervisor: it dispatches disposable orchestrators, never reads the work itself, and checks
every return against a unit-ID scoreboard, failing closed when a check does not pass. Each
change is reviewed by an agent that did not write it, bound to an exact commit SHA, and
merged by a separate gate that collects its own evidence; questions only you can answer are
parked, and settled later in a fresh session with `/stu:settle`.

- **A supervisor that never reads the work.** It holds paths and ID sets, so its context is
  designed to stay flat however much work the run does. Five set-operation checks on every
  return catch a spinning or self-certifying run mechanically. A return that fails one gets
  at most one repair request; after that the run stops rather than continuing on something
  it cannot verify.
- **Independent review at an exact SHA, plus a separate merge gate.** The reviewer works in
  its own detached checkout of the commit it reviews. The merge gate is handed only a PR
  number and a worktree path, runs its own commands, and by default merges with
  `--match-head-commit`, so the code that merges is the code that was reviewed.
- **Questions park; the run keeps going.** A question parks one unit, with a recommendation.
  When the run stops, `/stu:settle` walks you through the parked questions one at a time and
  writes your answers back for the next run.
- **Every rule is backed by a measured failure.** [docs/design-rationale.md](docs/design-rationale.md)
  carries the incident or the number behind each one.
- **Cost control is built in.** Turn and context budgets per agent, enforced live by a hook,
  a native `maxTurns` backstop, and a model per role.

## Install

```bash
claude plugin marketplace add keavi-app/stu-claude
claude plugin install stu@keavi --scope user
```

On any supported Claude Code version (see Requirements), one step also works:

```
/plugin install stu --marketplace keavi-app/stu-claude
```

Requirements:

- Claude Code 2.1.310 or later, with subagents, skills, and plugin hooks.
- `gh`, authenticated for the target repo. The merge gate merges with the row's
  `merge_method` (squash unless set) and assumes branch protection that requires status checks.
- git 2.31 or later, Python 3.9+ (standard library only) and `bash`.
- macOS, Linux or WSL. Native Windows is unsupported.
- Optional: a language server for your language. The scout and verifier use it to find
  references and fall back to grep when there is none.

## First run

1. **Configure the repo.** In a session in the repo, run `/stu:init`. It derives what it can
   (owner, project slug, project guide, run home, worktrees directory, GitHub repo), then
   asks one question per config section: merge mode, review evidence, the invariants a
   reviewer checks, verification commands, and so on. Every section can be left empty to
   take its default. You choose where the config lives: `<repo>/.claude/stu.md` (committed,
   shared) or `~/.stu/<project>/stu.md` (private, nothing added to the repo).
2. **Run one small unit.**

   ```
   /stu:run "<a one-unit objective>"
   ```

   The supervisor writes an objective file with the unit list and scoreboard under the run
   home (default `~/.stu/<project>/`) before any work starts, then cycles through
   orchestrators until the run is done or a stop condition fires. `/stu:run` also takes a
   handoff path or an issue number, and `overnight` fans the work out into parallel lanes.
3. **Settle what it parked.** A run that stops with questions parked ends with a line like
   `Next: /stu:settle <objective path>`. Run that in a **fresh** session. Settle shows each
   question with the run's recommendation, writes your answers into the objective, and
   hands back the line that resumes the run. A run that parked nothing says so.

## What's in the box

| Skill | Purpose |
|---|---|
| `/stu:init` | Write this repo's stu config, one question at a time. |
| `/stu:run` | The supervisor contract: objective, scoreboard, fail-closed checks, cycle cap. |
| `/stu:settle` | Answer a stopped run's parked questions in a fresh session. |
| `/stu:fix-campaign` | Triage open issues and drive fixes to merge; what an orchestrator runs. |

| Agent | Model | Role |
|---|---|---|
| `stu:orchestrator` | opus (sonnet on cycle 2+ with groomed briefs) | Grooms briefs, dispatches the fleet, writes handoffs. Writes no code. |
| `stu:implementer` | sonnet | One brief, one worktree. Commits what is green, hands off rather than running long. |
| `stu:reviewer` | sonnet | Read-only review of a diff it did not write, at a named SHA. |
| `stu:merge-gate` | sonnet | Collects its own evidence for one PR; merges at the SHA, labels it for an auto-merge actor, or reports. |
| `stu:scout` | haiku | Cheap locator: `file:line` answers, never file dumps. |
| `stu:verifier` | sonnet | Is this premise or claim true on the base branch today? |

**Hooks.** A `PostToolUse` hook (`scripts/turn-guard.py`) tells a stu orchestrator or
implementer its own turn count and context size against its budget, on approach, at the
bar, and every 25 turns past it. It exits immediately for every other session and agent.
A `PreToolUse` hook is the publish guard's tool-call half; see Publishing safely.

**`bin/`** (on the `PATH` of plugin sessions):

| Command | Does |
|---|---|
| `stu-env` | Resolves this repo's paths and config; `stu-env section <id>` prints one config answer. |
| `stu-claims` | A shared claims file, so two concurrent runs never work the same unit. |
| `stu-ctx` | Prints this session's context size, band, and growth. |
| `stu-ci-wait` | One background call, one line: waits for a PR's CI verdict instead of polling. |
| `stu-approve` | `stu-approve <id> <sha>`: records the owner's approval of one commit for a before-push checkpoint. Human-only. |
| `stu-forge` | Forge facts for the run kit (pull requests, labels, tags, checks) with a fail-closed output contract: result lines, then one `OK` or `ERROR <class> <detail>` line. |
| `stu-pre-push` | The publish guard's git `pre-push` hook: `--install` writes it, `--check` prints `INSTALLED` or `MISSING`. |
| `stu-run-check` | The supervisor's mechanical checks on one orchestrator return; `--approved` lists the approved awaiting units. |
| `stu-verify` | Runs a repo's verification commands at one commit in the background; prints one `VERIFY: PASS\|FAIL\|PENDING` line. `--retry` re-runs a failed commit once. |

## Several repos in one run

One stu config can describe a family of repos. A `## repos` table in the config holds one
`### <name>` block per repo (path, slug, remote, base, visibility, mode, merge mode and CI
kind, plus optional keys such as `merge_method`, `tag_by`, `required_checks` and
`human_checkpoints`); the first row is home. A config section that answers for one repo
only is written `## <id> @<name>`, for example `## verification-commands @lib`. Unit IDs in
the objective are qualified by repo (`app#12`, `lib:docs`). A config with no table is a family of
one, and every row key may be set in its frontmatter, so a single-repo config keeps working
unchanged. `/stu:init` does not write the table; the template's top comment shows its
shape, and `stu-env` exits 3 naming the fix when a row or section is wrong.

## Merge modes

Each repo row has a `merge_mode`, and the merge gate acts on it:

| Mode | The gate |
|---|---|
| `direct` | Merges the PR itself at the reviewed SHA. |
| `label-handoff` | Applies the row's merge label at the reviewed SHA and leaves merging to an auto-merge actor (GitHub native auto-merge, or a separate service). |
| `report-only` | Reports a verdict; a human merges. |
| `direct-push` | No PR: pushes the reviewed commit to the base branch. |

A row with `mode: pr-only` means `report-only`. `merge_method` (default `squash`) says how a
direct merge is made. A flat config may give the mode as a `Mode: <word>` line in its
`merge-mode` section.

## Publishing safely

For a repo whose pushes must be checked, the publish guard enforces at the push, not at the
command. A repo is strict when its row is `public`, or has a `before-push` checkpoint.

- **The git `pre-push` hook does the enforcement.** `stu-pre-push --install` writes it
  (chaining any hook already there). On a before-push row it refuses a push whose tip commit the
  owner has not approved, but only when the push comes from a Claude Code process (the
  `CLAUDECODE` environment variable is set); the owner's own terminal push passes, with one
  stderr line saying the approval check was skipped. On a public row, for every push, agent or
  human, it scans the pushed commits' messages and added lines,
  the ref name and an annotated tag's message for the names of the family's private rows. A run
  refuses to start on a strict row without the hook.
- **The tool-call hook is narrow.** It protects the approvals file, refuses hook bypasses
  (such as `--no-verify`) on strict rows, scans text sent through the forge CLI on public
  rows, and denies an MCP write that names a public row's slug (use git or the forge CLI instead). It never parses shell. A repo with no stu config is untouched.
- **Approval is human-only.** The owner runs `stu-approve <id> <sha>` from their own terminal,
  or as a `!` shell command in the session. An agent cannot run it.

Known limits:

- The approval rule keys on an environment variable. An agent process that strips `CLAUDECODE`
  from its environment is treated as a human push. A human push of an unapproved tip passes by
  design; the leak scan still runs on it.
- A push from a clone outside the row (not a worktree of its checkout) has no hook.
- When a push has no base the hook can resolve (a URL remote, or no tracking ref for the base),
  it scans every commit no remote-tracking ref holds instead of refusing; a commit already on a
  different remote's tracking ref is not re-scanned.
- A deliberately assembled bypass of the hook is not caught by text matching.
- A paraphrased private finding is caught only by the reviewer.
- The pre-push hook names the plugin copy that installed it. After a plugin update removes that
  copy, `stu-pre-push --check` reports `MISSING` and pushes from that repo are refused with a
  repair line; rerun `stu-pre-push --install` from the current plugin.
- `PASSED_IDS`, `APPROVAL_IDS` and `READY_IDS` prove a state of the forge or git, not that the
  gate passed; an orchestrator holding forge access could fabricate that state.
- The `!` approval channel could not be verified in a headless session; confirm it works in
  yours before relying on it.

## Forges and support

`stu-forge` is GitHub today; another forge's backend meets the contract in `scripts/stu_forge.py`.
GitHub Enterprise Server works by setting a row's `host` (otherwise it is parsed from the remote
URL, else `github.com`).

Not supported in this release: fork-based contribution, and merge queues (a run refuses to
start on a merge-queue row).

## Cost controls

Cost is roughly context size times number of turns, so stu bounds both.

| | Turn budget | Context soft / hard | Native `maxTurns` |
|---|---|---|---|
| Supervisor (main session) | cycle cap: 4, or 8 under `overnight` | 160k / 200k (`stu-ctx`) | — |
| `stu:orchestrator` | 120 | 120k / 160k | 190 |
| `stu:implementer` | 140 | 150k / 190k | 220 |

- **Soft** means finish the unit and hand off; **hard** means hand off now. Bands are
  absolute token counts, never a percentage of the window, and a failed context read
  counts as hard.
- The supervisor also watches **growth**: more than ~30k above its post-startup baseline
  ends the session at the next cycle boundary.
- The turn budgets and bands are enforced live by the hook; `maxTurns` is the hard stop
  behind them. `RUN_CTX_SOFT` / `RUN_CTX_HARD` override the bands.
- **Models per role** follow the table above. The orchestrator's model is a lookup, not a
  judgment: opus for cycle 1, sonnet once briefs are groomed, and opus again only with a
  literal `ESCALATION:` line naming one of its enumerated conditions.
- **Cache TTL:** `stu:orchestrator` alone writes its prompt cache with a 1-hour TTL
  (`experimental: cacheTtl: 1h` in its frontmatter), so a long wait on its children is a
  cache read rather than a rebuild. Every other role keeps the 5-minute default; see
  `docs/design-rationale.md`, "Cache TTL".

## Coming from a copied install

If you used the earlier copy-into-the-repo version of this kit:

1. Remove the copied run, settle and fix-campaign skills and the six agent files under
   `.claude/`, the copied scripts and their tests, and the turn-guard hook entry in
   `.claude/settings.json`. The plugin ships its own hook;
   leaving the old one in place warns twice.
2. Run `/stu:init`. Move the answers you wrote into the old `PROJECT-SPECIFIC` blocks into
   the matching config sections.
3. To keep your run history, set `run_home:` in the config to the old run home. Otherwise new runs start under `~/.stu/<project>/`.

## Further reading

[docs/design-rationale.md](docs/design-rationale.md) is the argument behind every rule:
why the scoreboard is sets of IDs and not counts, why the premise check moved off the
orchestrator twice before it worked, why the merge gate takes no evidence from its
dispatcher, and what was measured on the two projects where stu was built and replicated.
[docs/project-guide.template.md](docs/project-guide.template.md) lists what your
`CLAUDE.md` or `AGENTS.md` should cover for the agents to work well.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
