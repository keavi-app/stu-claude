# Stu on Codex

Implement the shared-core, separate-runtime approach approved in the conversation on 2026-10-31. Keep Stu eligible for Anthropic directory review and preserve the existing Claude install contract. No directory submissions or new hosted service are part of this change.

The canonical skills/, agents/, hooks/hooks.json and .claude-plugin/ remain the Claude package. A .codex-plugin manifest explicitly selects Codex-only skill wrappers and hooks under codex/. Codex contracts render current shared instructions through an adapter rather than forking the safety rules. Both runtimes use the same claims, verification, forge, scoreboard and approval records. Config lookup accepts a neutral .stu/stu.md while preserving existing paths and rejecting conflicting local configurations.

Codex uses native clean-context subagents, explicit model/effort selection from available models, native waits and steering, and exact-SHA independent review. Claude maxTurns and cache TTL settings have no implied Codex equivalent. Codex telemetry reads the current session by exact identity, never a recent unrelated file, and never adds cached tokens to an already inclusive input count. Missing supervisor telemetry is a hard handoff. Child warnings must verify identity rather than meter the parent.

Publishing remains enforced by the existing git hook. Codex agent markers must not take the human approval exception. Codex apply_patch inputs must protect approval-file edits and moves, including resolved aliases. Tool hooks are additional guardrails whose trust and runtime limitations are disclosed.

Use standard-library Python 3.9+, bash, git and gh; macOS/Linux/WSL. No dependency installation or changes to GitHub Actions. Test adapter behavior, real git pushes, telemetry isolation and packaging compatibility. Validate both plugin loaders and exercise the nested agent hierarchy on a disposable local repository. Report tested clients and remaining limitations without claiming an unrun overnight soak.
