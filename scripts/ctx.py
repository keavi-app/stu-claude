#!/usr/bin/env python3
"""Report THIS session's current context size, and which budget band it is in.

The check /stu:run binds to every subagent return
(skills/run/SKILL.md): "how big am I right now, and which
band am I in".

A failed read is HARD, not OK. This script exits nonzero rather than guessing,
and its caller is required to treat that as the hard ceiling: not knowing is not
the same as being under, and "it felt fine" is how every earlier context rule
failed.

Claude context is measured as:
    input_tokens + cache_creation_input_tokens + cache_read_input_tokens
for the most recent main-chain assistant message.
Codex context is the latest request's input_tokens (cached tokens are already
included). Codex "turns" count distinct model requests, not user turns. Select
with STU_RUNTIME=claude|codex; otherwise CLAUDE_CODE_SESSION_ID wins, followed by
CODEX_THREAD_ID. The Codex adapter verifies its own session metadata and never
chooses a transcript by mtime. STU_TRANSCRIPT_PATH may override its path, but
never its identity.

Bands (override with RUN_CTX_SOFT / RUN_CTX_HARD):
    < 160k   OK
    >= 160k  SOFT   stop opening new threads; finish the unit; hand off
    >= 200k  HARD   hand off now, mid-unit if necessary

Bands are operational -- they say when to hand off, not whether the design works.
The measured floor is substantial (skill file + project guide + MCP schemas) before any work,
so a band near it fires on every run and means nothing. Whether the architecture
holds is a GROWTH question, not a peak one: see docs/design-rationale.md.
This script reports both: the band against current context, and growth as the
final-decile mean minus the first-decile mean. Growth is a SUBTRACTION, not a
ratio, so a floor that rises cancels out of it -- a ratio would quietly drift
toward 1.0 as this skill file grows and start passing sessions it used to fail.

Never guesses. If it cannot identify this session's transcript it says so and
exits nonzero -- a plausible wrong number is worse than no number, because the
whole point of the band is that it fires.
"""
import glob
import json
import os
import sys

SOFT = int(os.environ.get("RUN_CTX_SOFT", 160_000))
HARD = int(os.environ.get("RUN_CTX_HARD", 200_000))
# Measured on project A: growth runs a few thousand tokens per deduped assistant turn, so
# 30k is about a dozen turns -- almost exactly the designed cycle shape. Most sessions
# exceeded it before the batching rules were enforced.
GROWTH_MAX = int(os.environ.get("RUN_CTX_GROWTH_MAX", 30_000))
GROWTH_MIN_TURNS = 10
# An opening handshake can be a few hundred tokens; records at or below this
# size are dropped before the growth deciles are cut.
HANDSHAKE_MAX = 1000


def die(msg):
    sys.stderr.write("ctx.py: %s\n" % msg)
    sys.exit(2)


def runtime():
    """Explicit runtime wins; preserve Claude when Codex's env was inherited."""
    selected = os.environ.get("STU_RUNTIME")
    if selected:
        if selected not in ("claude", "codex"):
            die("STU_RUNTIME must be claude or codex")
        return selected
    if os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude"
    return "codex" if os.environ.get("CODEX_THREAD_ID") else "claude"


def transcript_path():
    if runtime() == "codex":
        import codex_telemetry
        try:
            return codex_telemetry.transcript_path()
        except (OSError, codex_telemetry.TelemetryError) as exc:
            die(str(exc))
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        die("CLAUDE_CODE_SESSION_ID is not set -- cannot identify this session. "
            "Refusing to guess from file mtimes: this project directory holds "
            "transcripts from concurrent sessions.")
    root = os.path.expanduser("~/.claude/projects")
    hits = glob.glob(os.path.join(root, "*", sid + ".jsonl"))
    if not hits:
        die("no transcript found for session %s under %s" % (sid, root))
    if len(hits) > 1:
        die("ambiguous: %d transcripts match session %s" % (len(hits), sid))
    return hits[0]


def scan(path):
    """Return (current_ctx, peak_ctx, turns, ctxs) for the selected runtime."""
    if runtime() == "codex":
        import codex_telemetry
        try:
            return codex_telemetry.scan(path)
        except (OSError, codex_telemetry.TelemetryError) as exc:
            die(str(exc))
    cur = peak = turns = 0
    ctxs = []
    seen = set()
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            # Subagent turns are their own context, not ours.
            if d.get("isSidechain"):
                continue
            m = d.get("message") or {}
            u = m.get("usage")
            if not isinstance(u, dict):
                continue
            mid = m.get("id")
            if mid:
                if mid in seen:
                    continue
                seen.add(mid)
            ctx = ((u.get("input_tokens") or 0)
                   + (u.get("cache_creation_input_tokens") or 0)
                   + (u.get("cache_read_input_tokens") or 0))
            if not ctx:
                continue
            cur = ctx           # append-ordered file: the last one wins
            peak = max(peak, ctx)
            ctxs.append(ctx)
            turns += 1
    return cur, peak, turns, ctxs


def scoreable(ctxs):
    """Turns large enough to be real context rather than an opening handshake."""
    return [c for c in ctxs if c > HANDSHAKE_MAX]


def growth(ctxs):
    """Final-decile mean minus first-decile mean, or None if too few turns.

    A subtraction rather than a ratio on purpose: both deciles carry the same
    floor, so the floor cancels.

    Handshake-sized records are dropped BEFORE the deciles are cut. In a short
    session a single few-hundred-token opener would otherwise be the whole first
    decile, and growth would report the floor itself as accumulation --
    destroying the exact cancellation the metric depends on and failing the gate
    for a session that never grew. Not observed in practice (every measured
    session opened well above a handshake); guarded because a spurious failure of a design gate is
    as expensive as a missed one.

    Returns an int so the displayed value and the threshold comparison agree.
    """
    real = scoreable(ctxs)
    if len(real) < GROWTH_MIN_TURNS:
        return None
    n = max(1, len(real) // 10)
    return int(round(sum(real[-n:]) / n - sum(real[:n]) / n))


def growth_verdict(g):
    """The verdict string for a growth value. The boundary belongs to OK."""
    return "OK" if g <= GROWTH_MAX else "EXCEEDED - you are accumulating"


def growth_line(g, ctxs):
    """The growth line exactly as printed. Extracted so the suite can assert on
    production output rather than on a reimplementation of it -- a test that
    rebuilds the format string stays green through a formatting regression."""
    if g is None:
        return " growth: n/a (needs %d turns, have %d)" % (
            GROWTH_MIN_TURNS, len(scoreable(ctxs)))
    return " growth: %s tokens  [%s]   max: %s" % (
        format(g, "+,"), growth_verdict(g), format(GROWTH_MAX, ","))


def band(ctx):
    if ctx >= HARD:
        return "HARD EXCEEDED - hand off now, mid-unit if necessary"
    if ctx >= SOFT:
        return "SOFT EXCEEDED - finish this unit, then hand off"
    return "OK"


def main():
    path = transcript_path()
    cur, peak, turns, ctxs = scan(path)
    if not turns:
        die("transcript %s has no usage records yet" % path)
    print("context: %s tokens  [%s]" % (format(cur, ","), band(cur)))
    print("   peak: %s   turns: %d   soft: %s   hard: %s"
          % (format(peak, ","), turns, format(SOFT, ","), format(HARD, ",")))
    print(growth_line(growth(ctxs), ctxs))


if __name__ == "__main__":
    main()
