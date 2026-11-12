#!/usr/bin/env python3
"""Regression suite for fleet_actuals.py. Fixtures are hand-written JSONL in a temp projects root
(STU_PROJECTS_ROOT); nothing reads a real transcript. Run: python3 scripts/fleet_actuals_test.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fleet_actuals  # noqa: E402

FAILURES = []
COUNT = [0]


def check(name, got, want):
    COUNT[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


def asst(rid, model, out, mid=None):
    return {"type": "assistant", "requestId": rid,
            "message": {"id": mid or "m-" + rid, "model": model, "role": "assistant",
                        "usage": {"input_tokens": 1, "output_tokens": out}}}


def agent(root, project, session, aid, seat, parent=None, nonce=None, records=()):
    sdir = os.path.join(root, project, session, "subagents")
    os.makedirs(sdir, exist_ok=True)
    meta = {"agentType": seat, "spawnDepth": 1, "finished": True}
    if parent:
        meta["parentAgentId"] = parent
    with open(os.path.join(sdir, "agent-%s.meta.json" % aid), "w") as f:
        json.dump(meta, f)
    first = {"type": "user", "message": {"role": "user", "content": "go\n" + (
        "STU-SUPERVISED: %s\n" % nonce if nonce else "")}}
    with open(os.path.join(sdir, "agent-%s.jsonl" % aid), "w") as f:
        for r in [first] + list(records):
            f.write(json.dumps(r) + "\n")


def main():
    root = tempfile.mkdtemp(prefix="stu-actuals-test-")
    os.environ["STU_PROJECTS_ROOT"] = root
    S, I, R = "claude-sonnet-x", "claude-opus-x", None
    # session one: a supervisor, an implementer split across records, a reviewer two levels down
    agent(root, "p1", "sess1", "sup1", "stu:supervisor", nonce="stu-nonce-one",
          records=[asst("r1", I, 10), asst("r2", I, 5)])
    agent(root, "p1", "sess1", "imp1", "stu:implementer", parent="sup1", records=[
        asst("q1", S, 3), asst("q1", S, 40), asst("q1", S, 12),   # one response, three records
        asst("q2", S, 7), asst("q3", I, 100), {"type": "user", "message": {"content": "x"}}])
    agent(root, "p1", "sess1", "rev1", "stu:reviewer", parent="imp1", records=[asst("t1", S, 9)])
    agent(root, "p1", "sess1", "other", "stu:scout", records=[asst("z1", S, 999)])  # not in the tree
    got, why = fleet_actuals.launch_actuals("stu-nonce-one")
    check("available", why, None)
    rows = {a["id"]: a for a in got["agents"]}
    check("tree is root, child, grandchild, never the stranger", [a["id"] for a in got["agents"]],
          ["sup1", "imp1", "rev1"])
    check("seat is agentType, supervisor included", {k: v["seat"] for k, v in rows.items()},
          {"sup1": "stu:supervisor", "imp1": "stu:implementer", "rev1": "stu:reviewer"})
    check("split records count once at the largest output", rows["imp1"]["models"][S],
          {"turns": 2, "out": 47})
    check("a second model is its own row", rows["imp1"]["models"][I], {"turns": 1, "out": 100})
    check("two levels deep", rows["rev1"]["models"], {S: {"turns": 1, "out": 9}})
    check("supervisor own turns", rows["sup1"]["models"], {I: {"turns": 2, "out": 15}})
    check("totals", fleet_actuals.totals(got), (3, 171))
    check("by seat and model", fleet_actuals.by_seat_model(got), [
        {"seat": "stu:implementer", "model": I, "agents": 1, "turns": 1, "out": 100},
        {"seat": "stu:implementer", "model": S, "agents": 1, "turns": 2, "out": 47},
        {"seat": "stu:reviewer", "model": S, "agents": 1, "turns": 1, "out": 9},
        {"seat": "stu:supervisor", "model": I, "agents": 1, "turns": 2, "out": 15}])
    # a supervisor in another session than the tree's consumer: found by nonce under any project
    agent(root, "p2", "sess2", "sup2", "stu:supervisor", nonce="stu-nonce-two",
          records=[asst("a", S, 4)])
    agent(root, "p2", "sess2", "imp2", "stu:implementer", parent="sup2", records=[asst("b", S, 6)])
    got, why = fleet_actuals.launch_actuals("stu-nonce-two")
    check("nonce in another session", (why, fleet_actuals.totals(got)), (None, (2, 10)))
    # missing, ambiguous, malformed
    got, why = fleet_actuals.launch_actuals("stu-nonce-absent")
    check("missing nonce", (got, "no agent file" in why), (None, True))
    agent(root, "p3", "sess3", "dup", "stu:supervisor", nonce="stu-nonce-one")
    got, why = fleet_actuals.launch_actuals("stu-nonce-one")
    check("ambiguous nonce is unavailable, never a guess", (got, "ambiguous" in why), (None, True))
    got, why = fleet_actuals.launch_actuals("none")
    check("no nonce", (got, bool(why)), (None, True))
    # an agent with no meta agentType and a damaged line still counts
    agent(root, "p4", "sess4", "sup4", None, nonce="stu-nonce-four", records=[asst("a", S, 2)])
    with open(os.path.join(root, "p4", "sess4", "subagents", "agent-sup4.jsonl"), "a") as f:
        f.write('{"output_tokens" broken\n')
    got, why = fleet_actuals.launch_actuals("stu-nonce-four")
    check("unknown seat, damaged line skipped", (why, got["agents"][0]["seat"], fleet_actuals.totals(got)),
          (None, "unknown", (1, 2)))
    # synthetic placeholders are skipped; a record with no model counts under unknown
    nomodel = asst("n1", S, 6)
    del nomodel["message"]["model"]
    agent(root, "p5", "sess5", "sup5", "stu:supervisor", nonce="stu-nonce-five", records=[
        asst("y1", "<synthetic>", 50), asst("y2", S, 3), nomodel])
    got, why = fleet_actuals.launch_actuals("stu-nonce-five")
    check("synthetic skipped, no model is unknown", (why, got["agents"][0]["models"]), (
        None, {S: {"turns": 1, "out": 3}, "unknown": {"turns": 1, "out": 6}}))
    if FAILURES:
        print("FAIL %d of %d checks" % (len(FAILURES), COUNT[0]))
        for f in FAILURES:
            print("  " + f)
        return 1
    print("ok: %d checks" % COUNT[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
