# Codex support validation

Validated on 2026-10-31 with Codex CLI 0.166.0 and Python 3.9.6 on macOS.

- `make test` passed the shared Python and shell suites, including the existing
  Claude regression suites. The final native-attribution hardening was separately
  verified with all 29 telemetry tests and the unchanged Claude context suite.
- New behavioral coverage includes 15 publishing tests using real git pushes,
  six config tests, six forge capability tests, and nine contract adapter tests.
- `claude plugin validate --strict` passed. Its pre-existing directory warning
  about a missing listing icon remains; directory safety/policy approval was not
  requested or obtained.
- Codex's actual plugin loader exposed `stu:init`, `stu:run`, `stu:settle`, and
  `stu:fix-campaign`, selecting the Codex hook manifest rather than Claude's.
- A native `apply_patch` attempt to create an approval file was denied by Stu's
  PreToolUse hook. The file remained absent. Captured input confirmed the native
  `tool_input.command` patch shape; no alternative editing method was attempted.
- A separate native nested-agent probe captured both root and child hook payloads.
  A grandchild's own ID and transcript differ from both its immediate parent and
  the common root session ID; hook commands had no CODEX_THREAD_ID environment
  variable. The parser recognized the captured grandchild payload and rejects a
  mismatched optional agent ID.
- An installed `$stu:run` completed two sequential issues in a disposable private
  GitHub repository in one supervisor cycle. Each fix had observed failing
  regression tests, a caught behavioral mutant, a fresh exact-SHA detached review,
  a PR, and a separately dispatched merge gate that collected its own evidence.
  Both PRs merged and both issues closed. The supervisor's final `stu-run-check`
  reported both units `CLOSED merged-on-base` and terminal `OK`; the scoreboard
  settled with nothing outstanding. An independent read of the final remote main
  revision passed all 10 tests. No GitHub Actions workflows were added.

The sandbox's first attempt correctly stopped on GitHub Free's private rules
endpoint restriction. The subsequent run used the new explicit optional rules
capability handling; Claude's default command still returns its original error.

The integration run used reviewed hook definitions with Codex's invocation-scoped
hook-trust bypass. Normal installation still requires user review through `/hooks`;
no persistent hook trust was granted. Overnight duration, other client versions,
other operating systems, and cost calibration across large campaigns remain
unverified. Context hooks remain advisory, without Claude's native maxTurns or
cache-TTL guarantees.
