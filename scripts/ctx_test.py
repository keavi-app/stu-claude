#!/usr/bin/env python3
"""Regression suite for ctx.py's growth metric (the supervisor design's growth gate).

Growth is a design gate now, so it has to fire on a session that accumulated and
pass one that did not -- a metric that only ever returns OK is worth nothing, and
one that fails a flat session is worse, because it discredits the gate.

Run: python3 scripts/ctx_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctx  # noqa: E402

FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


FLOOR = 60_000

# 1. A flat supervisor: context never moves. The O(1) claim holds.
check("flat session scores 0", ctx.growth([FLOOR] * 40), 0)

# 2. Accumulation across a run: the shape the growth gate exists to catch.
#    First decile (4 turns) averages 60k; last decile averages 160k.
climbing = [FLOOR] * 4 + list(range(70_000, 150_000, 5_000)) + [160_000] * 4
check("climbing session is caught", ctx.growth(climbing) > ctx.GROWTH_MAX, True)

# 3. Too few turns is n/a, never a number. A 3-turn session has no trend.
check("short session is n/a", ctx.growth([FLOOR] * 3), None)

# 4. THE HANDSHAKE CASE. A few-hundred-token opener must not become the first
#    decile and report the floor itself as growth. Without the filter this
#    returns ~+59k and fails a session that never grew.
handshake = [400] + [FLOOR] * 11
check("handshake is excluded", ctx.growth(handshake), 0)
check("handshake does not fabricate growth",
      ctx.growth(handshake) <= ctx.GROWTH_MAX, True)

# 5. Handshakes are dropped before the turn count is applied, so a session that
#    is only long enough WITH the handshake is still n/a.
check("handshake does not pad the turn count", ctx.growth([400] * 5 + [FLOOR] * 6), None)

# 6. A shrinking context reports a signed negative, not "+-5,000". Asserted on
#    ctx.py's own output line -- rebuilding the format string here would stay
#    green through exactly the regression it is meant to catch.
shrinking = [100_000] * 5 + [FLOOR] * 5
g = ctx.growth(shrinking)
line = ctx.growth_line(g, shrinking)
check("shrinking is negative", g < 0, True)
check("shrinking has no double sign", "+-" in line, False)
check("shrinking renders a minus", "-40,000" in line, True)
check("shrinking passes", "[OK]" in line, True)

# 7. Display and comparison use the same value -- no truncate-then-compare skew
#    that could print an EXCEEDED verdict against a number equal to the max.
check("growth is an int", isinstance(ctx.growth([FLOOR] * 40), int), True)

# 8. Exactly at the cap is OK, not EXCEEDED. Boundary belongs to the passing side,
#    checked through the production verdict function.
at_cap = [FLOOR] * 5 + [FLOOR + ctx.GROWTH_MAX] * 5
check("cap boundary is exact", ctx.growth(at_cap), ctx.GROWTH_MAX)
check("cap boundary passes", "[OK]" in ctx.growth_line(ctx.growth(at_cap), at_cap), True)
over = [FLOOR] * 5 + [FLOOR + ctx.GROWTH_MAX + 1] * 5
check("one over the cap is caught",
      "[EXCEEDED" in ctx.growth_line(ctx.growth(over), over), True)

# 9. The n/a line reports the SCOREABLE turn count, not the raw one, so a
#    handshake-padded session does not look longer than it is.
padded = [400] * 5 + [FLOOR] * 6
check("n/a line counts scoreable turns",
      "have 6)" in ctx.growth_line(ctx.growth(padded), padded), True)

if FAILURES:
    print("ctx_test: %d FAILED" % len(FAILURES))
    for f in FAILURES:
        print("  - " + f)
    sys.exit(1)
print("ctx_test: all checks passed")
