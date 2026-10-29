# The brief — what one unit of work hands to an implementer

Read this when you are **writing** a brief: a grooming session before a run, or an orchestrator
grooming a unit inside one. The implementer reads the brief instead of the issue, so what is not in
here does not reach the work.

Measured on one project: a batch of briefs written to this shape, groomed in one short session
for a small fraction of the execution cost, produced merged PRs with **zero** mid-run
corrections. Briefs groomed without it needed three patch briefs mid-run, each one an extra
dispatch, and **none of the three was insight**. All three were project law the brief hadn't said.

That is the argument for grooming briefs *before* the run rather than inside it. It is also what
makes the cheaper cycle-2 orchestrator model viable: an orchestrator handed briefs of this shape
is dispatching, not deciding.

A brief that does not meet this shape is not ready to dispatch. **An implementer may report
`BLOCKED: brief incomplete — <what is missing>` and return** rather than guessing; that is cheaper
than the cycle a wrong guess costs.

---

## Shape

```markdown
# Brief — issue #<N>: <one line, the change, not the symptom>

Repo: <row name>
Worktree: `<abs path>` (create from `<base>` if absent; `<base>` is the objective's `Base branch:`, else the row's base branch)
Branch: `<type>/<N>-<slug>`
VERIFIED at: <remote>/<base> @ <full sha>, <YYYY-MM-DD>
After: <predecessor id> LANDED <oid>[, tag <tag>]   (omit when the unit has no predecessor)
ID range: <range>   (optional; the lane's pre-allocated identifiers, see `implementer.md`, "Sequential identifiers")
Issue: <url> (label `<label>`)
Epic: #<N or omit>

## Gate: <what must be true before this can start>

<What it consumes that does not exist yet, and what to do when it is missing: **stop and report
that** — never vendor, re-declare, or work around a missing dependency.>

Items tagged VERIFIED were read on `<remote>/<base>` at the stamp's SHA during grooming. Do not
re-derive them. Locate by symbol; line numbers drift.

The `VERIFIED at:` header line is the VERIFIED stamp: every VERIFIED fact in the brief carries
this ref and date. The ref is a full commit SHA of `<remote>/<base>`, not a branch name, so "the
base has moved since the stamp" is decidable. A brief with no stamp, or whose stamp is behind the
base, has its premise re-verified before dispatch.

The `After:` line names the predecessor unit this one waits on, the commit it landed as, and,
when the row tags releases, the verified tag, which the orchestrator copies in verbatim. For a
public row derived from a private unit it carries only the tag and the one line the private row
marks publishable, never anything else about the predecessor.

## The <sink | defect | call site> (VERIFIED, negative claim included)

<What is true today, with `file:line` anchors AND the evidence for the negative half — what you
grepped for and got zero hits on. A premise stated only positively reads as verified when only half
of it was checked.>

## What to do

<The change. Where a choice is genuinely open, say so, give the options, and give the rule that
decides between them plus what to record in the PR — "pick the smaller change and say why", "count
the callers first and put the count in the PR". A brief that hides an open choice gets it decided
silently by whoever is cheapest to ask, which is the implementer.>

<Anything explicitly NOT to do, with the reason it looks attractive: "**Do not add a generation
counter** — the cache type has no invalidate-all entry point, so nothing would ever increment it.">

## Trap: <each trap, one heading each>

<The thing that will mislead a competent agent: a doc comment that argues the change is unnecessary
(say so, and tell them to fix it), a registry that looks like it guarantees coverage here and does
not, a sibling unit that owns the part they will be tempted to fix.>

## Fix-when-touched

<The deferred findings on this unit's paths that the unit folds in, read with
`stu-env records fix-when-touched --repo <name>`: run each record's `match` command with the
unit's paths in place of `{paths}`, list what it prints, and name each finding in the brief. Each
is resolved with the record's `resolve` command (the finding in place of `{finding}`) once the
unit lands. If the section is empty, write **None** and say why. A fix-when-touched finding is
never a unit of its own.>

## Change nothing else

<The named files or modules in scope, then the exclusions by issue number: "do not touch the other
sinks (#N2–#N4), do not touch the config module (#N8's).">

## Verification bar

<The acceptance evidence, not a suggestion to test. Reuse the block below.>

## Changelog

<Either the section and the entry's budget, or **No entry**, why, and where the umbrella entry
lands instead — plus "say in your report you deliberately did not add one", so a missing entry is
distinguishable from a forgotten one.>

## Deliverables

1. Commits on `<branch>` (unless the row is before-push: then commit, get the review clean,
   push nothing, open no PR, and return the branch and SHA), pushed **once**, after every open review finding is handled
   locally and the review cycle is clean — all fixes batched into one push, never a push to
   see what CI says. The order is commit -> review clean -> push (once) -> CI -> PR. If the
   project installs a `pre-push` hook that enforces it (`implementer.md`, "Nothing is pushed
   until its review is clean"), it refuses a push with no finished review at the pushed SHA.
2. Unless the row is before-push, a PR against `<base branch>` (the objective's `Base branch:`, else the row's base branch; under `completion: integrated` only the FINAL unit targets the row's base branch) per the repo's PR template. `Fixes #<N>`. Explicit `--body`.
3. In the PR: <the decisions and counts this unit owes its siblings or reviewer>.
4. Report at `<run-dir>/reports/issue-<N>-report.md` — the run directory your brief lives in,
   i.e. the parent of its `briefs/` directory; return status, SHAs, PR number, mutation
   outputs, test counts.
5. On budget exhaustion: commit what is green, write `<run-dir>/handoffs/issue-<N>-handoff.md`
   with the `HEAD:` / `TREE: clean` stamp and the fixed fields (`implementer.md`
   "Run-length budget" — DONE, LEFT, READ THESE, VERIFIED, TRIED, COMMANDS, WRONG PREMISE,
   FIRST EDIT), return.

Short, plain comments and messages. Reuse existing helpers.
```

---

## Sizing a unit

Size a brief to finish in one or two implementer dispatches. Split before dispatch, not after
the second implementer stalls, when any of these hold:

- More than one independently deployable or independently verifiable part — each is its own unit.
- More than ~3 production files (matches `orchestrator-charter.md`'s model-selection row:
  "Implementation from a complete brief (1-3 files)").
- A visual/screenshot loop stacked on a logic change — split the two kinds of verification
  apart.
- More work than one implementer can finish under its **150k soft context band**
  (`scripts/turn-guard.py`, `AGENT_CTX_BANDS`): reading the files, the red test, the fix and
  the wrap-up all count against it. Estimate before dispatch; if the files to read plus the
  change would not fit, split it. A unit that hands off at the soft band is one dispatch too
  big, not one dispatch unlucky.
- A unit that already needed a third implementer dispatch — the brief is the problem
  (`orchestrator-charter.md`), so split it rather than dispatching a fourth.

Split by independently deployable or independently verifiable part — each half should be
verifiable on its own, without the other half's diff.

Under `/stu:run`, a split that creates new unit IDs goes through a `UNITS_CHANGED` line
(`SKILL.md` check 2) — see it there, not restated here.

---

## The verification bar

Copy it; drop only what genuinely does not apply, and say that it does not.

These hold in any language:

- Red before, green after. Counts in the report.
- **Mutation proof, mandatory:** name the specific mutation, confirm RED, restore, confirm GREEN,
  quote both, keep the mutation out of the commit. A test that cannot be made to fail proves
  nothing, and that is the most common defect in agent-written tests.
- **Fails first.**
  - Red on the unmodified base: the new test fails before the change, for the reason the brief
    names, and the failing output is quoted.
  - Never tune a threshold, a fixture or an expected value to manufacture the red.
  - Mutate the operand, the caller and the wiring, not only the line you changed: the layer you
    did not touch is where a test that passes both ways hides.
  - Commit before mutating, so the restore is exact.
  - Restore a mutated file with `git restore <file>`; never stash and never reset other work.
  - A control row (a case that must stay green or must come back positive) is asserted, and it
    comes back positive.
  - A brief that names a fixture names one that actually reaches the code under test.
- **Assert the surviving set, never a count or a reduction.** An over-narrow result presents as a
  smaller, plausible answer rather than an error — a filter that drops far too much reads as the
  feature working well.
- **Assert the decision you changed, not a downstream symptom** — another layer can make the
  symptom true anyway, and then the test passes either way. Ask: what *else* could make this
  assertion true?
- Where behavior has two halves (denied *and* still served), assert both. One half cannot tell a
  correct denial from a broken endpoint.
- No negative timing assertions — "did not run within 200ms" is equally true of work that has not
  been scheduled yet. Assert a synchronous upstream precondition instead.
- **Launch order is not execution order.** Asserting a downstream barrier catches a race only
  sometimes; we had one detection in nine runs. Confirm any fix by mutating the code and seeing
  the test fail over 3+ runs.

Run `stu-env section verification-commands --repo <name>` for the exact commands, and every way a run here
can look green while proving nothing: the CI lanes, their commands and path selectors (or the
guide that owns them), and which ones the change touches. If it is empty, take the commands
from `PROJECT_GUIDE`. Either way the brief pins down each of these, because each has cost a
cycle and the shape transfers even when the commands do not:

- The test command **with an explicit timeout**, or the harness kills the run with no output and
  a nonzero exit — indistinguishable from a failure. macOS ships no `timeout`, so a `timeout`
  prefix fails before the test runs; use the test runner's own flag.
- A typecheck that covers **test files** (many build commands do not), plus any codegen it
  depends on.
- The lint invocation in the **exact form that works** — some report clean when given an
  unexpected path form. Plant a deliberate violation once to confirm the run is live.
- The formatter check on changed files only. Never a blanket rewrite of the tree.
- **Whether the build tool lies** — exits 0 on a failed or zero-test run. Then: capture to a
  file, grep for the real result and confirm the test count, never trust the exit code, never
  pipe through `tail`.
- Any blocking CI lane that is easy to forget locally (an integration suite that only runs in CI).
- The test framework new tests should use, and any required file header.
- The integration suite and its command, or an explicit statement that none is required. A
  green PR is not evidence a path-filtered lane ran.

---

## Pre-flight — the checks that cost a cycle when skipped

Each row below is a real mid-run correction on one project, not a hypothetical.

| Check | The miss it prevents |
|---|---|
| Does this widen or change an **exported interface**? | Some build commands do not compile test code, so name every implementer to update, including test doubles in *other* modules. |
| Does a **sibling unit in this batch** touch the same file? | The changelog is the usual one. Assign the entry to exactly one unit, name the merge order, and tell the others to add none. |
| Is the spec in an issue **comment** rather than the body? | Quote it into the brief. An implementer reading the body alone silently implements the wrong scope. |
| Must this unit **run alone**? | Say so, and say what it contends with (a shared fixture, a port, a global lock). |
| Is there a **gate** — another PR that must merge first? | State it as a gate with a stop-and-report instruction, not as a note. |
| Does the change look **unnecessary** from some comment or doc in the tree? | Point at that text and tell them to fix it, or a reviewer will approve the code and leave the contradiction. |
| Is the premise's **negative half** checked? | Record what you grepped and got zero hits on, not just the positive anchors. |
| Does the tree already have a **helper for this**? | Name it. The default failure of a fresh agent is writing one that already exists. |
| Does this unit touch more than one independently deployable part, or more than ~3 files? | Split it before dispatch — see "Sizing a unit". |
| Is a **fix-when-touched** finding on this unit's paths? | Fold it into the brief's "Fix-when-touched" section. A fix-when-touched finding is never a unit of its own and never `UNITS_ADDED`. |
| Does a **sequential identifier** (a migration number, a fixture number) get allocated? | Name the row's `id-numbering` source, or give the lane's `ID range:` header line. Never leave it to be counted by eye. |
| Does **VERIFIED** carry a stamp? | Every VERIFIED fact carries the `VERIFIED at:` ref and date. A fact with no stamp is re-verified, not trusted. |

Then run `stu-env section brief-preflight-rows --repo <name>` and treat each row it prints as one
more row of the table above. Also run `stu-env records extra-gate-rows --repo <name>`: every
record whose `also:` list contains brief is a rule the brief must state, with the command that
proves it, so the implementer is not surprised by a gate row. These two channels are a union:
both apply, and neither overrides the other.

## When a brief is the wrong artifact

If the unit needs a decision only the owner can make — scope, which of two remedies, whether a
behavior change is acceptable — do not encode a guess as a brief. Park a question instead
(`handoff-format.md` § questions) with the measurement already settled and the remedy the only open
part. A guessed decision costs the implement/review/fix cycle beneath it; a parked question costs
one reply.

**Split by decision vs evidence, not by planning vs implementation.** A unit that needs a judgement
call is a parked question; a unit that needs only facts you can go and read is a brief you can
write now.
