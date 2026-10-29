#!/usr/bin/env python3
"""Regression suite for turn-guard.py's two axes.

The guard is worth nothing unless each axis fires on its OWN failure: a context
breach inside the turn bar, and a turn breach at small context. Every check below
that asserts "fires" has a sibling that asserts silence, because a guard that
warns unconditionally would pass a one-sided suite.

Run: python3 scripts/turn_guard_test.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "turn-guard.py")

spec = importlib.util.spec_from_file_location("turn_guard", GUARD)
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)

FAILURES = []

# Read the bar rather than restating it. A hardcoded 105 here passed silently once
# the implementer's budget moved, which is the drift this suite exists to catch.
# Resolve by suffix, so the suite still passes if the table's keys carry a prefix.


def budgeted(suffix):
    for name in tg.AGENT_TURN_BUDGETS:
        if name == suffix or name.endswith("-" + suffix):
            return name
    raise AssertionError(
        "no budget row ending in %r; table has %s"
        % (suffix, sorted(tg.AGENT_TURN_BUDGETS))
    )


def unbudgeted(suffix):
    """A prefixed name matching no budget row, whatever the install prefix is."""
    impl = budgeted("implementer")
    prefix = impl[: -len("implementer")]
    return prefix + suffix


IMPL = budgeted("implementer")
ORCH = budgeted("orchestrator")
IMPL_BUDGET = tg.AGENT_TURN_BUDGETS[IMPL]
OVER_BUDGET = IMPL_BUDGET + 5
SCOUT = unbudgeted("scout")
assert SCOUT not in tg.AGENT_TURN_BUDGETS


CHECKS = [0]


def check(name, got, want):
    CHECKS[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


def transcript(path, turns, context, agent_type=None):
    """A transcript of `turns` billed assistant turns, each at `context` tokens."""
    agent_type = IMPL if agent_type is None else agent_type
    with open(path, "w") as fh:
        for i in range(turns):
            fh.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "attributionAgent": agent_type,
                        "message": {
                            "id": "msg_%d" % i,
                            "usage": {
                                "input_tokens": 10,
                                "cache_creation_input_tokens": 100,
                                "cache_read_input_tokens": context - 110,
                            },
                        },
                    }
                )
                + "\n"
            )


def run(path, agent_type, env=None, raw=False, cwd=None):
    """Fire the hook once. Returns the additionalContext string, or ''.

    State is keyed by agent id, so each check needs its own or it inherits the
    previous one's turn count and warn stage -- which silently makes some checks
    pass for the wrong reason. Keyed off the transcript name: one file per check.
    """
    e = dict(os.environ)
    e["RUN_TURN_GUARD_DIR"] = os.path.join(os.path.dirname(path), "state")
    e.update(env or {})
    agent_id = "agent-" + os.path.basename(path).split(".")[0]
    # Plugin agents are namespaced ("stu:"-prefixed); generic seats arrive unprefixed.
    # `raw` sends agent_type verbatim, for the checks that probe the prefix gate.
    sent = agent_type if raw else tg.AGENT_PREFIX + agent_type
    payload = {"transcript_path": path, "agent_type": sent, "agent_id": agent_id}
    if cwd:
        payload["cwd"] = cwd  # the payload field, not the subprocess cwd
    out = subprocess.run(
        [sys.executable, GUARD], input=json.dumps(payload), capture_output=True,
        text=True, env=e,
    )
    check("exit code is always 0 (" + agent_type + ")", out.returncode, 0)
    if not out.stdout.strip():
        return ""
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


# --- unit: the context reading is the sum ctx.py uses ---------------------------
check(
    "context sums all three fields",
    tg._usage_context(
        {"usage": {"input_tokens": 5, "cache_creation_input_tokens": 50,
                   "cache_read_input_tokens": 1000}}
    ),
    1055,
)
check("no usage reads 0, not a crash", tg._usage_context({}), 0)

# --- unit: the two stage functions are independent ------------------------------
check("turns quiet below approach", tg._guard_stage(50, 100), 0)
check("turns warn at 85% of budget", tg._guard_stage(85, 100), 1)
check("turns exceed at budget", tg._guard_stage(100, 100), 2)
check("context quiet below SOFT", tg._guard_ctx_stage(120_000, 0), 0)
check("context SOFT at 160k", tg._guard_ctx_stage(160_000, 0), 1)
check("context HARD at 200k", tg._guard_ctx_stage(200_000, 0), 2)
check("context HARD escalates on turns past it", tg._guard_ctx_stage(210_000, 25), 3)

# --- unit: the per-agent band table (the decision) --------------------------------
# Bands are read from the table by name, then pinned to the numbers the unit chose.
# RUN_CTX_* is cleared so an exported override cannot make these pass or fail.
for _k in ("RUN_CTX_SOFT", "RUN_CTX_HARD"):
    os.environ.pop(_k, None)
check("orchestrator bands", tg.guard_ctx_bands(ORCH), (120_000, 160_000))
check("implementer bands", tg.guard_ctx_bands(IMPL), (150_000, 190_000))
check("unknown agent keeps the fleet pair", tg.guard_ctx_bands(SCOUT), (160_000, 200_000))
check("no agent type keeps the fleet pair", tg.guard_ctx_bands(None), (160_000, 200_000))
check("orchestrator SOFT at 120k, not before",
      (tg._guard_ctx_stage(119_999, 0, tg.guard_ctx_bands(ORCH)),
       tg._guard_ctx_stage(120_000, 0, tg.guard_ctx_bands(ORCH))), (0, 1))
check("implementer quiet at 150k-minus, SOFT at 150k",
      (tg._guard_ctx_stage(149_999, 0, tg.guard_ctx_bands(IMPL)),
       tg._guard_ctx_stage(150_000, 0, tg.guard_ctx_bands(IMPL))), (0, 1))
check("implementer HARD at 190k",
      tg._guard_ctx_stage(190_000, 0, tg.guard_ctx_bands(IMPL)), 2)
os.environ["RUN_CTX_SOFT"] = "300000"
os.environ["RUN_CTX_HARD"] = "400000"
check("env override wins over a table row",
      (tg.guard_ctx_bands(ORCH), tg.guard_ctx_bands(IMPL)),
      ((300_000, 400_000), (300_000, 400_000)))
for _k in ("RUN_CTX_SOFT", "RUN_CTX_HARD"):
    del os.environ[_k]

# --- end to end, through the hook ----------------------------------------------
with tempfile.TemporaryDirectory() as d:
    # 1. Small and short: silent. If this one talks, nothing below means anything.
    p = os.path.join(d, "a.jsonl")
    transcript(p, turns=20, context=90_000)
    check("quiet run says nothing", run(p, IMPL), "")

    # 2. A context breach INSIDE the turn bar -- the case the turn-only guard
    #    passed, and the reason this axis exists. 40 turns of a 100 budget.
    p = os.path.join(d, "b.jsonl")
    transcript(p, turns=40, context=210_000)
    msg = run(p, IMPL)
    check("context breach inside the turn bar fires", msg.split(" —")[0], "CONTEXT HARD")
    check("and it reports the size", "210k" in msg, True)

    # 3. MUTATION: same transcript, ceiling raised past it. Must go silent --
    #    otherwise check 2 was passing on something other than the threshold.
    p = os.path.join(d, "c.jsonl")
    transcript(p, turns=40, context=210_000)
    check(
        "same run is silent when the ceiling is above it",
        run(p, IMPL, {"RUN_CTX_SOFT": "500000", "RUN_CTX_HARD": "900000"}),
        "",
    )

    # 4. A turn breach at SMALL context -- the mirror case, and the one shape the
    #    context axis cannot see (a long run of small reads).
    p = os.path.join(d, "d.jsonl")
    transcript(p, turns=OVER_BUDGET, context=90_000)
    msg = run(p, IMPL)
    check("turn breach at small context fires", msg.split(" —")[0], "TURN BUDGET EXCEEDED")

    # 4b. And a run just UNDER the turn bar at small context stays silent, or check 4
    #     would pass on any long-ish run rather than on the bar.
    p = os.path.join(d, "d2.jsonl")
    transcript(p, turns=int(IMPL_BUDGET * 0.8), context=90_000)
    check("under both bars stays silent", run(p, IMPL), "")

    # 5. Both breached: turns speak, context waits its turn.
    p = os.path.join(d, "e.jsonl")
    transcript(p, turns=OVER_BUDGET, context=210_000)
    check("turns win the tie", run(p, IMPL).split(" —")[0],
          "TURN BUDGET EXCEEDED")

    # 6. An agent with no row in the table is watched on neither axis.
    p = os.path.join(d, "f.jsonl")
    transcript(p, turns=OVER_BUDGET, context=210_000, agent_type=SCOUT)
    check("unbudgeted agent stays silent", run(p, SCOUT), "")

    # 7. One warning per stage: the second identical call says nothing.
    p = os.path.join(d, "g.jsonl")
    transcript(p, turns=40, context=210_000)
    first = run(p, IMPL)
    check("first call warns", first.startswith("CONTEXT HARD"), True)
    check("second call does not repeat it", run(p, IMPL), "")

# --- end to end: the new bands, through the hook ---------------------------------
with tempfile.TemporaryDirectory() as d:
    # An orchestrator at 125k now speaks; at the old fleet band it was silent.
    p = os.path.join(d, "o1.jsonl")
    transcript(p, turns=30, context=125_000, agent_type=ORCH)
    check("orchestrator at 125k fires SOFT",
          run(p, ORCH).split(" —")[0], "CONTEXT SOFT")
    p = os.path.join(d, "o2.jsonl")
    transcript(p, turns=30, context=115_000, agent_type=ORCH)
    check("orchestrator at 115k stays silent", run(p, ORCH), "")
    p = os.path.join(d, "o3.jsonl")
    transcript(p, turns=30, context=165_000, agent_type=ORCH)
    check("orchestrator at 165k fires HARD",
          run(p, ORCH).split(" —")[0], "CONTEXT HARD")
    # An implementer just under 150k stays silent; at 155k it speaks SOFT, and its
    # message names the 150k band rather than the fleet 160k.
    p = os.path.join(d, "i1.jsonl")
    transcript(p, turns=30, context=149_000)
    check("implementer at 149k stays silent", run(p, IMPL), "")
    p = os.path.join(d, "i2.jsonl")
    transcript(p, turns=30, context=155_000)
    msg = run(p, IMPL)
    check("implementer at 155k fires SOFT", msg.split(" —")[0], "CONTEXT SOFT")
    check("and names its own 150k band", "150k soft" in msg, True)
    # An implementer at 195k is past its 190k hard band (past the old 160k soft only).
    p = os.path.join(d, "i3.jsonl")
    transcript(p, turns=30, context=195_000)
    check("implementer at 195k fires HARD", run(p, IMPL).split(" —")[0], "CONTEXT HARD")
    # Env override beats the orchestrator row through the hook.
    p = os.path.join(d, "o4.jsonl")
    transcript(p, turns=30, context=125_000, agent_type=ORCH)
    check("env override silences orchestrator 125k",
          run(p, ORCH, {"RUN_CTX_SOFT": "500000", "RUN_CTX_HARD": "900000"}), "")

# --- the plugin gate: the hook fires in EVERY session, so it must stay inert ------
with tempfile.TemporaryDirectory() as d:
    state = os.path.join(d, "state")

    def fire(payload):
        e = dict(os.environ)
        e["RUN_TURN_GUARD_DIR"] = state
        out = subprocess.run([sys.executable, GUARD], input=json.dumps(payload),
                             capture_output=True, text=True, env=e)
        check("gate exit code is 0", out.returncode, 0)
        return out.stdout.strip()

    def state_files():
        return sorted(os.listdir(state)) if os.path.isdir(state) else []

    # test_plugin_prefixed_orchestrator_watched
    p = os.path.join(d, "pp.jsonl")
    transcript(p, turns=tg.AGENT_TURN_BUDGETS["orchestrator"], context=50_000,
               agent_type="orchestrator")
    out = fire({"transcript_path": p, "agent_type": "stu:orchestrator", "agent_id": "pp"})
    check("plugin-prefixed orchestrator watched",
          "120-turn budget" in out or "hard budget of 120" in out, True)

    # test_unprefixed_orchestrator_ignored
    state = os.path.join(d, "state2")
    p = os.path.join(d, "up.jsonl")
    transcript(p, turns=300, context=50_000, agent_type="orchestrator")
    out = fire({"transcript_path": p, "agent_type": "orchestrator", "agent_id": "up"})
    check("unprefixed orchestrator: no output", out, "")
    check("unprefixed orchestrator: no state file", state_files(), [])

    # test_main_session_fast_exit: no agent_id, transcript that does not exist
    state = os.path.join(d, "state3")
    out = fire({"transcript_path": os.path.join(d, "missing.jsonl")})
    check("main session: no output", out, "")
    check("main session: no state file", state_files(), [])
    out = fire({"transcript_path": os.path.join(d, "missing.jsonl"),
                "agent_type": "stu:orchestrator"})
    check("no agent_id even with stu: type: no state", (out, state_files()), ("", []))

    # state directory resolution
    check("plugin data dir wins", str(tg.guard_state_dir({"CLAUDE_PLUGIN_DATA": "/x"})),
          "/x/turn-guard")
    check("fallback is under ~/.stu", str(tg.guard_state_dir({})),
          os.path.join(os.path.expanduser("~"), ".stu", ".turn-guard"))
    check("RUN_TURN_GUARD_DIR overrides",
          str(tg.guard_state_dir({"RUN_TURN_GUARD_DIR": "/y", "CLAUDE_PLUGIN_DATA": "/x"})),
          "/y")

# --- generic seats (general-purpose, fork) inside a configured repo -----------------
import datetime

CLAUSE = "Write what you did and what is left in your report, then return."
STAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"


def stamp(hours_ago):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)
    return t.strftime(STAMP_FMT)


def make_world(d, claims=None, configured=True, sub=""):
    """A git repo (+ config naming a RUN_HOME) and an optional claims file.

    Returns (repo, env). `claims` is a list of rows; None writes no file.
    """
    d = os.path.join(d, sub)
    os.makedirs(d, exist_ok=True)
    repo = os.path.join(d, "repo")
    home = os.path.join(d, "home")
    subprocess.run(["git", "init", "-q", repo], check=True)
    env = {"HOME": os.path.join(d, "fakehome"), "RUN_TURN_GUARD_DIR": os.path.join(d, "st")}
    if configured:
        cfg = os.path.join(d, "stu.md")
        with open(cfg, "w") as fh:
            fh.write("---\nrun_home: %s\ngithub_repo: acme/app\n---\n" % home)
        env["STU_CONFIG"] = cfg
    else:
        env["STU_CONFIG"] = os.path.join(d, "absent.md")
    if claims is not None:
        os.makedirs(os.path.join(home, "runs"))
        with open(os.path.join(home, "runs", "claims.tsv"), "w") as fh:
            for r in claims:
                fh.write("\t".join(r) + "\n")
    return repo, env


def live_rows():
    return [["unit1", "run1", "sess1", stamp(0.1)]]


def generic(d, name, kind, turns, context, repo, env, claims_env=None):
    p = os.path.join(d, name + ".jsonl")
    transcript(p, turns=turns, context=context, agent_type=kind)
    e = dict(env)
    e.update(claims_env or {})
    return p, run(p, kind, e, raw=True, cwd=repo)


def state_count(env):
    sd = env["RUN_TURN_GUARD_DIR"]
    return sorted(os.listdir(sd)) if os.path.isdir(sd) else []


check("generic table", tg.GENERIC_AGENT_BUDGETS, {"general-purpose": 140, "fork": 140})
with tempfile.TemporaryDirectory() as d:
    repo, env = make_world(d, live_rows())
    _, msg = generic(d, "g1", "general-purpose", 145, 90_000, repo, env)
    check("generic_seat_in_family_fires", msg.split(" -- ")[0].split(" —")[0], "TURN BUDGET EXCEEDED")
    check("generic budget is 140", "against a hard budget of 140" in msg, True)
    _, msg = generic(d, "g1f", "fork", 145, 90_000, repo, env)
    check("fork seat fires too", msg.split(" —")[0], "TURN BUDGET EXCEEDED")
    check("turn message carries the clause", CLAUSE in msg, True)
    check("turn message drops the definition wording", "definition names" in msg, False)
    _, msg = generic(d, "g1s", "general-purpose", 125, 90_000, repo, env)
    check("approach message carries the clause", (CLAUSE in msg, msg.split(" —")[0]),
          (True, "TURN BUDGET"))
    # 125 of 140 is past 85% and under the budget: stage 1.
    _, msg = generic(d, "g1c", "general-purpose", 30, 210_000, repo, env)
    check("ctx HARD message carries the clause",
          (msg.split(" —")[0], CLAUSE in msg, "definition names" in msg),
          ("CONTEXT HARD", True, False))
    _, msg = generic(d, "g1d", "general-purpose", 30, 170_000, repo, env)
    check("ctx SOFT message carries the clause",
          (msg.split(" —")[0], CLAUSE in msg), ("CONTEXT SOFT", True))
    # stu seats keep their wording
    p = os.path.join(d, "g1stu.jsonl")
    transcript(p, turns=OVER_BUDGET, context=90_000)
    msg = run(p, IMPL, env, cwd=repo)
    check("stu seat message unchanged", ("definition names" in msg, CLAUSE in msg), (True, False))

with tempfile.TemporaryDirectory() as d:
    repo, env = make_world(d, live_rows())
    _, msg = generic(d, "b1", "general-purpose", 30, 155_000, repo, env)
    check("generic_seat_gets_fleet_bands: 155k silent", msg, "")
    _, msg = generic(d, "b2", "general-purpose", 30, 205_000, repo, env)
    check("generic_seat_gets_fleet_bands: 205k fires", msg.split(" —")[0], "CONTEXT HARD")
    _, msg = generic(d, "b3", "general-purpose", 100, 90_000, repo, env)
    check("generic seat under the approach line is silent", msg, "")

with tempfile.TemporaryDirectory() as d:
    nrepo, nenv = make_world(d, live_rows(), configured=False)
    _, msg = generic(d, "o1", "general-purpose", 145, 210_000, nrepo, nenv)
    check("generic_seat_outside_family_silent", (msg, state_count(nenv)), ("", []))

with tempfile.TemporaryDirectory() as d:
    repo, env = make_world(d, live_rows())
    _, msg = generic(d, "n1", "general-purpose", 145, 210_000, None, env)
    check("generic seat with no payload cwd is inert", (msg, state_count(env)), ("", []))
    for kind in ("Explore", "Plan", "claude"):
        _, msg = generic(d, "x" + kind, kind, 145, 210_000, repo, env)
        check("non-table type %s is silent with a live run" % kind,
              (msg, state_count(env)), ("", []))

with tempfile.TemporaryDirectory() as d:
    repo, env = make_world(d, None)
    _, msg = generic(d, "l1", "general-purpose", 145, 210_000, repo, env)
    check("generic_seat_without_live_run_silent: no file", (msg, state_count(env)), ("", []))
with tempfile.TemporaryDirectory() as d:
    repo, env = make_world(d, [["unit1", "run1", "sess1", stamp(20)]])
    _, msg = generic(d, "l2", "general-purpose", 145, 210_000, repo, env)
    check("generic_seat_without_live_run_silent: only stale", (msg, state_count(env)), ("", []))
    # the same world with a fresh claim fires: the stale check is what silenced it
    repo2, env2 = make_world(d,
                             [["unit1", "run1", "sess1", stamp(20)], ["unit2", "run2", "s", stamp(0.1)]], sub="w2")
    _, msg = generic(d, "l3", "general-purpose", 145, 90_000, repo2, env2)
    check("a fresh claim beside a stale one fires", msg.split(" —")[0], "TURN BUDGET EXCEEDED")
with tempfile.TemporaryDirectory() as d:
    repo, env = make_world(d, [["unit1", "run1", "sess1", stamp(0.1), "hold"],
                                ["unit2", "run1", "sess1", stamp(30), "hold"]])
    _, msg = generic(d, "h1", "general-purpose", 145, 210_000, repo, env)
    check("generic_seat_with_only_holds_silent", (msg, state_count(env)), ("", []))
with tempfile.TemporaryDirectory() as d:
    repo, env = make_world(d, live_rows())
    _, msg = generic(d, "e1", "general-purpose", 145, 90_000, repo, env,
                     {"RUN_CLAIM_STALE_HOURS": "bogus"})
    check("bad RUN_CLAIM_STALE_HOURS is inert", (msg, state_count(env)), ("", []))
    # RUN_CLAIMS_FILE is honoured once resolve succeeds
    alt = os.path.join(d, "alt.tsv")
    with open(alt, "w") as fh:
        fh.write("\t".join(live_rows()[0]) + "\n")
    repo3, env3 = make_world(d, None, sub="w3")
    _, msg = generic(d, "e2", "general-purpose", 145, 90_000, repo3, env3,
                     {"RUN_CLAIMS_FILE": alt})
    check("RUN_CLAIMS_FILE override is honoured", msg.split(" —")[0], "TURN BUDGET EXCEEDED")

# generic_seat_resolve_systemexit_is_inert: in process, so resolve can be made to raise.
with tempfile.TemporaryDirectory() as d:
    import io
    repo, env = make_world(d, live_rows())
    p = os.path.join(d, "se.jsonl")
    transcript(p, turns=145, context=210_000, agent_type="general-purpose")
    sys.path.insert(0, HERE)
    import stu_env

    def boom(*a, **k):
        raise SystemExit(2)

    payload = json.dumps({"transcript_path": p, "agent_type": "general-purpose",
                          "agent_id": "agent-se", "cwd": repo})
    saved = (stu_env.resolve, sys.stdin, sys.stdout, tg.GUARD_STATE_DIR)
    saved_env = {k: os.environ.get(k) for k in ("STU_CONFIG", "RUN_TURN_GUARD_DIR")}
    tg.GUARD_STATE_DIR = type(tg.GUARD_STATE_DIR)(env["RUN_TURN_GUARD_DIR"])
    os.environ["STU_CONFIG"] = env["STU_CONFIG"]
    buf = io.StringIO()
    rc = out = None
    try:
        stu_env.resolve = boom
        sys.stdin, sys.stdout = io.StringIO(payload), buf
        try:
            rc = tg.main()
        except SystemExit as exc:  # the catch must not let this out of the hook
            rc = "escaped SystemExit(%s)" % exc.code
    finally:
        stu_env.resolve, sys.stdin, sys.stdout, tg.GUARD_STATE_DIR = saved
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check("generic_seat_resolve_systemexit_is_inert",
          (rc, buf.getvalue(), state_count(env)), (0, "", []))
    # control: unpatched, the same in-process call fires, so the silence above is the catch
    tg.GUARD_STATE_DIR = type(tg.GUARD_STATE_DIR)(env["RUN_TURN_GUARD_DIR"])
    os.environ["STU_CONFIG"] = env["STU_CONFIG"]
    buf = io.StringIO()
    saved2 = (sys.stdin, sys.stdout)
    try:
        sys.stdin, sys.stdout = io.StringIO(payload), buf
        rc = tg.main()
    finally:
        sys.stdin, sys.stdout = saved2
        os.environ.pop("STU_CONFIG", None)
    check("in-process control fires", "TURN BUDGET" in buf.getvalue(), True)


if FAILURES:
    print("turn_guard_test: %d FAILED" % len(FAILURES))
    for f in FAILURES:
        print("  - " + f)
    sys.exit(1)
print("turn_guard_test: all %d checks passed" % CHECKS[0])
