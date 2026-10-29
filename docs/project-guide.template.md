# Project guide — what stu's agents expect your guide to answer

stu's agents route to your project instruction file (`CLAUDE.md` or `AGENTS.md`; `/stu:init`
records which as `guide:`, and `stu-env` derives it when blank). They assume that file, or the
guides it links to, answers the questions below. If yours already does, ignore this file. If
not, copy the sections you are missing into it and fill them.

This is separate from the stu config that `/stu:init` writes. The config answers questions
about how stu runs in this repo (merge mode, review evidence, reviewer invariants,
verification commands, and so on). The project guide holds the rules every agent and every
human contributor follows anyway. Where a config section is left empty, stu falls back to
what the guide says, so a guide that covers these sections lets you leave most of the config
blank.

Everything here is here because **violating it fails silently**: green tests, no error, a
wrong result nobody is told about. Rules that fail loudly do not need to be written down for
an agent; the tooling tells it.

---

## Non-negotiables

<!-- The rules whose violation produces no error. Group them. Examples of the shape:

**Boundaries.**
- Every file write goes through the atomic-write helper, never a direct open-and-write. A
  crash mid-write leaves a truncated file that the next run reads as valid.
- Never accept an identifier from input without validating it where it is used, even where
  an earlier layer should catch it.
- A step that is skipped when its input is empty must say so. A silent no-op looks exactly
  like success, and an empty test fixture cannot show you.

**Safety nets.** A guard that always passes is indistinguishable from one that never
catches anything.
- Never weaken a guard to make its own regression suite pass. A red suite against `main`
  is a finding about the guard.
- Never relax an assertion to make a flaky test pass. Find what makes it flaky.
- Never pin a dependency's version inside a test alone. A suite that tests a different
  version stops testing the one you ship.
- Never hand-edit a derived baseline. Regenerate it.

**Other agents' work.** (if several sessions share the machine)
- Never clear the shared build cache; use <the cleanup target>.
- The main checkout is read-only while agents are running. Work in a worktree, address
  it with `git -C <absolute path>`, and never `git add -A`.
- Never reset, discard, stash, amend, or force-push work you did not create.
-->

## Delivery

<!-- Branches, commits, PRs, the review cycle, and merge authority. stu's merge gate assumes:
- squash merges (so the PR TITLE becomes the commit subject; a stale title lands wrong);
- branch protection requires the status checks, so a direct `gh pr merge
  --match-head-commit` is legal once they are green;
- whether merging a green, gated PR is standing authorisation or needs a human. State
  which. stu defaults to "standing authorisation, through the gate"; see
  docs/design-rationale.md for why. To require a human, set `merge-mode` to report-only in
  the stu config.
- the review cycle: nothing is pushed until its review is clean; review fixes go on the
  same branch, never a follow-up PR.
-->

## When to file an issue

stu's default is: do **not** file an issue for something you noticed while doing something
else. Write it as a new file under `<run home>/ledger-inbox/`; only the operator promotes a
ledger entry.

The one exception is a three-part test, and all three must hold:

1. It is a defect — not an improvement, a metric, or a future cleanup.
2. It is user-reachable, **or** it corrupts data, **or** it is a broken safety net.
3. It exists on `main` today, verified against code — not inferred from a comment, a
   closed issue, or an agent's report.

<!-- The repo, labels, and any project board conventions. -->

## Sequential identifiers

<!-- Optional: the numbering rule for anything this project numbers in order (a migration, a
     fixture, a changelog entry): where the next number comes from and who may allocate it. An
     implementer follows this when the stu config's `id-numbering` section has no source for
     the kind. -->

## Verification commands

<!-- The exact commands an implementer runs before claiming done, and the artifacts that
     carry the counts (a results file, a JUnit XML report). Name every way a run can look
     green without testing anything, such as a path-filtered CI check.
     The stu config's `verification-commands` section can hold these instead. -->

## Test suite traps

<!-- Every way a suite here can look green while proving nothing. Examples: piping through
     `tail` masks the exit code; a later run overwrites earlier results;
     a killed test runner truncates its output. -->

## Product taste

<!-- Optional: the tiebreaker when two implementations are both correct. For shape: "ship
     the one that leaves the user less to look at and less to decide." The stu config's
     `product-taste` section can point here. -->
