#!/usr/bin/env python3
"""stu-tree: which agents under this session are still running, and who owns the agent file.

  stu-tree --root <agent-id> [--session <id>]
  stu-tree --nonce <nonce>   [--session <id>]     (root = the agent whose prompt carries it)
  stu-tree                   [--session <id>]     (every agent of the session)

Reads `<projects root>/*/<session>/subagents/agent-*.meta.json` and the matching `.jsonl`.
`ListAgents` does not exist inside a subagent; this is the one way a supervisor or a
coordinator decides liveness (docs/design-rationale.md, "Fleet nesting spike", change 1).

One line per agent (the root first, then its descendants by `parentAgentId`):
    <agent-id> depth=<spawnDepth> state=live|finished last-write=<seconds>s
An agent is `finished` only when its meta file says `finished: true`. A status of
`completed` is never read: a supervisor shows it while it waits on its timer.

Exit 0 if any listed agent (the root included) is live, 1 if none is, 2 on a usage error,
3 when the session or the root is not found. The session defaults to
CLAUDE_CODE_SESSION_ID; the projects root to ~/.claude/projects, overridable with
STU_PROJECTS_ROOT (tests).

`find_by_nonce` is shared with ctx.py: the launcher puts a `STU-SUPERVISED: <nonce>` or
`STU-NONCE: <nonce>` line in an agent's prompt, and the one agent file whose first record holds
that line is that agent's. Zero or several matches is an error, never a guess.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

NONCE_RE = re.compile(r"^[A-Za-z0-9._-]{6,80}$")


class NotFound(Exception):
    """Session, agent or nonce could not be resolved to exactly one thing."""


def projects_root():
    return os.environ.get("STU_PROJECTS_ROOT") or os.path.expanduser("~/.claude/projects")


def subagents_dir(session):
    if not session:
        raise NotFound("no session: pass --session or set CLAUDE_CODE_SESSION_ID")
    hits = [d for d in glob.glob(os.path.join(projects_root(), "*", session))
            if os.path.isdir(d)]
    if not hits:
        raise NotFound("no session directory for %s under %s" % (session, projects_root()))
    if len(hits) > 1:
        raise NotFound("ambiguous: %d session directories match %s" % (len(hits), session))
    return os.path.join(hits[0], "subagents")


def agent_id(path):
    base = os.path.basename(path)
    return base[len("agent-"):base.index(".")]


def load_agents(sdir):
    """-> {agent id: {"meta": dict, "jsonl": path}} for every agent-*.meta.json."""
    agents = {}
    for m in sorted(glob.glob(os.path.join(sdir, "agent-*.meta.json"))):
        try:
            with open(m, "r") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        aid = agent_id(m)
        agents[aid] = {"meta": meta, "jsonl": m[:-len(".meta.json")] + ".jsonl"}
    return agents


def first_record_text(path):
    """The text of an agent file's first record (its dispatch prompt), or ''."""
    try:
        with open(path, "r", errors="replace") as fh:
            line = fh.readline()
        content = (json.loads(line).get("message") or {}).get("content")
    except (OSError, ValueError, AttributeError):
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def find_by_nonce(session, nonce):
    """-> (agent id, jsonl path) of the one agent whose first record has the nonce line."""
    if not nonce or not NONCE_RE.match(nonce):
        raise NotFound("nonce must be 6-80 characters of letters, digits, . _ -")
    sdir = subagents_dir(session)
    line = re.compile(r"(?m)^(?:STU-SUPERVISED|STU-NONCE):[ \t]*%s[ \t]*$" % re.escape(nonce))
    hits = [p for p in sorted(glob.glob(os.path.join(sdir, "agent-*.jsonl")))
            if line.search(first_record_text(p))]
    if not hits:
        raise NotFound("no agent file under %s has the nonce line %s" % (sdir, nonce))
    if len(hits) > 1:
        raise NotFound("ambiguous: %d agent files carry the nonce line %s" % (len(hits), nonce))
    return agent_id(hits[0]), hits[0]


def walk(agents, root):
    """The root, then its descendants by parentAgentId, breadth first, ids sorted."""
    order, queue = [], [root]
    while queue:
        cur = queue.pop(0)
        if cur in order:
            continue
        order.append(cur)
        queue.extend(sorted(a for a, v in agents.items()
                            if v["meta"].get("parentAgentId") == cur))
    return order


def describe(aid, entry, now):
    meta = entry["meta"]
    live = meta.get("finished") is not True
    try:
        age = "%ds" % max(0, int(now - os.path.getmtime(entry["jsonl"])))
    except OSError:
        age = "unknown"
    return live, "%s depth=%s state=%s last-write=%s" % (
        aid, meta.get("spawnDepth", "?"), "live" if live else "finished", age)


def main(argv):
    p = argparse.ArgumentParser(prog="stu-tree", description=__doc__.split("\n")[0])
    p.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    g = p.add_mutually_exclusive_group()
    g.add_argument("--root", help="agent id whose descendants to list")
    g.add_argument("--nonce", help="the root is the agent whose prompt carries this nonce")
    args = p.parse_args(argv)   # exits 2 on a usage error
    try:
        sdir = subagents_dir(args.session)
        root = args.root
        if root and root.startswith("agent-"):
            root = root[len("agent-"):]
        if args.nonce:
            root = find_by_nonce(args.session, args.nonce)[0]
        agents = load_agents(sdir) if os.path.isdir(sdir) else {}
        if root and root not in agents:
            raise NotFound("agent %s not found under %s" % (root, sdir))
    except NotFound as e:
        sys.stderr.write("stu-tree: %s\n" % e)
        return 3
    order = walk(agents, root) if root else sorted(agents)
    now = time.time()
    any_live = False
    for aid in order:
        live, line = describe(aid, agents[aid], now)
        any_live = any_live or live
        print(line)
    return 0 if any_live else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
