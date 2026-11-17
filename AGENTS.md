# stu — project guide

stu is a Claude Code (and Codex) plugin for long autonomous runs: a blind supervisor, SHA-bound
independent review, a separate merge gate, and parked questions settled later. This file is the
guide every agent and contributor follows. The stu config for this repo is `.claude/stu.md`; where
it answers a question in more detail, it says so here.

## Layout

- `skills/` — the slash-command skills (`run`, `fleet`, `settle`, `fix-campaign`, `init`, with the
  config template in `skills/init/stu.template.md`).
- `agents/` — the subagent definitions (`stu:orchestrator`, `stu:reviewer`, `stu:merge-gate`, …).
- `bin/` — thin `stu-*` wrappers over `scripts/*.py`, the Python core; each script has its
  `*_test.py` beside it.
- `tests/` — shell suites, the content and dispatch lints, and the Python 3.9 floor.
- `hooks/` — the plugin's tool hooks. `codex/` and `.codex-plugin/` — the Codex port.
- `docs/` — `design-rationale.md` (why every rule exists) and the public site (`CNAME`, served).
- `.githooks/pre-push` — the tracked deny-scan hook; see Delivery for installing it.

## Non-negotiables

Each of these fails silently: green tests, no error, a wrong result nobody is told about.

**Portability.**
- Every `scripts/*.py` and `tests/*.py` parses as Python 3.9 and uses the standard library only.
  Newer syntax runs on your machine and breaks users' (`tests/python_floor.py`). No third-party
  dependency, ever.
- macOS ships no `timeout`, and BSD `sed`/`grep` differ from GNU. Scripts users run must work on
  macOS, Linux and WSL.

**Prose and parser move together.**
- A return block, dispatch line or config section is a contract between the prose that tells an
  agent what to write (`agents/*.md`, `skills/*/SKILL.md`) and the script that checks it
  (`run_check.py`, `judgment_return.py`, `settler_return.py`, `stu_env.py`). Change both, and a
  test, in the same diff. Drift between them passes every test.
- The config template is a closed registry: every `stu-env section|commands|records <id>` used in
  `skills/` or `agents/` has a `## <id>` in the template, and every template section is read
  somewhere (`tests/content_lint_test.sh`). A new key also lands in `stu_env.py`, the init skill
  and a test.
- The fleet skill's dispatch lines match each agent file's (`tests/dispatch_lines_lint.py`).
- Agent and skill names are always prefixed (`stu:reviewer`, `/stu:settle`). Skills and agents
  call the `bin/` wrappers, never `scripts/` paths.

**Fail closed.**
- A check that cannot read, parse or run its input refuses or FAILs. A missing file, empty
  output or unparsed line is never a pass.
- Never weaken a guard or relax an assertion to make a suite pass. A red suite against `main` is a
  finding about the guard.
- Never bypass a hook (`--no-verify`, `core.hooksPath` overrides, a skip variable). A refusal is a
  stop, reported as-is.

**Every rule is backed by a measured failure.** A new rule in a skill or agent gets its reason
(the incident or the measurement) in `docs/design-rationale.md`, not in the skill text.

**Public repo.** Nothing private reaches a tracked file, a commit message or a PR: no
private-repo content, internal paths, personal names or machine paths. `tools/deny-scan.sh`
checks against a private list kept outside the repo; a reader still has to catch a paraphrase.

**Tests.** Tests never touch the network or the real HOME: temp repos with local bare remotes, a
temp HOME, `STU_CONFIG`, and `tests/fake_gh.py` standing in for `gh`.

## Releases

`main` on `keavi-app/stu-claude` is the release: the marketplace installs from it.

- A change that ships to users bumps the version in `.claude-plugin/plugin.json` and
  `.codex-plugin/plugin.json` together, and adds a top `## <version>` entry to `CHANGELOG.md`
  saying what changed for an owner. The merge gate checks the three agree.
- Put the version in the PR title, e.g. `Add stu:designer, one decision-ready design round (0.2.21)`.
- Tags are plain `<version>` (no `v`), on the commit that landed the bump. The merge gate pushes
  the tag after a unit lands; never move or delete an existing tag.

## Delivery

- Branch from `main`; never commit to it directly. Work in a worktree under
  `~/Dev/stu-claude-worktrees/` when agents are running; the main checkout is read-only then.
- Commit locally. RoboRev reviews every commit (git hooks below). Wait for the review with
  `roborev job wait <sha>`, read its content, fix every HIGH and genuine MEDIUM on the same branch,
  and repeat until `roborev fix --list --branch <branch>` is empty. Never run bare `roborev fix`:
  it edits and commits.
- Nothing is pushed until its review is clean. Batch fixes into one push.
- Open a PR into `main`. It is squash-merged, so the PR title becomes the commit subject: keep it
  current. A PR that passes the stu merge gate (a `stu:reviewer` review and RoboRev both clean at
  the head SHA, `make test` green) may be merged by the gate: that is standing authorisation.
- No backticks, `$(...)` or `$VAR` in an issue or PR title: they execute as shell.

**Git hooks (once per clone).** The hooks live in `.git/hooks`, not the tracked `.githooks/`,
because they hold machine paths. In a fresh clone: `roborev init`, then `stu-pre-push --install`,
and make `.git/hooks/pre-push.local` run `.githooks/pre-push`. A push then runs the deny scan, the
RoboRev push guard (`tools/roborev-push-guard.sh`: it refuses a branch push with an open review
job, a review of the pushed SHA still running, or no finished review for it), and stu's
public-repo check. The guard warns and lets the push through when roborev is down: confirm review
state yourself then. `STU_SKIP_ROBOREV_PUSH_GUARD=1` is for humans only; agents never set it.

## When to file an issue

Do **not** file an issue for something you noticed while doing something else. Write it under
`~/.stu/keavi-app-stu-claude/ledger-inbox/`; only the owner promotes a ledger entry. The one
exception needs all three: it is a defect (not an improvement); it is user-reachable, corrupts
data, or is a broken safety net; and it exists on `main` today, verified against code. Issues go
to `keavi-app/stu-claude`.

## Verification commands

```
make test
git ls-files -z | tools/deny-scan.sh -0
```

`make test` runs every `scripts/*_test.py`, every `tests/*_test.sh` (the content and dispatch
lints included) and the Python floor; about 5 minutes. There is no CI: these are the gate.

## Test suite traps

- `make test` stops at the first failing suite; read each suite's own ok/failed counts, not just
  the exit code, and never pipe it through `tail` (that masks the exit status).
- The deny scan exits 2 when its private list is missing: that is a failure, not a skip.
- A content-lint change that matches nothing passes: plant a violation once to confirm it is live.

## Product taste

When two implementations are both correct, ship the one that is checked mechanically (a script
and a test) over one that relies on an agent reading prose, and the one that asks the owner less.
