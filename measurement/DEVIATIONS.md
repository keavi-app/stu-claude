# Deviations from the pre-registered method

Pre-registration: keavi-app/stu-claude 71691aff441831f2121ca688d93286bd2caabbde (METHOD.md sha256 f50c41a6...).
Every change after that commit is listed here.

## D1 2026-11-02: value_sonnet partial reads rescored; scorer read rule tightened

- **Found:** after 3 rounds of `value_sonnet` (300 of 615 items done), one scorer reported it
  had answered 4 items from a truncated read. A check of every scorer transcript in that session
  (structure only: which Read calls were made on which input, and whether any Read result
  contained the input's last line `--- DIFF END ---`) found 76 of the 300 items whose scorer
  never saw the end of its input. Value inputs are uncut by design (median 34 KB, max 121 KB); the
  Read tool stops early on large files without failing, and the scorer instruction ("read it in
  consecutive parts ... until you have read all of it") was not followed.
- **Change:** step 3 of both scorer agent definitions (`scoring/.claude/agents/pr-scorer-sonnet.md`,
  `pr-scorer-opus.md`; not part of the pre-registered hashed files) now requires reading every
  input to its last line: page with offset = the line after the last one shown and limit 400, and
  stop only when Read reports the offset is past the end of the file (a short or truncated result
  is not the end). Prompts, schema, inputs, batch size and everything in METHOD.md are unchanged.
- **Rescoring:** the 76 outputs were moved to `scoring/rejected/value_sonnet/` (an `.err.txt`
  beside each names this entry) and returned to pending; they are rescored under the new rule in
  later batches, so their batch ids and positions differ from first issue. The rejected answers
  are kept and never analysed. Approved by Jon 2026-11-02 before the move.
- **Ongoing check:** after every round of every Claude instrument, a transcript check collects
  the line numbers of every Read result on each input and compares them with the file's line
  count; any item whose scorer was not shown every line is rejected and rescored the same way.
  The 224 kept outputs pass this line-level check (every line seen).
  The check is `scripts/read_coverage.py <instrument> --reject` (+ `tests/test_read_coverage.py`),
  run after every round's `collect` (RUNBOOK step 6).
- **Not affected:** `value_codex` (the whole input goes to `codex exec` on stdin) and the 224
  kept `value_sonnet` outputs. The blinding checks were affected: see D2.

## D2 2026-11-02: blinding guess tasks with partial reads rescored; both checks re-decided

- **Found:** the D1 transcript check, applied to the guess instruments, showed that 4 of the 8
  guess tasks skipped large spans of their input (each input bundles 50-70 changes, 350-540 KB):
  `guess_sonnet` 9a8beda7a3c9, 9d859cd0f9c6, 4b39e0591436 (roughly 50-70% of lines unseen, mostly
  labelled examples) and `guess_runother_sonnet` 85d37f89b104 (about 50% unseen). The other 4 were
  read in full. Unseen examples bias the guesser's accuracy down, so the first decisions (both
  "leak": false; period gap 0.16 p 0.1221, runother gap 0.167 p 0.1326) were biased toward "no
  leak". Those decisions had already let `value_sonnet` (3 rounds) and `value_codex` start.
- **Action (approved by Jon 2026-11-02):** the 4 outputs were moved to
  `scoring/rejected/<instrument>/` and rescored under the D1 read rule; the 4 fully read outputs
  are kept. The first decision files are kept as `data/blinding_<check>.superseded-D2.json`;
  `blinding.py decide` is rerun on the completed instruments and its result replaces them. The
  baselines do not depend on the guesses and are unchanged. `value_sonnet` rounds are held until
  the new decisions; if either check leaks, scoring stops as in METHOD.md section 12, and the
  value outputs already written are held, not analysed, until the cue is resolved.
- **Rescoring detail:** two of the three period rescores were again partial (about 35% of lines
  seen; those agents started under an interim wording of the D1 rule that guess inputs, which hold
  many `--- DIFF END ---` lines, could satisfy early); they were rejected
  (`<item>.r2.json`) and rescored a third time under the final rule. Final state: all 5 period
  and all 3 runother guess outputs read in full by the line-level check; `model_ids.py` ok for
  every batch (claude-sonnet-5-5).
- **Outcome (2026-11-02):** runother `"leak": false` (llm 0.667, baseline 0.567, gap 0.100,
  p 0.2727, 30 targets). **period `"leak": true`** (llm 0.68, baseline 0.36, gap 0.32, p 0.0028,
  50 targets). Per METHOD.md section 12 value scoring stopped at once: the Codex runner was
  killed (no `codex exec` left running, `codex-cwd/` empty). State held: `value_sonnet` 224 of 615
  done (76 rejected under D1, pending), `value_codex` 113 of 615 done. Nothing from either is
  analysed until the cue is resolved; whether they are rescored after input regeneration is
  decided then.
- **Note:** re-deciding is a second look at the blinding outcome, made because the first look
  was invalid by protocol (scorers not reading their input), not because of its result; the
  first decision values are recorded above.

## D3 2026-11-02: period cue removed from titles (removal attempt 1 of 2); inputs regenerated

- **Cue:** the guess `reason` fields of the leaking period check named title format in most
  correct Before guesses ("conventional-commit 'fix:' prefix ... the dominant cue for class C").
  Confusion: Before 15 of 17 right; Sep vs Oct near chance (topic continuity, "Android:"-style
  prefixes). On stripped titles of the 360-PR sample: conventional-commit prefix Before 70%, Sep
  8%, Oct 1%; other "Area:" prefix 4% / 37% / 72%; lowercase start 70% / 22% / 26%.
- **Change (approved by Jon 2026-11-02):** `scripts/prep.py` `strip_title` now ends with
  `normalize_title`: up to four leading prefixes are removed, each either a conventional-commit
  `type(scope)!:` (feat, feature, fix, fixes, fixed, chore, doc, docs, refactor, test, tests,
  perf, ci, build, style, revert, wip) or an "Area:" prefix of one or two words; the first letter
  is capitalised. The rest of the title is unchanged. Applies to every prepared input (value,
  complexity, guess, retest). After the change, on the same sample: conventional 0% in every
  period, "Area:" 2% / 7% / 11%, lowercase 0%. Hash `scripts/prep.py` was 266f84f2... (in the
  published hashes.txt), now f789031f...; `tests/test_prep.py` updated (+1 test of 15 cases;
  expectations of 3 tests changed to capitalised, prefix-free titles), now 0ccd6644...; suite
  227 green.
- **Regenerated:** `prep.py` over all 2,910 PRs (201 chunked, unchanged); `data/prep_index.json`
  identical; every hours and complexity input is byte-identical except its title line (3,804 files
  changed, 2,480 identical). Retest inputs regenerated with `prep_retest.py` (30 PRs, 31 items;
  `--check` ok). Guess tasks rebuilt for both checks: same class letters, same target groups and
  example order (seeded), new task ids; no title with a conventional-commit prefix remains.
  Blinding baselines unchanged (they use diff stats and platform only).
- **Superseded, archived, never analysed:** everything scored on the old inputs is under
  `scoring/superseded/D3/`: the old inputs (`inputs-pre-D3.tgz`, `inputs-retest/`, `inputs/`),
  `prep_index.pre-D3.json`, and the full state (manifest, config, batches, outputs, rejected,
  model_ids, codex logs) of `guess_sonnet`, `guess_runother_sonnet`, `value_sonnet` (224 done +
  76 rejected) and `value_codex` (113 done), plus the D2-era decision files. The instruments
  were then initialised fresh.
- **Next:** both checks rerun on the new inputs with the D1 read rule and line-level check. If
  neither leaks, `value_sonnet` and `value_codex` restart from zero. If the period check still
  leaks, a second removal attempt follows; after two failed attempts the method stops for Jon.
- **Outcome of attempt 1 (2026-11-02):** both checks rerun on the D3 inputs, all 8 guess outputs
  read in full by the line-level check (one period task needed two reissues: twice the guesser
  stopped at line 8,800 of 8,840, never saw the answer-format lines, and wrote an object instead
  of an array; `collect` rejected both), `model_ids.py` ok. runother `"leak": false` (llm 0.533,
  baseline 0.567, gap -0.033, p 0.7966). **period `"leak": true`** (llm 0.58, baseline 0.36,
  gap 0.22, p 0.0328). Confusion: Before 8 of 17 right (was 15), Sep 11 of 17, Oct 10 of 16. The
  reasons now cite topic continuity (the same feature work in the period's examples) rather than
  surface format, with isolated mentions of title style and other details of the diffs. Feature
  names and file details are withheld here because the product is not yet public. No value instrument initialised since D3.

## D4 2026-11-02: no second removal attempt; value scoring proceeds under the leak fallback

- **Decision (Jon, 2026-11-02):** the cue left after D3 is topic continuity, the content of the
  diffs themselves, and no further surface cue could be removed without damaging what the value
  scorer must judge. A second removal attempt is therefore not made. This departs from the
  wording "after two attempts" in METHOD.md section 12 (one attempt made, not two); the fallback
  of that section applies as written: value scoring proceeds on the D3 inputs, the period gap is
  published (llm 0.58, baseline 0.36, gap 0.22, p 0.0328, 50 targets; first attempt's figures in
  D3 and the pre-D3 figures in D2 published beside it), and the value scores of the holdout PRs the
  guesser classified correctly and incorrectly are compared within each period. The run vs.
  other check did not leak and needs no fallback.
- **Restart:** `value_sonnet` and `value_codex` are initialised fresh on the D3 inputs and scored
  from zero under the D1 read rule and line-level check. `value_opus` and `value_retest` follow
  in the RUNBOOK order on the D3 inputs.

## D5 2026-11-02: smaller batches for the remaining value items; Read size fallback for scorers

- **Found:** in the post-D4 `value_sonnet` session, the line-level read check (D1) rejected 6, 9
  and 19 outputs in three rounds of 100 (556 of 615 done, 59 pending after round 3). Rejected
  items return to pending together, so `next` packs the largest inputs (65-120 KB each) into the
  same batches; scorers given ten such inputs stopped partway and answered from what they had
  seen, despite the D1 rule (one batch: all 10 partial; another: 5 items stopped at exactly line
  800). The same 6 items failed three times. Separately, `a22aadcf598d` (101 KB in 308 lines)
  cannot be read under the D1 rule at all: from line 221 one 400-line page is about 80 KB and
  Read refuses it as too large; `77810ffa2de0.5` has pages up to about 55 KB.
- **Change 1 (batch size):** the remaining `value_sonnet` items are issued with
  `queue.py next value_sonnet --size 3` instead of the pre-registered 10. Batch size only sets
  how many independent items one scorer handles; prompt, schema and inputs are unchanged and
  each item is still scored on its own input. Items already done keep their size-10 batch ids.
  The analysis can tell the two groups apart by `batch_id` (batch files record their items).
- **Change 2 (read rule):** step 3 of both scorer agent definitions (`pr-scorer-sonnet.md`,
  `pr-scorer-opus.md`) adds: if a Read fails because its result is too large, retry at the same
  offset with half the limit (200, 100, 50, 25, 10, 1) until it succeeds, then go on paging with
  limit 400. Nothing else in the rule changes; the line-level check still rejects any partial
  read.
- **Not affected:** `value_codex` (whole input on stdin); the 556 kept `value_sonnet` outputs,
  all of which pass the line-level check. `value_opus` and `value_retest` will use the amended
  read rule from their start; whether they also use a smaller batch size is decided before they
  are initialised. Approved by Jon 2026-11-02 before the change.
- **value_opus batch size (Jon, 2026-11-02):** `value_opus` is issued with `--size 3` from its
  first batch, for the same reason as Change 1 (in the last two `value_sonnet` rounds at size 3,
  59 of 60 items were read in full at first issue).
- **value_retest batch size (Jon, 2026-11-02):** `value_retest` is issued with `--size 3` from
  its first batch, for the same reason as `value_opus`.

## D6 2026-11-03: results published before the final quality pass

- **Change (Jon, 2026-11-03):** METHOD.md freezes the revert and fix-up data on 2026-11-14 and
  runs the final pass on or after 2026-11-15. The write-up is published on 2026-11-03 from the
  provisional pass instead, with reverts and fix-ups counted for PRs merged through 2026-11-03
  (`quality.py fetch-mirror`, `fetch-followup` and `run` rerun that day; counts identical to the
  2026-11-02 pass: October 0 of 1,073 reverted, 5 of 1,073 fixed up). PRs merged late in October
  have therefore had less than the full two weeks; the write-up says so.
- **Still to come:** the final pass runs on or after 2026-11-15 exactly as pre-registered. If any
  published figure changes, the write-up is corrected and the change is listed here.
