#!/usr/bin/env python3
"""Advisory Codex PostToolUse budget telemetry, independent of Claude's hook.

Hook payload session_id may name the PARENT. Count only a transcript whose
session_meta proves it is a child, and whose thread_spawn path/role names a Stu
seat, inside a configured project with live claims. A parent transcript, unknown
format, missing usage, or ambiguous identity silently skips this advisory hook.
CODEX_THREAD_ID resolves the transcript only when the payload omits its path.

This counts model requests, not user turns, and enforces no maxTurns limit.
The rollout schema is observational and must be rechecked on Codex upgrades.
"""
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

import codex_telemetry as telemetry

BUDGETS = {"orchestrator": 120, "implementer": 140}
BANDS = {"orchestrator": (120000, 160000), "implementer": (150000, 190000)}


def own_child(payload):
    explicit = payload.get("transcript_path")
    if explicit is not None and (not isinstance(explicit, str) or not explicit):
        return None
    path = Path(explicit or telemetry.transcript_path())
    # Metadata is always first in observed rollouts. Stop before decoding any
    # conversation text; an unknown format is not a reason to guess identity.
    first = next(telemetry.records(path), {})
    if first.get("type") != "session_meta":
        return None
    metadata = first.get("payload")
    if not isinstance(metadata, dict):
        return None
    sid = metadata.get("id") or metadata.get("session_id")
    if not isinstance(sid, str) or not sid:
        return None
    # Native builds can supply the child's id even when common session_id
    # names its root. If supplied, it must corroborate this exact transcript.
    agent_id = payload.get("agent_id")
    if agent_id is not None and agent_id != sid:
        return None
    if not (path.name == sid + ".jsonl" or path.name.endswith("-" + sid + ".jsonl")):
        return None
    source = metadata.get("source")
    subagent = source.get("subagent") if isinstance(source, dict) else None
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
    if not isinstance(spawn, dict):
        return None
    parent = spawn.get("parent_thread_id")
    # At depth two and beyond the common session_id can name the ROOT, while
    # parent_thread_id names the immediate parent. Accept only lineage ids
    # recorded in this verified child's metadata; never infer a child's id
    # from either parent-valued field or open their transcripts for usage.
    lineage = {sid, parent}
    root = metadata.get("session_id")
    if isinstance(root, str) and root:
        lineage.add(root)
    if not parent or sid == parent or payload.get("session_id") not in lineage:
        return None
    env_id = os.environ.get("CODEX_THREAD_ID")
    if env_id and env_id not in lineage:
        return None
    # Names alone are insufficient: live configured claims are checked next.
    leaf = str(spawn.get("agent_path") or "").rsplit("/", 1)[-1]
    match = re.fullmatch(r"stu_(orchestrator|implementer)(?:[_-](?:cycle|issue)[_-]?\d+)?", leaf)
    if match is None:
        match = re.fullmatch(r"stu[-_](orchestrator|implementer)", str(spawn.get("agent_role") or ""))
    if match is None:
        return None
    cwd = payload.get("cwd")
    metadata_cwd = metadata.get("cwd")
    if not isinstance(cwd, str) or not cwd or not isinstance(metadata_cwd, str) or not metadata_cwd:
        return None
    if Path(metadata_cwd).resolve() != Path(cwd).resolve():
        return None
    return path, sid, match.group(1)


def live_run(payload):
    """Use Stu's existing config and claims semantics, without forge/network I/O."""
    import run_claims
    import stu_env

    resolved = stu_env.resolve(cwd=payload["cwd"], require_config=True, forge_lookup=False)
    os.environ["RUN_CLAIMS_FILE"] = os.environ.get("RUN_CLAIMS_FILE") or str(
        Path(resolved["RUN_HOME"]) / "runs" / "claims.tsv")
    return any(not run_claims.is_hold(row) and run_claims.is_live(row)
               for row in run_claims.read_rows())


def update(path, state):
    """Consume new whole lines; state is bounded and scoped to this child."""
    stat = path.stat()
    identity = [stat.st_dev, stat.st_ino]
    offset = state.get("offset", 0)
    if state.get("file") != identity or not isinstance(offset, int) or offset > stat.st_size:
        state = {}
        offset = 0
    state["file"] = identity
    with path.open("rb") as fh:
        fh.seek(offset)
        while True:
            line = fh.readline()
            if not line.endswith(b"\n"):
                break
            state["offset"] = fh.tell()
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            measured = telemetry.usage_snapshot(record)
            if measured is None:
                continue
            context, snapshot = measured
            state["context"] = context
            if snapshot == state.get("snapshot"):
                continue
            state["snapshot"] = snapshot
            state["requests"] = state.get("requests", 0) + 1
    return state


def warning(state, role):
    requests = state.get("requests", 0)
    context = state.get("context", 0)
    if not requests or not context:
        return None
    soft, hard = BANDS[role]
    soft = int(os.environ.get("RUN_CTX_SOFT") or soft)
    hard = int(os.environ.get("RUN_CTX_HARD") or hard)
    budget = BUDGETS[role]
    stage = (2 + (requests - budget) // 25 if requests >= budget
             else 1 if requests >= int(budget * 0.85) else 0)
    messages = []
    if stage > state.get("request_warned", 0):
        label = "MODEL REQUEST BUDGET" + (" EXCEEDED" if requests >= budget else " APPROACHING")
        messages.append("%s: %d model requests against an advisory budget of %d. "
                        "Reach a clean stopping point, write your handoff, and return."
                        % (label, requests, budget))
        state["request_warned"] = stage
    ctx_stage = 2 if context >= hard else 1 if context >= soft else 0
    repeat = ctx_stage == 2 and requests - state.get("context_warned_at", 0) >= 25
    if ctx_stage and (ctx_stage > state.get("context_warned", 0) or repeat):
        messages.append("CONTEXT %s: %s input tokens after %d model requests "
                        "(soft %s; hard %s). %s"
                        % ("HARD" if ctx_stage == 2 else "SOFT", format(context, ","), requests,
                           format(soft, ","), format(hard, ","),
                           "Write your handoff and return now, mid-unit if necessary."
                           if ctx_stage == 2 else "Finish this unit, then hand off; open no new threads."))
        state["context_warned_at"] = requests
    state["context_warned"] = ctx_stage
    return "\n".join(messages) or None


def handle(payload):
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PostToolUse":
        return None
    child = own_child(payload)
    if child is None or not live_run(payload):
        return None
    path, sid, role = child
    directory = Path(os.environ.get("RUN_TURN_GUARD_DIR") or Path.home() / ".stu" / ".codex-turn-guard")
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / ("codex-" + hashlib.sha256(sid.encode()).hexdigest()[:24] + ".json")
    with state_path.with_suffix(".lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        try:
            state = json.loads(state_path.read_text())
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError):
            state = {}
        state = update(path, state)
        message = warning(state, role)
        tmp = state_path.with_suffix(".%d.tmp" % os.getpid())
        try:
            tmp.write_text(json.dumps(state, separators=(",", ":")))
            tmp.replace(state_path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
        return message


def main():
    try:
        # Helpers may raise SystemExit or print diagnostics; a telemetry hook is
        # strictly advisory and stdout must contain only valid hook JSON.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            message = handle(json.load(sys.stdin))
    except (Exception, SystemExit):
        return 0
    if message:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": message}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
