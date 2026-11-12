#!/usr/bin/env python3
"""fleet_actuals: what one supervisor launch actually used, read from the agent transcripts.

  launch_actuals(nonce) -> (actuals, None) | (None, reason)

The supervisor is the one agent whose first record carries `STU-SUPERVISED: <nonce>`, looked for
in every session under the projects root (a coordinator that took over after a handoff runs in a
different session from the supervisors it inherited). Zero or several matches is unavailable,
never a guess. Its tree is the supervisor plus every agent whose `parentAgentId` chain reaches it
(agent_tree.walk). The result:

  {"agents": [{"id": ..., "seat": <meta agentType, "unknown" if absent>,
               "models": {<model>: {"turns": n, "out": n}}}, ...]}   (supervisor first)

One API response can be split over several assistant records sharing a `requestId`; each
`requestId` counts once, as the record with the largest `output_tokens`, and is one turn. A
record with no `requestId` falls back to `message.id`, then counts alone.

Projects root: agent_tree.projects_root() (STU_PROJECTS_ROOT in tests). Standard library only.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_tree  # noqa: E402


def agent_turns(path):
    """-> {model: {"turns": n, "out": n}} for one agent file."""
    best = {}  # key -> (output_tokens, model)
    try:
        fh = open(path, "r", errors="replace")
    except OSError:
        return {}
    with fh:
        for i, line in enumerate(fh):
            if '"output_tokens"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("type") != "assistant":
                continue
            m = d.get("message")
            if not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
                continue
            out = m["usage"].get("output_tokens")
            if not isinstance(out, int) or isinstance(out, bool):
                continue
            key = d.get("requestId") or m.get("id") or ("line-%d" % i)
            if key not in best or out > best[key][0]:
                best[key] = (out, m.get("model") or "unknown")
    models = {}
    for out, model in best.values():
        e = models.setdefault(model, {"turns": 0, "out": 0})
        e["turns"] += 1
        e["out"] += out
    return models


def find_supervisor(nonce):
    """-> (subagents dir, agent id). Raises agent_tree.NotFound unless exactly one agent matches."""
    if not nonce or not agent_tree.NONCE_RE.match(nonce):
        raise agent_tree.NotFound("no usable launch nonce on the board line")
    hits = []
    for sdir in sorted(glob.glob(os.path.join(agent_tree.projects_root(), "*", "*", "subagents"))):
        hits += [(sdir, agent_tree.agent_id(p)) for p in agent_tree.nonce_hits(sdir, nonce)]
    if not hits:
        raise agent_tree.NotFound("no agent file under %s has the nonce line %s" % (
            agent_tree.projects_root(), nonce))
    if len(hits) > 1:
        raise agent_tree.NotFound("ambiguous: %d agent files carry the nonce line %s" % (
            len(hits), nonce))
    return hits[0]


def launch_actuals(nonce):
    try:
        sdir, root = find_supervisor(nonce)
        agents = agent_tree.load_agents(sdir)
        rows = []
        for aid in agent_tree.walk(agents, root):
            meta = agents[aid]["meta"]
            seat = meta.get("agentType")
            rows.append({"id": aid, "seat": seat if isinstance(seat, str) and seat else "unknown",
                         "models": agent_turns(agents[aid]["jsonl"])})
        return {"agents": rows}, None
    except agent_tree.NotFound as e:
        return None, str(e)
    except Exception as e:  # a transcript problem must never block recording a return
        return None, "%s: %s" % (type(e).__name__, e)


def totals(actuals):
    """-> (agent count, output tokens)."""
    return len(actuals["agents"]), sum(m["out"] for a in actuals["agents"]
                                       for m in a["models"].values())


def by_seat_model(actuals):
    """-> [{seat, model, agents, turns, out}] sorted by seat then model."""
    acc = {}
    for a in actuals["agents"]:
        for model, v in a["models"].items():
            e = acc.setdefault((a["seat"], model), {"agents": 0, "turns": 0, "out": 0})
            e["agents"] += 1
            e["turns"] += v["turns"]
            e["out"] += v["out"]
    return [dict(seat=s, model=m, **v) for (s, m), v in sorted(acc.items())]
