# Codex Support Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or focused parallel agents. Steps use checkbox syntax for tracking.

**Goal:** Run Stu on local Codex while preserving the Claude package.
**Architecture:** Shared safety contracts and scripts, explicit runtime wrappers/hooks, separate manifests.
**Tech Stack:** Python 3.9 standard library, shell, Git, Claude Code and Codex.
**Spec:** docs/superpowers/specs/2026-10-31-codex-support-design.md

## Global Constraints

- Preserve canonical Claude skills, agents and hook declarations.
- No new runtime dependencies, hosted service or workflow triggers.
- Never guess a current session or silently skip publishing approvals for Codex.
- Unknown supervisor telemetry ends the run with a handoff.

## Review Focus

- A patch moves an unrelated file onto approvals.tsv or edits a symlink alias.
- Child hooks receive parent session_id and must not charge parent usage.
- A machine has both Claude and Codex markers or multiple local configs.
- A cached plugin has a different absolute path and must resolve its own helpers.
- A child finishes with descendants still live; supervisor must not certify it complete.

### Task 1: Publishing guards

Files: scripts/publish_guard.py, scripts/stu_pre_push.py, hooks/publish-guard.sh, regression suites.
- [x] Add failing real-push tests for CODEX_THREAD_ID/CODEX_SHELL and patch approval-file edits/moves/aliases.
- [x] Normalize payloads and markers without changing human/Claude behavior.
- [x] Run existing and new publish guard suites.

### Task 2: Telemetry

Files: scripts/ctx.py, scripts/codex_telemetry.py, scripts/codex_turn_guard.py and tests.
- [x] Add failing fixtures for own-session resolution, deduplicated usage, compaction, malformed input and parent rejection.
- [x] Integrate Codex context reporting and verified child warnings.
- [x] Run existing and new telemetry suites.

### Task 3: Runtime contracts

Files: scripts/stu_codex.py, bin/stu-codex, codex/runtime.md, codex/skills/ and tests.
- [x] Test every role/skill adapter retains common safety rules and excludes unsupported Claude lifecycle instructions.
- [x] Render current source contracts with explicit native Codex runtime bindings.
- [x] Verify from unrelated working directories and package paths containing spaces.

### Task 4: Packaging and shared config

Files: .codex-plugin/plugin.json, codex/hooks.json, scripts/stu_env.py, scripts/stu_forge.py, config/forge tests, Makefile, README.md, docs/codex.md, CHANGELOG.md.
- [x] Test neutral config resolution and conflicting-path errors before implementing.
- [x] Bind Codex git hooks to their selected config; verify human terminal leak checks and missing-config refusal.
- [x] Keep known GitHub plan-unavailable rules handling explicit and opt-in; preserve default Claude errors.
- [x] Package explicit Codex skill/hook roots, retaining Claude manifest behavior.
- [x] Add install, hook trust, approval and capability documentation.
- [x] Run all suites and both loaders. Exercise native nested delegation in a disposable repo, review whole diff and fix findings.
- [x] Record actual native-hook and two-issue delivery results in docs/codex-validation.md.
- [ ] Commit and create one reviewable PR.
