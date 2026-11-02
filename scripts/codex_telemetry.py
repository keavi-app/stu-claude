#!/usr/bin/env python3
"""Strict adapter for the observed Codex rollout JSONL format (not a stable API).

Only metadata and token-count records are interpreted. Current context is the
latest request's input_tokens, which ALREADY includes cached_input_tokens.
"Turns" are distinct model-request usage snapshots, not user turns or tool calls.
The cumulative usage snapshot deduplicates repeated token_count notifications.
"""
import json
import os
from pathlib import Path
import re


class TelemetryError(ValueError):
    pass


def records(path):
    """Read complete JSON objects only; an in-flight trailing line is retried later."""
    with Path(path).open("rb") as fh:
        for line in fh:
            if not line.endswith(b"\n"):
                break
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(record, dict):
                yield record


def session_metadata(path, expected_id=None):
    """Verify own id, never the parent-valued session_id when id is available."""
    metadata = None
    for record in records(path):
        if record.get("type") != "session_meta":
            continue
        candidate = record.get("payload")
        if not isinstance(candidate, dict):
            raise TelemetryError("invalid session metadata")
        own_id = candidate.get("id") or candidate.get("session_id")
        if not isinstance(own_id, str) or not own_id:
            raise TelemetryError("session metadata has no identity")
        if expected_id is not None and own_id != expected_id:
            raise TelemetryError("transcript identity does not match CODEX_THREAD_ID")
        if metadata is not None and own_id != (metadata.get("id") or metadata.get("session_id")):
            raise TelemetryError("conflicting transcript identities")
        metadata = candidate
    if metadata is None:
        raise TelemetryError("transcript has no session metadata identity")
    return metadata


def transcript_path(env=None):
    env = os.environ if env is None else env
    sid = env.get("CODEX_THREAD_ID")
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        raise TelemetryError("CODEX_THREAD_ID is not set or invalid; refusing to guess this session")
    explicit = env.get("STU_TRANSCRIPT_PATH")
    if explicit:
        path = Path(explicit).expanduser()
        session_metadata(path, sid)
        return str(path)
    root = Path(env.get("CODEX_HOME") or Path.home() / ".codex").expanduser() / "sessions"
    # The id is a complete suffix, never a substring or a file-mtime heuristic.
    hits = [p for p in root.rglob("*.jsonl")
            if p.name == sid + ".jsonl" or p.name.endswith("-" + sid + ".jsonl")]
    if len(hits) != 1:
        raise TelemetryError("%d transcripts match session %s under %s" % (len(hits), sid, root))
    session_metadata(hits[0], sid)
    return str(hits[0])


def _token_integer(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TelemetryError("invalid token usage; refusing to report stale context")
    return value


def scan(path):
    """Return (current, peak, requests, contexts), the ctx.py scan contract."""
    contexts = []
    previous = None
    peak = 0
    for record in records(path):
        measured = usage_snapshot(record)
        if measured is None:
            continue
        context, snapshot = measured
        peak = max(peak, context)
        if snapshot == previous:
            # The same request can be re-emitted with a fresher reading after
            # context editing. Refresh current context without inventing a turn.
            contexts[-1] = context
            continue
        previous = snapshot
        contexts.append(context)
    if not contexts:
        raise TelemetryError("transcript has no usable token usage records yet")
    return contexts[-1], peak, len(contexts), contexts


def usage_snapshot(record):
    """(request input tokens, cumulative snapshot key), or None for non-usage."""
    payload = record.get("payload")
    if record.get("type") != "event_msg" or not isinstance(payload, dict):
        return None
    if payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    # Codex also emits rate-limit-only notifications with info=null.
    if info is None:
        return None
    if not isinstance(info, dict):
        raise TelemetryError("invalid token usage info")
    last = info.get("last_token_usage")
    total = info.get("total_token_usage")
    if not isinstance(last, dict) or not isinstance(total, dict):
        raise TelemetryError("missing token usage snapshot")
    context = _token_integer(last.get("input_tokens"))
    if not context:
        return None
    _token_integer(total.get("input_tokens"))
    _token_integer(total.get("output_tokens"))
    snapshot = json.dumps({key: _token_integer(value) for key, value in total.items()},
                          sort_keys=True, separators=(",", ":"))
    return context, snapshot
