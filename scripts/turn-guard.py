#!/usr/bin/env python3
"""PostToolUse hook: tell an agent its own turn count and context size against budget.

An agent cannot count its own turns from inside a run, and a budget stated only
in prose goes unheeded -- on project A, orchestrators routinely broke their
120-turn budget against a rule that had been written, with its
rationale, two weeks earlier. The rule was never the problem. Nothing was
telling the agent.

TWO AXES, because neither implies the other. Turns catch thrash (a fourth attempt
at one failure) -- a quality signal before a cost one. Context catches spend: a
turn re-reads everything before it, so context sets what a turn COSTS. They come
apart both ways: 60 turns that read three large files sit at 300k; 200 small greps
stay at 140k. On a second codebase, the implementers with the largest
context were a large share of a run's cost -- every one of them inside
the turn bar it was given.

This fires DURING the run: once on approach (85% of the turn budget, or the
context SOFT band), again at the bar, then every 25 turns past it. Repeating
matters: an agent 400 turns deep has pushed the first warning out of the context
window it would have had to remember it in.

Wired as a PostToolUse hook by the plugin's hooks/hooks.json:

    "PostToolUse": [{"hooks": [{"type": "command",
        "command": "python3 \\"${CLAUDE_PLUGIN_ROOT}/scripts/turn-guard.py\\"",
        "timeout": 10, "statusMessage": "Checking turn budget"}]}]

A plugin hook fires in EVERY session of every repo once installed, so the guard
exits 0 immediately -- before opening any transcript or writing any state -- for
the main session (no `agent_id`) and for any `agent_type` that neither starts with
AGENT_PREFIX nor is a generic seat named in GENERIC_AGENT_BUDGETS, including a user's
own agent that happens to be named `orchestrator`. Budgets for plugin agents are looked
up by the bare name after the prefix.

GENERIC SEATS. `general-purpose` and `fork` subagents are not plugin agents, so they
carry no definition naming a handoff. They are watched (turn budget and the fleet
context bands, with a report-back clause in place of the definition wording) only when
ALL of these hold, checked in this order before any transcript is opened or state file
written: the type matches a key exactly (unprefixed); the payload carries a `cwd`; that
`cwd` resolves (stu_env.resolve, require_config=True, forge_lookup=False) to a configured
row; and a stu run is live for that row's RUN_HOME (at least one non-hold, non-stale row
in its claims file, read in process). Any failure on that path, including SystemExit
from run_claims, leaves the seat unwatched: a hook is inert, it never errors.

State lives in $CLAUDE_PLUGIN_DATA/turn-guard/ (else ~/.stu/.turn-guard/);
RUN_TURN_GUARD_DIR overrides both.

The agent's type and id come from the hook payload (`agent_type`, `agent_id`),
not from the transcript: inside a subagent, `transcript_path` is the PARENT
session's transcript, so deriving either from it watches the wrong agent.

Never fails a tool call. A telemetry guard that can break a run would cost more
than the budget it protects, so every path returns 0.

Budgets are keyed by agent type. Add a row to AGENT_TURN_BUDGETS for each agent
definition that declares one; the agent's own .md file is the source of truth
and this table should mirror it. An agent with no row is watched on neither axis:
context warnings ride the same table, so the two stay in one place.

Context bands are per agent type (AGENT_CTX_BANDS, beside the turn budgets); an
agent type without a row gets the fleet pair. RUN_CTX_SOFT / RUN_CTX_HARD, when
set, override every agent's bands. ctx.py is the supervisor's own meter and keeps
its own default pair (the fleet pair below): the supervisor is neither agent type
here, so the two tools answer for different agents. ctx.py reads the same
RUN_CTX_SOFT / RUN_CTX_HARD override, so setting them moves both tools at once.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# Plugin agents are namespaced: the hook payload carries "stu:orchestrator".
AGENT_PREFIX = "stu:"

# Generic subagent seats (no stu definition). Keys are the observed, unprefixed
# `agent_type` payload values; a fork reports "fork", a generic subagent "general-purpose".
GENERIC_AGENT_BUDGETS = {"general-purpose": 140, "fork": 140}
# Said in place of "the handoff your <type> definition names", which is false for them.
GENERIC_REPORT_CLAUSE = "Write what you did and what is left in your report, then return."

# Declared in each agent's own definition. Kept here so a breach is reported
# against the budget that agent actually carries, not a fleet-wide bar.
AGENT_TURN_BUDGETS = {
    "orchestrator": 120,
    # Looser than the context bands on purpose. Re-measured at 140 against past
    # runs, context fires first on every run that trips anything and this bar on none:
    # it is a runaway backstop (thrash at low context, a 200-turn run of small
    # greps), not the working bar. At 100 it had one unique catch and would have
    # forced a handoff on the 125-140-turn runs that finish cleanly today.
    "implementer": 140,
}

# Context bands. SOFT = finish the unit and hand off; HARD = hand off now,
# mid-unit if necessary. Keys mirror AGENT_TURN_BUDGETS. Numbers from
# project A's token logs: an
# orchestrator's floor is high and most of
# them passed the old 160k soft band, so it gets the earlier pair; an implementer
# is cheaper per turn and few passed 190k, so it keeps most of the old room.
AGENT_CTX_BANDS = {
    "orchestrator": (120_000, 160_000),
    "implementer": (150_000, 190_000),
}
# The fleet pair: any agent type with no row above. RUN_CTX_SOFT / RUN_CTX_HARD,
# read at call time, override the table for every agent type.
FLEET_CTX_BANDS = (160_000, 200_000)


def guard_ctx_bands(agent_type: str | None) -> tuple[int, int]:
    """(soft, hard) for this agent type. An env override beats the table."""
    soft, hard = AGENT_CTX_BANDS.get(agent_type or "", FLEET_CTX_BANDS)
    return (
        int(os.environ.get("RUN_CTX_SOFT") or soft),
        int(os.environ.get("RUN_CTX_HARD") or hard),
    )


def guard_state_dir(env) -> Path:
    """RUN_TURN_GUARD_DIR, else the plugin data dir, else ~/.stu/.turn-guard."""
    if env.get("RUN_TURN_GUARD_DIR"):
        return Path(env["RUN_TURN_GUARD_DIR"])
    if env.get("CLAUDE_PLUGIN_DATA"):
        return Path(env["CLAUDE_PLUGIN_DATA"]) / "turn-guard"
    return Path.home() / ".stu" / ".turn-guard"


GUARD_STATE_DIR = guard_state_dir(os.environ)
# Warn once on approach, again at the budget, then every this-many turns past it.
GUARD_APPROACH_FRACTION = 0.85
GUARD_REPEAT_TURNS = 25
# One logical turn can be written to the transcript more than once. Measured
# over 400 subagent transcripts, every re-emission was ADJACENT to the record
# it repeats (max distance 1). The window is bounded rather than unbounded
# because this state file is rewritten after every tool call, so a set that
# grows with the run would be paid for on every one of them -- the quadratic
# shape the guard exists to prevent. 512 is ~500x the observed distance, and
# the bound fails safe: a duplicate beyond it costs one over-counted turn, so
# the guard warns marginally early.
GUARD_RECENT_IDS = 512


def _guard_state_path(key: str) -> Path:
    """One state file per agent. Never one shared file.

    Many agents run concurrently and every one of them fires this hook after
    every tool call. A single JSON rewritten in place loses whichever writer
    lost the race. Keyed by digest because neither an agent id nor a transcript
    path is a safe filename.
    """
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return GUARD_STATE_DIR / f"{digest}.json"


def guard_counting_transcript(payload: dict, transcript: Path) -> Path:
    """The transcript whose turns belong to THIS agent.

    Inside a subagent, `transcript_path` is the parent session's transcript,
    whose records are the supervisor's — counting it charges an orchestrator
    for turns it never took, and leaves its own budget unwatched. A subagent's
    own turns live in `<session>/subagents/agent-<agent_id>.jsonl`.
    """
    agent_id = payload.get("agent_id")
    if not agent_id:
        return transcript
    if transcript.stem.startswith("agent-"):
        return transcript  # already the subagent's own transcript
    name = str(agent_id)
    if not name.startswith("agent-"):
        name = f"agent-{name}"
    own = transcript.with_suffix("") / "subagents" / f"{name}.jsonl"
    return own if own.exists() else transcript


def _usage_context(msg: dict) -> int:
    """Context this turn was billed for: what the model read, cached or not.

    Same three fields ctx.py sums, so both report one number.
    """
    u = msg.get("usage") or {}
    try:
        return (
            int(u.get("input_tokens") or 0)
            + int(u.get("cache_creation_input_tokens") or 0)
            + int(u.get("cache_read_input_tokens") or 0)
        )
    except (TypeError, ValueError):
        return 0


def _count_turns_since(
    path: Path, offset: int, recent_ids: list[str]
) -> tuple[int, int, str | None, int]:
    """Count assistant turns from `offset` on.

    Returns (turns, new_offset, agent_type, context). Context is the LAST turn's,
    not the largest: compaction and context editing both shrink it, and the live
    question is how big the agent is now, not how big it ever was. 0 means no
    billed turn appeared in these bytes -- the caller keeps its previous reading
    rather than treating that as "small".

    Incremental by byte offset: re-parsing the whole transcript after every
    tool call would make the guard itself quadratic in run length, which is the
    cost shape it exists to prevent. `recent_ids` is mutated in place and
    carries the dedup window across calls.
    """
    agent_type = None
    context = 0
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if offset > size:  # transcript truncated or replaced under us
                offset = 0
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return 0, offset, None, 0

    # Whole lines only. A partial trailing line is left for the next call, or
    # the turn it belongs to would be counted twice.
    end = data.rfind(b"\n")
    if end == -1:
        return 0, offset, None, 0

    turns = 0
    for line in data[: end + 1].split(b"\n"):
        if not line or b'"assistant"' not in line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            continue
        if rec.get("attributionAgent"):
            agent_type = rec["attributionAgent"]
        if rec.get("type") != "assistant":
            continue
        msg = rec.get("message") or {}
        # Usage is what makes a record a billed turn; sidechain scaffolding
        # carries none.
        if not msg.get("usage"):
            continue
        # Count the MESSAGE, not the record.
        mid = msg.get("id")
        if mid:
            if mid in recent_ids:
                # Refresh on a hit, or the window holds the 512 ids seen FIRST
                # rather than the 512 seen most recently.
                recent_ids.remove(mid)
                recent_ids.append(mid)
                # A re-emission is not a new turn, but it is the newest reading
                # of the same turn's context.
                context = _usage_context(msg) or context
                continue
            recent_ids.append(mid)
            del recent_ids[:-GUARD_RECENT_IDS]
        turns += 1
        context = _usage_context(msg) or context
    return turns, offset + end + 1, agent_type, context


def _guard_stage(turns: int, budget: int) -> int:
    """0 = quiet, 1 = approaching, 2+ = over budget and escalating."""
    if turns >= budget:
        return 2 + (turns - budget) // GUARD_REPEAT_TURNS
    if turns >= int(budget * GUARD_APPROACH_FRACTION):
        return 1
    return 0


def _guard_ctx_stage(context: int, turns: int, bands: tuple[int, int] | None = None) -> int:
    """0 = quiet, 1 = SOFT band, 2+ = HARD band and escalating.

    Escalation is keyed to turns past the breach, not to further token growth: a
    parked agent that stops growing is still spending the HARD band's price on
    every turn it takes.
    """
    soft, hard = bands or guard_ctx_bands(None)
    if context >= hard:
        return 2 + max(0, turns) // GUARD_REPEAT_TURNS
    if context >= soft:
        return 1
    return 0


def _guard_message(
    agent_type: str, turns: int, budget: int, stage: int, generic: bool = False
) -> str:
    if stage == 1:
        tail = (
            GENERIC_REPORT_CLAUSE + " Do it while you still have the turns to write it properly."
            if generic
            else "Reach a clean stopping point and prepare your handoff now, while "
            "you still have the turns to write it properly."
        )
        return f"TURN BUDGET — you are {turns} turns into a {budget}-turn budget. " + tail
    over = turns - budget
    handoff = (
        GENERIC_REPORT_CLAUSE
        if generic
        else f"write the handoff your {agent_type} definition names, and return."
    )
    return (
        f"TURN BUDGET EXCEEDED — {turns} turns against a hard budget of "
        f"{budget} ({over} over). Cost grows with the SQUARE of run length, so "
        "every further turn costs more than the last. Do not push through to a "
        "stopping point that feels tidier. Stop taking on new work now. "
        + (handoff[0].upper() + handoff[1:])
        + " A fresh agent resuming from a good handoff is cheaper and thinks "
        "more clearly than you do here."
    )


def _guard_ctx_message(
    agent_type: str, context: int, turns: int, stage: int, bands: tuple[int, int],
    generic: bool = False,
) -> str:
    soft, hard = bands
    k = f"{context // 1000}k"
    if stage == 1:
        return (
            f"CONTEXT SOFT — you are at {k} against a {soft // 1000}k soft "
            f"band ({turns} turns in). Every turn from here re-reads all {k}. Open no "
            "new threads: finish the unit you are on, then "
            + ("stop. " + GENERIC_REPORT_CLAUSE if generic else "hand off.")
            + " Delegate any further reading to a subagent rather than pulling it in here."
        )
    return (
        f"CONTEXT HARD — you are at {k}, past the "
        f"{hard // 1000}k hard ceiling ({turns} turns in). This is a cost "
        "ceiling, not a capacity one: you may well be able to continue, and doing so "
        "is the expensive mistake. "
        + (
            GENERIC_REPORT_CLAUSE + " Do it mid-unit if necessary."
            if generic
            else f"Commit what is green, write the handoff your {agent_type} "
            "definition names, and return — mid-unit if necessary."
        )
    )


def _guard_lock(state_path: Path):
    """Exclusive lock for one transcript's state. None means: skip this call.

    Non-blocking with a short bounded retry. A hook that waits on a lock adds
    latency to every tool call in the fleet, and skipping is safe: the offset is
    left unadvanced, so the next call counts the same bytes.
    """
    try:
        GUARD_STATE_DIR.mkdir(parents=True, exist_ok=True)
        fh = state_path.with_suffix(".lock").open("a+")
    except OSError:
        return None
    for _ in range(50):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            time.sleep(0.01)
    fh.close()
    return None


def _release_guard_lock(fh) -> None:
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        fh.close()
    except OSError:
        pass


def _write_guard_state(state_path: Path, state: dict) -> None:
    """Atomic, and never fatal. A guard that crashes a run is worse than none."""
    try:
        GUARD_STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, separators=(",", ":")))
        tmp.replace(state_path)
    except OSError:
        pass


def _generic_seat_live(payload: dict) -> bool:
    """Is this generic seat inside a configured repo with a stu run live there?

    No subprocess for the claims: the file is read in process through run_claims, so
    the live rule is the one `run_claims.py list --runs` applies. Imports are lazy so
    stu seats and unrelated payloads never pay for them. Anything that goes wrong,
    SystemExit from run_claims.die() included, answers False: a hook is inert.
    """
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return False
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import run_claims
        import stu_env

        env = stu_env.resolve(cwd=cwd, require_config=True, forge_lookup=False)
        override = os.environ.get("RUN_CLAIMS_FILE")
        # run_claims reads its path from this variable; set it from the resolved
        # RUN_HOME rather than letting it re-resolve from the hook's own cwd.
        os.environ["RUN_CLAIMS_FILE"] = override or os.path.join(
            env["RUN_HOME"], "runs", "claims.tsv"
        )
        return any(
            not run_claims.is_hold(r) and run_claims.is_live(r)
            for r in run_claims.read_rows()
        )
    except BaseException:
        return False


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    # Inert outside our own agents, before any file is touched: the main session
    # has no agent_id, and a non-stu agent type is somebody else's agent -- except
    # a generic seat, which is watched only inside a configured repo with a live run.
    declared = str(payload.get("agent_type") or "")
    if not payload.get("agent_id"):
        return 0
    generic = False
    if declared.startswith(AGENT_PREFIX):
        bare_type = declared[len(AGENT_PREFIX):]
    elif declared in GENERIC_AGENT_BUDGETS:
        if not _generic_seat_live(payload):
            return 0
        generic = True
        bare_type = declared
    else:
        return 0

    transcript = payload.get("transcript_path")
    if not transcript:
        return 0
    path = Path(transcript)
    if not path.exists():
        return 0

    # An agent id keys state directly; without one this is the main thread,
    # which carries no budget but still gets a file so counting stays cheap.
    path = guard_counting_transcript(payload, path)
    state_path = _guard_state_path(str(payload.get("agent_id") or path))

    # Parallel tool calls in one assistant message fire this hook concurrently
    # for the SAME transcript. Unserialised, two invocations read the same
    # `warned` stage and both emit the one-time warning, and the later write
    # discards the earlier one's offset. The lock is a separate file because
    # the state file is replaced by rename, which would detach a lock held on it.
    lock = _guard_lock(state_path)
    if lock is None:
        return 0
    try:
        state: dict = {}
        try:
            state = json.loads(state_path.read_text())
        except (OSError, json.JSONDecodeError):
            state = {}

        agent_type = bare_type
        offset = int(state.get("offset") or 0)
        turns = int(state.get("turns") or 0)
        warned = int(state.get("warned") or 0)
        context = int(state.get("context") or 0)
        ctx_warned = int(state.get("ctx_warned") or 0)
        ctx_breach_turns = int(state.get("ctx_breach_turns") or 0)
        recent_ids = [str(x) for x in (state.get("recent_ids") or [])]

        new_turns, new_offset, seen_type, new_ctx = _count_turns_since(
            path, offset, recent_ids
        )
        turns += new_turns
        agent_type = agent_type or seen_type
        # No billed turn in these bytes means no fresh reading, not a small one.
        context = new_ctx or context

        budgets = GENERIC_AGENT_BUDGETS if generic else AGENT_TURN_BUDGETS
        watched = (agent_type or "") in budgets
        budget = budgets.get(agent_type or "")
        stage = _guard_stage(turns, budget) if budget else 0
        bands = guard_ctx_bands(agent_type)
        if watched and context >= bands[1]:
            ctx_breach_turns += new_turns
        ctx_stage = _guard_ctx_stage(context, ctx_breach_turns, bands) if watched else 0

        # Both axes are live; whichever escalated first this call speaks. Turns
        # win a tie because a thrashing agent's context is a symptom of it.
        fire_turns = bool(budget) and stage > warned
        fire_ctx = watched and not fire_turns and ctx_stage > ctx_warned

        _write_guard_state(
            state_path,
            {
                "agent_type": agent_type,
                "offset": new_offset,
                "turns": turns,
                "warned": stage if fire_turns else warned,
                "context": context,
                "ctx_warned": ctx_stage if fire_ctx else ctx_warned,
                "ctx_breach_turns": ctx_breach_turns,
                "recent_ids": recent_ids[-GUARD_RECENT_IDS:],
            },
        )
    finally:
        _release_guard_lock(lock)

    message = None
    if fire_turns:
        message = _guard_message(agent_type or "agent", turns, budget, stage, generic)
    elif fire_ctx:
        message = _guard_ctx_message(
            agent_type or "agent", context, turns, ctx_stage,
            guard_ctx_bands(agent_type), generic,
        )

    if message:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": message,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
