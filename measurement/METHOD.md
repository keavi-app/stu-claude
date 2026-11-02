# Pre-registered method: measuring the engineering work delivered with stu

Pre-registration for a measurement study of the agent orchestration tool stu
(https://stu.keavi.app, repository keavi-app/stu-claude). Written 2026-10-31, re-scoped
2026-11-01 from a full census to a stratified random sample (section 19) and on 2026-11-02 from
an engineer-hours estimate to a value-tier judgment (section 20), extended on 2026-11-02 by one
kind-matched October comparison of run and non-run PRs (section 20.1), and committed before any
population pull request was scored. Every analysis choice that can affect a
published number is fixed here. Any later change is recorded, with its reason and date, in
`DEVIATIONS.md` published next to this file; nothing is changed silently.

The measured repository is private. Its owner can be identified from the site and repository
named above; the product it builds is not named or described here. This document describes the
repository only in generic terms: no product names, features, paths, file patterns, titles, or diffs appear here or in
any published artifact. Where a rule depends on the repository's paths, the rule is stated in
prose and the exact code is committed by its sha256 hash (section 11). The hashed files are
private because they contain the repository's paths; they can be disclosed to an independent
reviewer on request, who can check them against these hashes.

Design document of this study: sha256
`a21bbab3ded6e49ed6bacc356555e0c14437260125486573b5b241b362321843` (design.md, private).
All file hashes are listed in `hashes.txt` beside this file.

## 1. Purpose and non-goals

Purpose: measure how much engineering value one private product repository received per
dollar of agent spend, before and after its owner began using stu runs (`/stu:run`), by judging
what each merged pull request (PR) accomplishes rather than by counting lines or PRs.

Value per PR is a model judgment on a six-step, non-linear tier scale (0, 1, 2, 3, 5, 8; the
prompt is in section 10.1), made from the prepared diff and the stripped title only. The rubric
is adapted from the one used by a usage report on a second codebase, not the measured one, so
that the two studies compare row for row. It judges the substance of a change for the system
(new capability, hardening, valuable deletion), not its size.

Non-goals and anti-goals:

- Not user value or business value. Not a measure of individual developers.
- Not an estimate of time: the study does not estimate engineer-hours.
- Not a controlled experiment: the model generation changed (5.0 to 5.5) in the same weeks as
  the change in way of working. The before/after comparison cannot fully separate stu from the
  models, and the report says so beside the number.
- Not a causal comparison of stu runs with other ways of working inside the same months. One
  claim compares October run PRs with October non-run ("other") PRs of matched kinds (the
  kind-matched run vs. non-run claim, sections 5 and 14). It is not a counterfactual for the run
  work: almost all large features ran in stu runs in October, and the October "other" PRs are
  self-selected leftover work, opened partly from settle sessions and other orchestration
  rather than only from plain sessions (section 15). Matching is by kind only; size and
  difficulty are not matched. The run-versus-other token decomposition of
  section 14 is descriptive and carries no claim.
- Whatever the numbers show is published, including flat or negative results.

There is no human calibration of the tiers (section 17).

## 2. Population and exclusions

Population: every PR merged into the measured repository whose merge time falls on an
America/New_York local day from 2026-07-01 to 2026-10-31, as returned by the GitHub search API
at the fixed fetch time **2026-11-01T21:26:28Z** (after the last population day had ended in
New York).

- The fetch runs one query per calendar week window, because one month exceeds the
  1,000-result search cap. Each window's bounds are New York local midnight and 23:59:59 with
  their UTC offset, so the windows tile the New York days exactly at both ends; contiguous,
  non-overlapping, at most 7 days. Any window returning 1,000 or more results aborts the fetch.
  Each month's count (by New York merge day) was checked against the live search total at fetch
  time; all four matched. No fetched PR falls outside the New York window.
- PRs merged into a non-default base branch (epic branches) are included: 42 PRs.
- Merged PR counts by New York month: July 608, August 594, September 665, October 1,090;
  total 2,957.

Exclusions, each counted and published:

| Reason | Count |
| --- | ---: |
| Roll-up PR that carries an epic branch into the default branch (no new work) | 1 |
| Bot or dependency PR (bot author) | 0 |
| No attributable agent session (section 3) | 46 |
| **Scored population (sampling frame before the period filter)** | **2,910** |

The 46 unattributable PRs by period: before 18, transition 0, September 12, October 16. The
unattributable share is below 2 percent in every period (threshold for stopping: 5 percent).

Day and week: every date is the America/New_York local day of the merge time. Weeks are ISO
weeks starting Monday.

## 3. Attribution: which session opened each PR

Attribution decides which PRs are attributable (the exclusion above), which PRs were opened
by Codex (section 14, tokens per value unit), and the two groups of the kind-matched claim:
**run** (a PR whose opening root is a stu run root, below) and **other** (any attributable
Claude PR whose opening root is not a run root). "Other" is not only hand-driven work: it
includes roots in settle mode, roots where the model itself invoked a run, settle or
fix-campaign skill without a typed run command, and roots that dispatched orchestration
subagents under earlier or ad-hoc orchestration (composition in section 15). Codex PRs belong
to neither group.

Source: a local agent session archive that indexes every Claude Code and Codex session on the
owner's development machine (sessions, parent links, messages, tool calls and tool results).
It is the primary source for every period.

- **Opening session:** a session whose shell tool call ran a PR-create command and whose tool
  result contains the PR's URL. Tool results are read from both places the archive stores
  them (in later months only the per-event result store holds them). Fallbacks, in order, when
  no tool result exists: the archive's PR-link field of a session that also ran a PR-create
  command; then a Claude Code session link in the PR body, matched to the session whose tool
  input wrote that link. Sources used: tool result 2,902 PRs, body link 8, PR-link field 0.
- **Scope:** a session belongs to the measured repository if its working directory, or its root
  session's working directory, is the repository checkout or one of its worktrees. Scratch
  directories, and sessions working in this study's own directories or its earlier baseline
  measurement's, are out of scope by this rule. In addition, an in-scope root session tree
  whose user messages or tool calls reference this study's or the baseline's directory, and
  that opened no PR, is a **measurement tree** and is excluded from all spend (section 6); a
  tree that opened a PR is never excluded.
- **Root session:** subagent sessions roll up to their root through the parent links (at most
  20 levels, cycle-safe).
- **Codex PR:** a PR whose opening session is a Codex session and whose opening root is not a
  stu run root (a root session with a user message invoking the run command). Codex PRs are in
  the population and may be sampled.

Attributable PRs by period and opening agent:

| Period | Claude | Codex | none | total |
| --- | ---: | ---: | ---: | ---: |
| Before | 942 | 1 | 18 | 961 |
| Transition | 236 | 5 | 0 | 241 |
| September | 646 | 7 | 12 | 665 |
| October | 1,073 | 0 | 16 | 1,089 |

The Before period has no stu runs by construction, and the pipeline fails if any Before PR is
opened under a run root.

## 4. Periods

| Period | Merge days (America/New_York) | Role | Sampling frame |
| --- | --- | --- | ---: |
| Before | 2026-07-01 to 2026-08-21 | baseline | 943 |
| Transition | 2026-08-22 to 2026-08-31 | excluded from every comparison, never sampled | n/a |
| September | 2026-09-01 to 2026-09-30 | after, reported separately | 653 |
| October | 2026-10-01 to 2026-10-31 | after, reported separately | 1,073 |

The earlier private name of the run command first appears in messages on 2026-08-22; the first
run invocation is on 2026-09-02. September and October are always reported separately, never
pooled. The sampling frame of a period is its scored-population PRs (not excluded, attributable,
with prepared inputs); the four frames sum to the 2,910 scored PRs (Transition 241).

## 5. What is compared

- **Headline, before vs. after:** all work in each period, every attributable PR, every agent:
  value units per merged PR, cost per value unit, and tokens per value unit (section 14).
  Before against September, and Before against October, each reported on its own.
- **Quality:** revert and fix-up shares per period, computed by script over every scored PR
  (section 13).
- **Free weekly metrics:** spend per merged PR and Claude tokens per merged PR, per ISO week
  and per period, computed by script from the session archive and the PR list (section 14).
- **Secondary scripted metrics:** the context-hygiene, model-family, session-mode,
  right-censoring and token-decomposition metrics of a usage report on a second codebase, not
  the measured one, computed here by script with that report's definitions, per period and per
  ISO week (section 14). They are pre-registered secondary results: descriptive, with no
  interval and no test.
- **Kind-matched run vs. non-run PRs, October:** cost per value unit of October run PRs
  against October other PRs (section 3), the two groups matched by kind (sections 14 and 15),
  with value units per PR and cost per PR by group. This claim is not a counterfactual for the
  run work: almost all large features ran in stu runs in October, "other" in October is
  self-selected leftover work, and matching is by kind only; size and difficulty are not
  matched. A separate blinding check tests whether the scorer can tell the two groups apart
  (section 12).
- **Runaway-session measures (secondary, scripted):** the share of main sessions whose own
  context passed 300K and 800K tokens, by period and session mode, and the share of Claude
  spend on turns above 300K tokens, by period and cost bucket (section 14). Descriptive, with no
  interval and no test.
- **What was seen before registration.** For the kind-matched claim, the cost side was
  inspected before it was registered: mean and median per-PR cost by period, group and kind
  (that look motivated the claim). The value side is unseen: no population PR has a tier. The
  runaway-session measures were computed and inspected before registration. The within-kind
  threshold (at least 15 PRs per group) and the exclusion of the 56 October other PRs opened
  from run setup sessions (section 15) were fixed after seeing those counts.
- Nothing else is a pre-registered claim.

## 6. Cost method

All spend figures are **list-price estimates at API rates**, not an invoice.

- **Source:** per-message token usage in the session archive, for every in-scope session with
  messages dated (America/New_York day) 2026-07-01..2026-10-31.
- **Prices:** per-day list prices. Each message is priced at the list price in force on its UTC
  day, from the archive's dated model price history (two Codex model families had list-price
  cuts inside the window); the current price table otherwise.
- **Token accounting:** input, output, cache read, and cache write tokens; cache writes split
  into 5-minute and 1-hour writes from the usage record, any unsplit remainder priced at the
  1-hour rate. Streamed duplicates of one Claude request are deduplicated by request id
  (fallback: message id), keeping the snapshot with the largest output count, located at its
  earliest occurrence. Models with no list price (a negligible share of usage) are priced at zero.
- **Reconciliation:** over all sessions, computed cost matches the archive's own daily usage
  report per agent per month within 0.5 percent (Claude within 0.04 percent).
- **Tokens:** Claude tokens processed = input + cache write + cache read + output, Claude models
  only (tokenizers differ). The share of spend on non-Claude models is stated per period.
- **Period spend:** all in-scope spend (section 3) dated in the period: every session, including
  automated review sessions and non-Claude models, excluding only the measurement trees of
  section 3. Spend is never divided among PRs; no
  published number depends on which session opened which PR beyond section 3.

## 7. Scorer inputs

The scorer sees only the prepared diff and the stripped title. It never sees the description,
dates, author, branch, session, labels, PR number, or commit message bodies.

- **Diff:** the first-parent diff of the PR's merge commit (squash merges); for an epic-branch
  PR whose merge commit is unavailable, the PR head against its merge base. Blob `index` lines
  are removed.
- **Generated and vendored files** are replaced by one line naming the file, its category, and
  its changed-line count. Categories: generated query code, mocks, lockfiles, snapshots, API
  specs, vendored code, binary files. The file rules that assign them are committed by hash
  (section 11).
- **Scrubbing** of diff and title: calendar dates and year-month strings become `<date>` and
  `<month>`; issue and PR references become `<n>` forms; the PR's own head branch name and every
  epic branch name become `<branch>`. Bare numbers are kept.
- **Title:** issue and PR numbers, commit SHAs (7 to 40 hex characters containing a digit),
  dates, and run vocabulary are removed. Run vocabulary: `stu`, the run command and the earlier
  private name of the same command, orchestrator, implementer, merge gate, supervisor, campaign,
  objective, settle, unit, and "run" followed by a number or slug. Diff content is not scrubbed
  of run vocabulary (code is the work); the blinding check (section 12) is the net for content
  cues.
- **File names:** each input file is named by an opaque key, a salted hash of the PR number
  (salt private), re-derived until it contains none of the PR number's digits as a substring.
  No input file name or body contains the PR number, branch, or a merge date.
- **Mechanical PRs:** a PR whose every file is generated or vendored is still scored. Its input
  holds only the one-line notes, and the prompt makes such a change tier 0 (`noise`). The second
  report's prefilter, which gives such PRs tier 0 without a model call, is not adopted: the
  generated-file handling above already removes their content, and only 1 of the 2,910 scored
  PRs consists solely of generated files; it is not among the 520 PRs scored (the 360-PR sample
  and the kind-matched PRs).
- **Test files** (for the blinding baseline): files in test directories or with test-file
  naming conventions.

Input format, exactly (every value scorer):

```
TITLE: <stripped title>
PART: <k> of <n>          (only when chunked)
--- DIFF START ---
<prepared diff>
--- DIFF END ---
```

Inputs are prepared for every PR of the scored population (2,910), so that the blinding
baseline (section 12) and any later registration can use them; only sampled PRs are scored.

## 8. Token limit and chunking

- Token estimate: characters / 4.
- Limit: **30,000** estimated tokens per input. A larger diff is split at file boundaries into
  consecutive parts; a single file over the limit is split at hunk boundaries with its file
  header repeated (a single oversized hunk at line boundaries). Each part is scored separately,
  as if it were the whole change (section 10.1).
- **Value of a chunked PR:** tiers are not additive, so parts are never summed. A chunked PR's
  tier is the highest tier given to any of its parts; its category and effort type are those of
  that part, ties going to the earliest part. The rule can understate a chunked PR's value (no
  part shows the whole change), and it can also overstate it: the maximum over several noisy
  part scores tends to rise with the number of parts. Chunked PRs are more common in the Before
  sample (14 of 120) than in September (11) or October (5). If the net effect understates
  Before, it favours the after/before indices; if it overstates Before, it works against them.
  The sensitivity result without chunked PRs (section 14) is the check.
- Chunked PRs are eligible for the sample like any other PR.
- Chunked PRs: 201 of the 2,910 scored PRs (largest: 52 parts). In the sample: Before 14 of
  120, September 11 of 120, October 5 of 120. Scored inputs (parts) of the sample: Before 152,
  September 133, October 135 (420).

## 9. Scorers and model IDs

| Instrument | Name | Scorer | Model ID | Items |
| --- | --- | --- | --- | --- |
| Sample value | `value_sonnet` | Claude Code subagent | `claude-sonnet-5-5` | every part of the 360 sampled PRs and the 178 kind-matched PRs, each PR once (520 PRs, 615) |
| Second-instrument value | `value_codex` | Codex CLI | `gpt-6.1-sol` | the same 520 PRs (615) |
| Opus value | `value_opus` | Claude Code subagent | `claude-opus-5-5` | every part of the 60 Opus-subset PRs |
| Test-retest value | `value_retest` | Claude Code subagent | `claude-sonnet-5-5` | 30 retest PRs, file order shuffled |
| Blinding guesser, periods | `guess_sonnet` | Claude Code subagent | `claude-sonnet-5-5` | 5 tasks of 10 targets |
| Blinding guesser, run vs. other | `guess_runother_sonnet` | Claude Code subagent | `claude-sonnet-5-5` | 3 tasks of 10 targets |

**Claude Code subagents.** Scoring runs only inside interactive Claude Code sessions on a
subscription plan; no non-interactive or API calls. The session's working directory is a
neutral scoring workspace, so no project instructions of the measured repository load. Two
subagent definitions (model `sonnet` or `opus`, tools Read and Write only) instruct the scorer
to read only the batch file, the prompt file it names, and the listed input files; to score each
item independently of the others; and to write each answer as bare JSON to its output path.
The dispatch text is exactly:

```
Score batch {{BATCH_ID}}. The batch file is {{BATCH_PATH}}. Follow your instructions exactly and, when every output is written, reply only: done {{BATCH_ID}}
```

- Batches hold 10 items (a guess task is one item per subagent). Items are shuffled within and
  across batches with seed label `batch:<instrument>`, so periods are mixed. The position in the
  batch is recorded.
- An output is accepted only if it parses and has exactly four keys: `justification` (a
  non-empty string), `category` (one of the seven categories), `effort_type` (one of the four
  effort types) and `tier` (an integer, one of 0, 1, 2, 3, 5, 8). Rejected outputs return the
  item to pending; an abandoned reservation is released after 2 hours.
- Model IDs are not taken from self-report: each batch's subagent session is found in the
  session archive by its batch id and its recorded model is stored. Any batch scored by another
  model is rescored.
- The test-retest inputs are regenerated with the files of each diff shuffled (seed label
  `retest`) and re-chunked, and are scored in a different session from the batches that scored
  the same PRs for the sample value instrument.

**Codex.** One call per item, sequential, 600-second timeout, launched from the study directory with
`-C` pointing the model at an empty directory, and with the prompt file, a blank line, then the
input file on standard input. Codex runs on a separate plan from the Claude scorers. The exact
command:

```
codex exec -m gpt-6.1-sol -s read-only -C scoring/codex-cwd --skip-git-repo-check --ephemeral --ignore-rules --output-schema scoring/schema/value.json -o scoring/codex-tmp/<item>.json --disable memories --disable hooks -c model_reasoning_effort=high -
```

The output schema (`value.json`, committed by hash) is the strict form of the four keys above.
Stored memories and user hooks are disabled because they can carry context the scorer must not
have. The reasoning effort is pinned to high by the `-c model_reasoning_effort=high` override,
so a later change to the local Codex configuration cannot alter the scorer. The model and
reasoning effort reported in each call's header are recorded and checked (pilot: model
`gpt-6.1-sol`, reasoning effort high).

Codex failures. A call that times out (its process group is killed at 600 seconds), that writes
no answer (a refusal outside the schema included), or whose answer does not parse or validate
(the answer is moved aside with its errors) leaves the item pending; every attempt is logged.
Each later run of the runner retries pending items, until an item has 3 failed attempts in the
log; it is then not tried again and is missing for the Codex scorer. A PR with any part missing
is left out of every Codex-based statistic, and the number of such PRs is published. The
Claude subagent instruments have no retry limit: a rejected or abandoned item returns to
pending (above) until it is answered.

**Pilot.** Before pre-registration, 10 PRs merged in June 2026 (outside the population, seed
label `pilot`) were scored by the Sonnet, Opus and Codex scorers with the earlier engineer-hours
prompt (section 20). The pilot tested the scoring harness, which the value instruments use
unchanged apart from the prompt, the answer schema and its validation: all outputs validated,
every subagent batch was found with the expected model ID, and no justification mentioned a PR
number, date, or author. Pilot outputs are never analyzed.

## 10. The prompts, verbatim

### 10.1 Value prompt (`prompts/value.txt`)

The prompt is adapted from the value rubric of a usage report on a second codebase, not the
measured one: the same tiers, anchors, categories, effort types and scoring rules. The
adaptation removes the rubric's references to a PR description and a linked issue (the scorer
here sees neither), describes the blind input and its placeholders, adds the chunked-input rule
of section 8, and asks for the one-sentence justification first, before the tier. Every value
scorer (Sonnet, Codex, Opus, retest) uses this prompt.

````
You are scoring the engineering value of one change to a software codebase.

The input file you are given contains:
- A line starting with "TITLE:" holding a short title for the change.
- Sometimes a line of the form "PART: k of n" (see below).
- The change itself as a unified diff, between the lines "--- DIFF START ---" and "--- DIFF END ---".

Some identifiers in the input have been replaced with placeholders such as <date>, <month>, <n> and <branch>. Generated and vendored files are not shown in full: each is replaced by a single note giving the file, its category and the size of its change. Such files are produced by a tool, so their contents carry no engineering judgment of their own.

Score the substance of what the change accomplishes for the system, not the number of lines or files changed. Judge only from the title and the diff in the input.

Category: pick exactly one.
- "feature": a new user- or system-facing capability that did not exist.
- "hardening": makes an error-prone or fragile system solid: tests, race or edge-case fixes, validation, reliability.
- "refactor": restructuring or simplification, including valuable deletion of dead or unneeded code.
- "bugfix": corrects incorrect behavior.
- "infra": build, continuous integration, tooling, deploy or release plumbing.
- "docs": documentation or process.
- "noise": mechanical, generated, vendored, data-only, pure formatting or bulk rename; no engineering judgment.

Effort type: pick the dominant nature of the change, exactly one of "new_code", "hardening", "deletion", "refactor". Deletion is first-class: removing a large amount of unnecessary code is valuable and is scored on its effect on the system, not on what it adds.

Value tier: the scale is not linear; pick the closest anchor, exactly one of 0, 1, 2, 3, 5, 8.
- 0, noise: mechanical, generated or data-sync; no engineering judgment.
- 1, trivial: a configuration tweak, a one-line change, a copy change.
- 2, minor: a small localized fix or helper.
- 3, substantial: a real feature increment, a fix with tests, a useful refactor.
- 5, major: a new capability, a complex or error-prone system made solid, a significant justified deletion, an architecture-level change.
- 8, exceptional: a large novel feature, taming a critical subsystem, a major risk reduction.

Rules:
- Judge value, not volume. A large diff can be tier 0 (generated); a small diff can be tier 5 (a subtle critical fix).
- Credit deletions and hardening fully.
- If the change is mechanical, generated or data-only, it is tier 0 and category "noise", regardless of size.
- The justification is one sentence and must cite concrete evidence from the diff (a file, function or behavior), not generic praise.

If the input has a "PART: k of n" line, the change was too large to show at once and has been split at file boundaries into n parts; you are seeing part k. Score only the part shown, as if it were the whole change, and do not guess at the parts you cannot see. Each part is scored separately.

Answer in this order:
- "justification": first, one sentence citing concrete evidence from the diff. Write it before you settle on a tier.
- "category": one of the category names above.
- "effort_type": one of the effort types above.
- "tier": one of the integers 0, 1, 2, 3, 5, 8.

Base the answer only on the input you are given. Respond with a single JSON object and nothing else: no text before or after it, no code fences, no comments, no extra keys. Its exact shape is:

{"justification": "<one sentence>", "category": "<category>", "effort_type": "<effort type>", "tier": <tier>}
````

### 10.2 Blinding guess prompt (`prompts/guess.txt`)

`{{EXAMPLES}}` and `{{TARGETS}}` are filled by the pipeline as described in section 12.

````
You are shown changes to one software codebase. Every change belongs to exactly one of three classes, labeled A, B and C. You are not told what the classes mean.

First come labeled examples: 20 changes from each class, 60 in all, in mixed order. Then come 10 unlabeled target changes. For each target, guess which class it belongs to, using anything in the examples and the target that helps.

Each change is shown as an input of this form: a line starting with "TITLE:" holding a short title, sometimes a line "PART: k of n" meaning only part k of a change split into n parts is shown, then a unified diff between the lines "--- DIFF START ---" and "--- DIFF END ---". Some identifiers have been replaced with placeholders such as <date>, <month>, <n> and <branch>. Generated files are replaced by a one-line note. Every input has been cut to about 2,000 tokens; a cut input ends with the line "[input truncated]".

Each labeled example appears as:

=== EXAMPLE CLASS: <A, B or C> ===
<input>
=== END EXAMPLE ===

Each target appears as:

=== TARGET <position> OF 10 ===
<input>
=== END TARGET ===

LABELED EXAMPLES

{{EXAMPLES}}

TARGETS

{{TARGETS}}

Respond with a single JSON array and nothing else: no text before or after it, no comments. The array has exactly one object per target, in target order (the object for TARGET 1 first, TARGET 10 last), and each object has exactly these keys:

{"guess": "<A, B or C>", "reason": "<one sentence naming the cue you used>"}

"guess" must be exactly one of "A", "B" or "C". Give a guess for every target even when unsure.
````

### 10.3 Run vs. other guess prompt (`prompts/guess_runother.txt`)

The period guess prompt with two classes instead of three; filled the same way (section 12).

````
You are shown changes to one software codebase. Every change belongs to exactly one of two classes, labeled A and B. You are not told what the classes mean.

First come labeled examples: 20 changes from each class, 40 in all, in mixed order. Then come 10 unlabeled target changes. For each target, guess which class it belongs to, using anything in the examples and the target that helps.

Each change is shown as an input of this form: a line starting with "TITLE:" holding a short title, sometimes a line "PART: k of n" meaning only part k of a change split into n parts is shown, then a unified diff between the lines "--- DIFF START ---" and "--- DIFF END ---". Some identifiers have been replaced with placeholders such as <date>, <month>, <n> and <branch>. Generated files are replaced by a one-line note. Every input has been cut to about 2,000 tokens; a cut input ends with the line "[input truncated]".

Each labeled example appears as:

=== EXAMPLE CLASS: <A or B> ===
<input>
=== END EXAMPLE ===

Each target appears as:

=== TARGET <position> OF 10 ===
<input>
=== END TARGET ===

LABELED EXAMPLES

{{EXAMPLES}}

TARGETS

{{TARGETS}}

Respond with a single JSON array and nothing else: no text before or after it, no comments. The array has exactly one object per target, in target order (the object for TARGET 1 first, TARGET 10 last), and each object has exactly these keys:

{"guess": "<A or B>", "reason": "<one sentence naming the cue you used>"}

"guess" must be exactly one of "A" or "B". Give a guess for every target even when unsure.
````

## 11. Task-type strata

Every PR gets one platform and one kind. They describe the sample in the published table and
feed the blinding baseline; the kind also stratifies the kind-matched claim (sections 14 and
15). No other claim is stratified by them. The rules are code committed by
hash before scoring:

- strata rules: sha256 `981597dee49410d2f4498523da661faa6546de09c2931a66799386aadbef5316`
- generated-file rules: sha256 `b6ec0851ac3fe10246616883471ef5ab7eb4d02d65f18ba5026eb2cc89006e37`

**Platform** (server, mobile-a, mobile-b, web-site, docs-design, infra-tooling; mobile-a and
mobile-b are the two mobile client apps). Each changed file maps to a platform by its location:
the server code and server test directories map to server, except the repository's test-script
and mobile end-to-end directories and some tooling directories, which map to infra-tooling; each mobile app's directory maps to its mobile platform; the web and
site directories map to web-site; the documentation and specification directories, and markdown
files at the repository root, map to docs-design; the server's dependency files map to server; everything else maps to infra-tooling. The PR's platform is the one with the
most changed lines (added plus deleted) in non-generated files. If every file is generated, all
files count; if no file has a line count (binary only), each file counts 1; ties go to the first
of server, mobile-a, mobile-b, web-site, infra-tooling, docs-design.

**Kind** (feature, fix, refactor-test, design-docs), decided by the first rule that applies:

1. Branch prefix (text before the first `/`): `feat` and `feature` -> feature; `fix` -> fix;
   `refactor`, `test`, `perf`, `chore`, `ci`, `config` -> refactor-test; `docs`, `design` ->
   design-docs.
2. A further set of operational branch prefixes (not applied to Codex-named branches): `revert`
   -> fix; prefixes for CI machines, infrastructure, tooling, lint and guard checks -> refactor-test.
3. The conventional-commit prefix of the title (`type(scope)!:`), with the map of rule 1 plus
   bugfix, hotfix, revert -> fix; doc -> design-docs; tests, build, style, infra, tooling, lint,
   guards -> refactor-test.
4. For a branch with no `/`: its first hyphen- or underscore-separated token, under the map of
   rule 1.
5. A title starting with fix, fixes, or fixed -> fix.
6. Otherwise feature (the number of PRs falling to this default is published).

Labels are accepted by the rule but carry no information (nearly every PR has the same single
label). Strata over all 2,957 PRs: platform server 1,373, mobile-a 445, mobile-b 498,
infra-tooling 368, docs-design 267, web-site 6; kind fix 1,459, feature 1,036, design-docs 289,
refactor-test 173. No PR is unclassified.

## 12. Blinding checks

The concern is the scorer inferring a PR's period, or its group in the kind-matched claim, from
anything other than the work itself. Real differences in the work (bigger PRs, more tests) are
not leaks. Two checks, each comparing two guessers on held-out PRs:

- **Period check:** 50 held-out sampled PRs (Before 17, September 17, October 16); classes: the
  three periods; LLM guesser `guess_sonnet` with the prompt of section 10.2.
- **Run vs. other check:** 30 held-out PRs of the October kind-matched sample (15 run, 15
  other); classes: run and other; LLM guesser `guess_runother_sonnet` with the prompt of section
  10.3.

1. **Content-only baseline:** multinomial (softmax) logistic regression with weights and
   intercepts initialised to zero, fitted by 2,000 full-batch gradient-descent iterations at
   learning rate 0.1 on the weighted mean cross-entropy plus an L2 penalty of 1.0 (half of 1.0
   times the sum of squared weights; intercepts not penalised). Features, z-scored with the
   training set's mean and population standard deviation (a constant feature is divided by 1):
   log of 1 plus the changed lines in non-generated files, files touched, the test share of
   changed lines (0 when there are none), and platform (one-hot, six platforms). The predicted
   class is the highest-scoring one, ties to the earlier class. Period check: trained, with
   equal weights, on every sampling-frame PR of the three periods not in its holdout or
   examples (2,559 PRs). Run vs. other check: trained on every October run or other PR (not
   excluded, with prepared inputs) not in its holdout or examples (1,003 PRs: run 893, other
   110), with class-balanced weights (each class's weights sum to the same total), because run
   PRs outnumber other PRs about eight to one. The code is written and tested before
   registration and committed by hash (`hashes.txt`).
2. **LLM guesser:** `claude-sonnet-5-5` (the sample value scorer), tasks of 10 holdout targets,
   each task with all the labeled examples, reshuffled per task: for the period check 5 tasks
   with 60 examples (20 per period, from the period sample, disjoint from the holdout); for the
   run vs. other check 3 tasks with 40 examples (20 run, 20 other, October PRs of each group
   outside the kind-matched sample). Each change is its first (or only) input, cut at a line
   boundary to 2,000 estimated tokens. Classes are shown only as letters; the class-to-letter
   mapping is drawn with seed label `batch:<guesser instrument>` and kept private until results
   are published. An answer is accepted only if it holds exactly one guess per target.

**Decision**, per check. Gap = LLM accuracy minus baseline accuracy on the holdout. p = share of
10,000 paired bootstrap resamples of the targets (seed labels `bootstrap:blind_period` and
`bootstrap:blind_runother`) in which the gap is at most 0.05. **Leak** if the observed gap
exceeds 0.05 and p < 0.05. With 50 or 30 targets a check can detect only a large leak; the
report says so beside the result.

**Order.** Both checks run before any value scoring of the population: the guessers are scored
and both decisions made first. If a check finds a leak: read the guesser's stated cues, strip the
cue in input preparation, regenerate the inputs, rerun that check, and record the change in
`DEVIATIONS.md`; value scoring starts only when neither check finds a leak. If a cue cannot be
removed after two attempts: value scoring proceeds, the gap is published, and the scores of the
PRs the guesser classified correctly and incorrectly are compared within each period (period
check) or within each group (run vs. other check).

**Limitations.** The guesser sees each change cut to 2,000 estimated tokens, while the value
scorer sees inputs of up to 30,000 estimated tokens per part, so a cue that appears only later in
a large diff can reach the scorer without reaching the guesser. In the run vs. other check the
"other" examples come from the October other PRs outside the kind-matched sample, which are
exactly the 56 PRs opened from run setup sessions (section 15), so they may resemble the other
targets less than run examples resemble run targets.

## 13. Fix-ups, reverts, and the freeze

Quality is computed by script over every scored PR of each period, not only the sample, and
costs no scoring.

- **Revert:** a later commit on the same base whose message contains "This reverts commit
  <sha>" with the target's merge commit, or whose title starts with `Revert "` and quotes the
  target's title or PR number.
- **Fix-up:** a PR merged within 14 days after the target whose deleted or modified lines (old
  side of its hunks), blamed in the candidate's parent commit, trace to the target's merge
  commit, with blamed lines divided by the target's added lines (generated files excluded) at
  least 0.5. A candidate matching several targets fixes the one with the highest overlap.
  Targets with zero added lines cannot be fixed up: they are excluded from the fix-up
  denominator and counted. Epic-branch PRs are blamed on the epic base when it exists, else on
  the PR head lineage; undeterminable cases are counted and published.
- **Value:** value is not adjusted for fix-ups in the main result (a deduction would need tiers
  for fix-up PRs outside the sample). Sensitivity (section 14): sampled PRs that are fix-ups
  count zero value units.
- **Freeze:** quality data is frozen on **2026-11-14**, so October PRs get their full 14 days.
  PRs merged 2026-11-01..2026-11-14 are fix-up and revert candidates only, never population.
  The final pass runs on or after 2026-11-15. Every number computed before the freeze is
  labeled provisional.
- **Quality published:** per period, the share of PRs reverted and the share fixed up within 14
  days.

## 14. Statistics

Definitions. P is Before, September or October. N_P is the period's sampling frame size
(section 4); n_P = 120 sampled PRs. Spend_P and Claude tokens_P are as in section 6; merged
PRs_P counts the period's non-excluded PRs by New York merge day.

- **PR value units:** the PR's tier from the sample value instrument (Sonnet), a chunked PR's
  tier by the rule of section 8. A PR at tier t counts t value units (0, 1, 2, 3, 5 or 8), as in
  the second codebase's report.
- **Value units per merged PR:** v_P = mean PR value units over the period's 120 sampled PRs.
- **Value index per PR:** v_P / v_Before x 100.
- **Estimated period value units:** V_P = N_P x v_P.
- **Cost per value unit:** spend_P / V_P, in dollars at list prices (section 6); and as an
  index, (spend_P / V_P) / (spend_Before / V_Before) x 100.
- **Tokens per value unit:** Claude tokens processed_P / V'_P, where V'_P = N'_P x v'_P counts
  non-Codex PRs only (N'_P non-Codex frame PRs, v'_P over non-Codex sampled PRs); in tokens and
  as an index (Before = 100). Independent of model prices.
- **Cost per merged PR (dollars):** spend_P / merged PRs_P.
- **Free weekly metrics:** per ISO week and per period, spend per merged PR and Claude tokens per
  merged PR. No tiers enter them; no weekly value index is published.

The three headline measures (value units per merged PR, cost per value unit, tokens per value
unit) are reported for Before, September and October separately, each with its index against
Before.

Intervals. Every headline measure and index carries a 95 percent percentile interval from a
**bootstrap stratified by period: 2,000 resamples, each period's 120 sampled PRs resampled with
replacement within the period, with N_P, spend and tokens held fixed**. The agreement
statistics below get the same kind of interval by resampling the PRs they are computed on.

Bootstrap seed labels. Each label below is one stream of resamples (2,000; 10,000 for the
blinding decisions), drawn in the order the resampled PRs are listed in `samples.json` (sorted
by PR number within each stratum, strata in the order given). Every statistic listed with a
label is computed on that label's resamples, so a measure and its index share resamples.

- `bootstrap:headline`: the three headline measures and their indexes, Sonnet tiers (strata:
  Before, September, October).
- `bootstrap:headline_codex`: the same with Codex tiers.
- `bootstrap:trimmed`, `bootstrap:no_chunked`, `bootstrap:ladder`, `bootstrap:fixups`: the
  headline measures and indexes of the sensitivity results of the same names below.
- `bootstrap:opus_index`: the value index per PR on the 60 Opus-subset PRs by each of the three
  scorers (strata: Before, September, October).
- `bootstrap:agree_sonnet_codex` (360 sampled PRs), `bootstrap:agree_opus_subset` (60 PRs; all
  three pairs), `bootstrap:agree_retest` (30 PRs): weighted kappa, exact and within-one-tier
  agreement, and category agreement.
- `bootstrap:kindmatched`: the kind-matched claim, pooled (strata: kinds in the order feature,
  fix, design-docs, refactor-test, each split into run then other).
- `bootstrap:kindmatched:feature`, `bootstrap:kindmatched:fix`,
  `bootstrap:kindmatched:design-docs`: the claim within each kind (strata: run, other).
- `bootstrap:kindmatched_setup`, `bootstrap:kindmatched_codex`: its two sensitivity results,
  pooled.
- `bootstrap:blind_period`, `bootstrap:blind_runother`: the blinding decisions (section 12).

Scorer agreement, on PR-level tiers (chunked PRs by the rule of section 8). Tiers are compared
on their ladder position: tiers 0, 1, 2, 3, 5, 8 are positions 0 to 5.

- **Sonnet and Codex, all 360 sampled PRs:** quadratically weighted Cohen's kappa on ladder
  positions (agreement weight 1 - (i - j)^2 / 25 for positions i and j), the exact-agreement
  rate (same tier) and the within-one-tier rate (positions differ by at most 1).
- **Sonnet, Codex and Opus, the 60 Opus-subset PRs:** the same three statistics for each scorer
  pair.
- **Test-retest:** the same three statistics between the sample and retest Sonnet tiers of the
  30 retest PRs.
- **Category:** the exact-agreement rate of `category` for each pair above (descriptive).
- **Position effect:** mean tier by position in batch (1 to 10).

Sensitivity results, each reported beside the main result:

- **Second instrument:** the three headline indices recomputed with Codex tiers in place of
  Sonnet tiers, published with whether each points the same way as the Sonnet result; if not,
  the report says so. On the 60 Opus-subset PRs, the value index per PR by each of the three
  scorers, each with a 95 percent interval from stream `bootstrap:opus_index` (the 60 PRs
  resampled with replacement within each period, 20 per period).
- **Trimmed:** the 4 highest-value sampled PRs (1 percent of the 360, rounded half up), ranked
  pooled over the three periods by Sonnet tier, ties broken by more changed lines in
  non-generated files and then by the lower PR number, are removed from the sample; every index
  is recomputed with the remaining sampled PRs, N_P and spend unchanged. Only the 1 percent
  threshold.
- **Excluding chunked PRs:** every chunked PR is removed from the value side (14 Before, 11
  September, 5 October sampled PRs), so v_P is the mean over the period's remaining sampled PRs;
  every headline measure and index is recomputed with N_P, spend and tokens unchanged.
- **Ladder:** tiers replaced by their ladder positions (0 to 5), so that the non-linear spacing
  of the scale is not what drives a result.
- **Fix-ups:** sampled PRs identified as fix-ups (section 13) count zero value units.
- **Blinding:** if section 12 finds an unremovable leak, the correct-vs-incorrect score
  comparison: within each period for the period check, and within each group (run, other) for
  the run vs. other check.

Secondary scripted metrics (section 5). Computed by script per period (Before, September,
October, and also July and August) and per ISO week (America/New_York days; the first and last
weeks are partial and their day counts are published), over the in-scope sessions of section 6.
Definitions follow the usage report on a second codebase, not the measured one, wherever they
apply; that report's weeks are UTC weeks, these are New York weeks.

- **Turn:** one Claude message with token usage, deduplicated by request as in section 6. Its
  **context** is its input + cache write + cache read tokens; its **spend** is its tokens at its
  model's list price on its UTC day (section 6), so turn spend sums to period spend (checked per
  period, total and Claude-only, within 1 percent).
- **Spend share above 300K:** Claude turn spend on turns with context above 300,000 tokens,
  divided by all Claude turn spend.
- **Cache-read tokens per turn** and **output tokens per turn:** means over Claude turns.
- **Peak context of main sessions:** for each root (non-subagent) session with a Claude turn in
  the period or week, the largest context among its own turns there; the mean and the median
  over those sessions, and their number.
- **Turns above 300K and above 800K:** the number of Claude turns with context above 300,000 and
  above 800,000 tokens.
- **Spend by model family:** dollars for opus, sonnet, haiku, fable, other Claude models, and
  non-Claude models; each Claude family's share of Claude spend.
- **Root sessions by mode:** root sessions with a Claude turn of their session tree in the
  period or week. Run: a root that typed the run command (section 3); run wins over settle.
  Settle: a root whose first typed run-or-settle command is the settle command (`/stu:settle`
  or its earlier private name). Normal: every other root.
- **Right-censoring:** PRs created on the period's or week's New York days (bot authors
  excluded), with the number still open at the population fetch time (section 2) and the number
  not yet merged or closed at the window's end, both judged from the PRs' merge and close
  timestamps.
- **Decomposition:** Claude tokens per merged PR = turns per merged PR x Claude tokens per turn,
  with the mean context per turn; overall, and for two groups: run (turns of sessions in a stu
  run's session tree; PRs opened under a run root, section 3) and other (turns of the remaining
  attributed Claude work; PRs whose opening root is not a run root, section 3). Turns of automated review, run setup
  and Codex sessions belong to neither group, and their share of Claude tokens is published. The
  group split is descriptive (section 1).

Kind-matched run vs. non-run PRs (October; section 5). The groups are those of section 3 ("other"
is any attributable Claude PR whose opening root is not a run root); the PRs are those of
section 15. Matching is by kind only; size and difficulty are not matched. A PR's value units are its tier from the sample value instrument
(Sonnet), a chunked PR's by the rule of section 8. A PR's cost is its `pr_cost`: the cost
(section 6) of its opening root session's whole session tree, subagents included, divided
equally among the PRs that root opened (a PR opened from several roots sums its shares). For a
group g of n_g PRs, C_g is the sum of their costs and U_g the sum of their value units.

- **Value units per PR by group:** U_g / n_g.
- **Cost per PR by group (dollars):** C_g / n_g.
- **Cost per value unit by group (dollars):** C_g / U_g.
- **Claim statistic:** the ratio (C_run / U_run) / (C_other / U_other). Below 1 means run PRs
  cost less per value unit.
- **Interval:** 95 percent percentile interval from 2,000 bootstrap resamples **stratified by
  kind**: in each resample, each group's PRs of each kind are resampled with replacement within
  that group and kind (cell sizes fixed). Seed labels as listed above. A resample in which a group has zero value units gives that group an infinite cost
  per value unit; the interval is taken over those extended values. The per-group measures get
  intervals from the same resamples.
- **Within kind:** the same four measures and the ratio, with its interval (resampling within
  the kind), for each kind with at least 15 PRs in each group: feature (36), fix (23) and
  design-docs (17). Refactor-test (13 per group) is reported in the pooled ratio only. The
  threshold of 15 was set after these counts were seen (section 5).
- **Sensitivity, setup cost:** `pr_cost_with_setup` in place of `pr_cost`: a run PR's share
  also includes the cost of the run's setup sessions (the sessions that prepared its
  objective), divided the same way; other PRs are unchanged.
- **Sensitivity, second instrument:** Codex tiers in place of Sonnet tiers.
- **Caveat, published beside the number:** this is not a counterfactual for the run work.
  Almost all large features ran in stu runs in October; the October "other" PRs are
  self-selected leftover work, and only about a third of them came from plain sessions
  (section 15); matching is by kind only, and size and difficulty are not matched. The cost
  side was inspected before registration (section 5). The groups also differ
  in which sessions are counted: a PR opened by a run's setup session has no `pr_cost` and is
  not eligible (section 15), and automated review sessions outside a PR's opening session tree
  are in no PR's cost.

Runaway-session measures (secondary, scripted; section 5). Computed by the registered script
(`hashes.txt`) per period (Before, September, October) over the Claude turns defined above.

- **Main sessions over 300K and 800K:** per period and session mode (run, settle, normal, as
  above), the number of root sessions with a Claude turn of their own in the period, and the
  number and share of them whose own largest turn context in the period exceeded 300,000 and
  800,000 tokens. Subagent turns do not count toward a root's peak.
- **Spend above 300K by bucket:** per period and cost bucket (run session trees, run setup
  sessions, other sessions outside a run tree, automated review, Codex), Claude turn spend in dollars
  and the share of it on turns with context above 300,000 tokens; a bucket with $1 or less of
  Claude spend in a period is omitted.

No sampling decision is made after seeing results: the sample, the Opus subset, the retest, the
blinding and the kind-matched draws are made below with fixed seeds and fixed sizes, before any
scoring.

## 15. Seeds and samples

Master seed **20261031**. Each labeled stream is `random.Random(int(sha256("20261031:" +
label).hexdigest()[:16], 16))` in Python 3. Labels: `sample`, `opus`, `retest`, `blind`,
`likeforlike`, `blind_runother`, `batch:<instrument>`, the `bootstrap:<name>` labels of section
14, and `pilot` for the pilot. The label `likeforlike` is the seed stream of the kind-matched
draw, kept under its original name so the draw reproduces; it is not a claim name.

Sampling frame: per period, the scored PRs (not excluded, attributable, with prepared inputs),
sorted by PR number: Before 943, September 653, October 1,073. Transition PRs are never sampled.
Codex PRs are eligible (none was drawn).

- **Sample:** per period, in the order Before, September, October, one draw of 120 from the
  period's frame with stream `sample` (360 in all).
- **Opus subset:** per period, 20 drawn from that period's 120 sampled PRs, stream `opus`.
- **Retest:** per period, 10 drawn from that period's 20 Opus-subset PRs, stream `retest`, so
  scorer noise and inter-scorer disagreement are measured on the same PRs.
- **Blinding:** per period one draw from that period's 120 sampled PRs with stream `blind`:
  17 + 20 for Before and September, 16 + 20 for October; the first part is the holdout, the last
  20 the labeled examples. Holdout and examples are disjoint.
- **Kind-matched run vs. non-run (October):** eligible PRs are October scored-population PRs
  (not excluded, attributable, with prepared inputs) of group run or other (Codex excluded)
  that have a `pr_cost` (section 14). The 56 October other PRs opened from run setup sessions
  (11 roots) have none and are not eligible; every run PR has one. This exclusion was fixed after
  the counts were seen (section 5). Eligible by kind: other
  feature 36, fix 23, design-docs 17, refactor-test 13 (89); run feature 415, fix 435,
  design-docs 41, refactor-test 37. The other group is all 89 eligible other PRs. The run group
  is drawn with stream `likeforlike` (the kind-matched draw's seed label), without replacement, kind by kind in the order feature,
  fix, design-docs, refactor-test, exactly as many run PRs of each kind as the other group has
  (a kind with too few run PRs would give all of them, with the shortfall published; there is
  none): 89 run PRs. Of the 178, 18 are also in the October period sample (run 10, other 8);
  each such PR is scored once and its tier used in both analyses. The other 160 enter only the
  kind-matched claim, never the period measures. Chunked: run 7, other 6.
- **Composition of the 89 other PRs by opening root** (descriptive; the rule is committed by
  hash as the opening-mode script): normal sessions 29 PRs (22 roots); settle sessions 2 (2);
  roots where the model itself invoked a run, settle or fix-campaign skill without a typed run
  command 23 (10); roots that dispatched orchestrator, implementer or merge-gate subagents
  without a typed run command 35 (8). The 89 run PRs come from 82 run roots.
- **Run vs. other blinding:** one stream `blind_runother`, drawn in this order: 15 run and then
  15 other holdout targets from the kind-matched sample, then 20 run and 20 other labeled
  examples from the October PRs of each group (not excluded, with prepared inputs; no cost
  needed) outside the kind-matched sample. The other examples are drawn from the 56 PRs opened
  from run setup sessions, the only other PRs outside the sample.
  Scored inputs (parts): run 110, other 104; new to scoring 160 PRs, 195 parts.

Samples manifest sha256 (canonical JSON of the PR-number lists, including the kind-matched and
run vs. other blinding lists, keys sorted, no whitespace):
`6b9ad0c7f73774712be60a6385661fac1ac4cf459d32e83d2ae308a40567b6de`. The PR numbers are private;
the hash commits to them. The sampling code is committed by hash in `hashes.txt`.

## 16. Publication commitments

- The report publishes value units per merged PR, cost per value unit (in dollars, list prices)
  and tokens per value unit for Before, September and October, with their indexes (Before =
  100) and intervals.
- Spend appears in dollars, labeled as list-price estimates at API rates.
- September and October are always shown separately.
- Flat or negative results are published. Every number carries its caveat beside it, including
  that value comes from a sample of 120 PRs per period and from an uncalibrated model judgment
  (section 17).
- The published per-PR table covers the 360 sampled PRs and the 160 further kind-matched PRs
  (520) and identifies each only by a salted hash of its PR number (salt private), with ISO
  week, period, platform, kind, a line-count bucket, and per scorer the tier, category and
  effort type. Scorer justifications are never
  published: they cite the diff. No titles, paths, descriptions, branch names, or diffs are
  published.
- Exclusion counts, the chunked share of the sample per period, and the non-Claude spend share
  per period are published.
- The secondary scripted metrics of section 14 are published per period and per ISO week.
- The report states, beside the kind-matched claim and the runaway-session measures, what was
  seen before registration (section 5): the claim's cost side and the runaway measures were
  inspected; the value side was not; the within-kind threshold and the exclusion of the
  setup-opened PRs were fixed after seeing counts.
- Both blinding checks are published with their gaps, p values and the guessers' stated cues.
- The kind-matched claim is published with the ratio and its interval (pooled and per kind
  with at least 15 PRs per group), value units per PR and cost per PR by group, both
  sensitivity results, and its caveat beside the number. Its PRs appear in the per-PR table
  with their group.
- The runaway-session measures are published per period, mode and bucket.
- Any change to this method after the pre-registration commit is recorded in `DEVIATIONS.md`
  with its date and reason; rescoring after the outputs are frozen is allowed only by such a
  note.

## 17. Value-tier caveat

There is no human calibration. A tier is one model's judgment of a change's value from its diff
and title, on a coarse, non-linear scale. The second codebase's report observed judge noise of
about one tier per PR. A model judge may favor code written by models; nearly all code in every
period here was written by agents, so this applies to every period alike. Value units measure
the substance of changes relative to one another within one instrument; they are not a measure
of user value. Every published comparison is a ratio within the same instrument.

## 18. Commitment hashes

sha256 of this study's design document (design.md, private):
`a21bbab3ded6e49ed6bacc356555e0c14437260125486573b5b241b362321843`.

`hashes.txt` beside this file lists the sha256 of the design document, the strata rules, the
generated-file rules, the input preparation code, the sampling code, the blinding baseline and
decision code with its tests, the runaway-session script with its tests, the opening-mode script,
each of the three prompts (value, period guess, run vs. other guess), the value answer schema,
and the samples manifest. This file itself is not hashed there; its commit is the commitment.
Files published beside this one are listed by their path here (`prompts/...`, `schema/...`), so
their lines check with `sha256sum -c` in this directory; private files are listed by their
private path and can be checked only on disclosure; the manifest line is a hash of JSON, not of
a file.

## 19. Re-scope before registration (2026-11-01)

This method was first drafted on 2026-10-31 as a census of every scored PR, with a run-led
vs. other-work comparison inside September and October, a second complexity instrument, and a
replication on a public repository. Before anything was registered or scored, the owner
re-scoped it on 2026-11-01 for cost: a census would have used about $1,200 to $2,000 of
subscription quota at API list prices, against a target of about $100 to $150. The changes:

- The fetch windows became New York days at both ends (the first fetch, by UTC date, missed 8
  PRs merged late on 2026-10-31 New York time).
- A stratified random sample of 120 PRs per period replaced the census; Codex hours run on the
  whole sample; Opus on a 60-PR subset; the retest on 30.
- Dropped: the run-led vs. other-work comparison and every statistic that served it (groups,
  within-strata ratios, setup reallocation, weekly work series), the complexity instrument, and
  the public-repository replication, which may return as a separate registration.
- Batches grew from 5 to 10 items; the blinding check shrank from 15 to 5 guesser tasks, with
  the three periods as its classes.

## 20. Re-scope before registration (2026-11-02)

Before anything was registered or scored, the owner changed the scored instrument and added
secondary metrics, so that this study and a usage report on a second codebase, not the measured
one, compare row for row. The changes:

- The scored instrument is a value tier (0, 1, 2, 3, 5, 8, with category and effort type;
  section 10.1), adapted from that report's rubric, in place of a model estimate of the
  engineer-hours a skilled engineer would need to produce the change by hand. The instruments,
  samples, inputs, batches, blinding check and harness are unchanged; only the prompt, the
  answer schema and its validation changed.
- Chunked PRs take the highest tier of their parts (section 8); hours of parts were summed.
- The headline measures are value units per merged PR, cost per value unit (dollars and index)
  and tokens per value unit, in place of the hours-based work index. Scorer agreement is a
  weighted kappa with exact and within-one-tier agreement, in place of ICC(2,1) on log hours and
  factor-2 disagreement. The with-and-without-tests split is dropped (the tier has no test
  share); a ladder-position sensitivity is added; the trim ranks by tier.
- The second report's scripted metrics are added as pre-registered secondary results (section
  14). Its prefilter for mechanical PRs is not adopted (section 7).

### 20.1 Addition before registration (2026-11-02)

Later on 2026-11-02, before anything was registered or scored, the owner approved one more
claim: kind-matched run vs. non-run PRs, October (sections 5, 14, 15). It restores a
narrow form of the run-versus-other comparison dropped in section 19: October only, the two
groups matched by kind, cost per value unit from per-PR costs, an interval stratified by kind.
It is not a counterfactual for the run work (almost all large features ran in stu runs in
October), "other" in October is self-selected leftover work, and matching by kind is the only
adjustment. Its 178 PRs are added to the Sonnet and Codex value instruments (160 PRs, 195 parts
not already in the sample); the Opus subset and the retest are unchanged. An exploratory look at
per-PR costs by period, group and kind motivated the claim; no PR had been scored. The same
addition registers the runaway-session measures (section 14), computed earlier by an
exploratory script, now under test and committed by hash, with unchanged output.

Before registration, an independent review of this text asked for changes, all made the same
day: the claim's name (kind-matched run vs. non-run PRs) and the exact definition of "other",
with its composition by opening mode; a run vs. other blinding check (section 12) with tested
baseline code committed by hash, and both checks before any value scoring; disclosure of what
was seen before registration (sections 5 and 16); the chunked-PR rationale (section 8); named
bootstrap streams (section 14); a single statement of the measurement-session scope (sections 3
and 6); the Codex failure rule (section 9); and the hashes of the runaway script's tests.
