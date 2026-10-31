#!/usr/bin/env python3
"""Behavior fixtures for the Codex adapter; no live transcript text is read."""
import json
import datetime
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent
OWN = "01234567-89ab-cdef-0123-456789abcdef"
OTHER = "11234567-89ab-cdef-0123-456789abcdef"


def meta(sid=OWN, role=None, parent=None):
    payload = {"id": sid, "cwd": "/repo", "source": "cli"}
    if parent:
        payload.update(session_id=parent, thread_source="subagent", source={
            "subagent": {"thread_spawn": {
                "parent_thread_id": parent, "agent_role": role,
            }}})
    return {"type": "session_meta", "payload": payload}


def usage(n, total, output=100):
    return {"type": "event_msg", "payload": {"type": "token_count", "info": {
        "last_token_usage": {"input_tokens": n, "cached_input_tokens": n // 2,
                             "output_tokens": output},
        "total_token_usage": {"input_tokens": total,
                              "cached_input_tokens": total // 2,
                              "output_tokens": total // 100},
        "model_context_window": 272000,
    }}}


class CodexTelemetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith((
            "CODEX_", "CLAUDE_", "STU_", "RUN_CTX_", "RUN_TURN_"))}
        self.env.update(CODEX_HOME=str(self.root), CODEX_THREAD_ID=OWN,
                        RUN_TURN_GUARD_DIR=str(self.root / "guard"))

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, records, sid=OWN, suffix=""):
        path = self.root / "sessions" / "2026" / ("rollout-date-" + sid + suffix + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return path

    def run_script(self, name="ctx.py", payload=None):
        return subprocess.run([sys.executable, str(SCRIPTS / name)],
                              input=json.dumps(payload) if payload is not None else "",
                              env=self.env, text=True, capture_output=True)

    def test_cached_input_is_already_inclusive_and_duplicate_snapshot_is_one_request(self):
        self.transcript([meta(), usage(60000, 60000), usage(60000, 60000),
                         usage(70000, 130000)])
        got = self.run_script()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("context: 70,000 tokens  [OK]", got.stdout)
        self.assertIn("peak: 70,000   turns: 2", got.stdout)

    def test_compaction_shrinks_current_but_preserves_peak(self):
        self.transcript([meta(), usage(180000, 180000),
                         {"type": "compacted", "payload": {}}, usage(50000, 230000)])
        got = self.run_script()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("context: 50,000", got.stdout)
        self.assertIn("peak: 180,000   turns: 2", got.stdout)

    def test_reemitted_request_can_refresh_context_without_counting_another_request(self):
        self.transcript([meta(), usage(180000, 180000),
                         {"type": "compacted", "payload": {}}, usage(50000, 180000)])
        got = self.run_script()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("context: 50,000", got.stdout)
        self.assertIn("peak: 180,000   turns: 1", got.stdout)

    def test_malformed_lines_and_partial_trailing_record_do_not_count(self):
        p = self.transcript([meta(), usage(60000, 60000)])
        with p.open("a") as f:
            f.write("garbage\n[]\nnull\n{\"type\":\"event_msg\",\"payload\":")
        got = self.run_script()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("turns: 1", got.stdout)

    def test_missing_usage_is_a_supervisor_error(self):
        self.transcript([meta(), {"type": "event_msg", "payload": {
            "type": "token_count", "info": None}}])
        got = self.run_script()
        self.assertEqual(got.returncode, 2)
        self.assertEqual(got.stdout, "")
        self.assertIn("usage", got.stderr)

    def test_invalid_latest_usage_does_not_report_stale_safe_context(self):
        broken = usage(200000, 260000)
        broken["payload"]["info"]["last_token_usage"]["input_tokens"] = "unknown"
        self.transcript([meta(), usage(60000, 60000), broken])
        got = self.run_script()
        self.assertEqual(got.returncode, 2)
        self.assertEqual(got.stdout, "")
        self.assertIn("invalid token usage", got.stderr)

    def test_concurrent_parent_and_similar_id_files_never_win(self):
        self.transcript([meta(), usage(60000, 60000)])
        self.transcript([meta(OTHER), usage(250000, 250000)], sid=OTHER)
        self.transcript([meta(OTHER), usage(250000, 250000)], suffix="-copy")
        got = self.run_script()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("context: 60,000", got.stdout)

    def test_explicit_path_still_requires_own_metadata_id(self):
        path = self.transcript([meta(OTHER), usage(250000, 250000)], sid=OTHER)
        self.env["STU_TRANSCRIPT_PATH"] = str(path)
        got = self.run_script()
        self.assertEqual(got.returncode, 2)
        self.assertIn("identity", got.stderr)

    def test_own_child_id_takes_precedence_over_parent_session_id(self):
        self.transcript([meta(parent=OTHER), usage(60000, 60000)])
        got = self.run_script()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("context: 60,000", got.stdout)

    def test_growth_and_context_overrides_still_apply(self):
        self.env.update(RUN_CTX_SOFT="65000", RUN_CTX_HARD="90000")
        self.transcript([meta()] + [usage(n, i * 100000) for i, n in enumerate(
            [60000] * 5 + [100000] * 5, 1)])
        got = self.run_script()
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("[HARD EXCEEDED", got.stdout)
        self.assertIn("growth: +40,000 tokens  [EXCEEDED", got.stdout)

    def test_no_identity_never_uses_recent_transcript(self):
        self.transcript([meta(), usage(60000, 60000)])
        del self.env["CODEX_THREAD_ID"]
        self.env["STU_RUNTIME"] = "codex"
        got = self.run_script()
        self.assertEqual(got.returncode, 2)
        self.assertIn("CODEX_THREAD_ID", got.stderr)

    def test_claude_environment_wins_over_inherited_codex_identity(self):
        self.transcript([meta(), usage(60000, 60000)])
        self.env["CLAUDE_CODE_SESSION_ID"] = "does-not-exist"
        got = self.run_script()
        self.assertEqual(got.returncode, 2)
        self.assertIn("does-not-exist", got.stderr)
        self.env["STU_RUNTIME"] = "codex"
        got = self.run_script()
        self.assertEqual(got.returncode, 0, got.stderr)

    def hook_world(self, role="orchestrator", count=1, context=170000):
        repo = self.root / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        config = self.root / "stu.md"
        config.write_text("---\nrun_home: %s\ngithub_repo: acme/app\n---\n" % (self.root / "run"))
        self.env["STU_CONFIG"] = str(config)
        claim = self.root / "run" / "runs" / "claims.tsv"
        claim.parent.mkdir(parents=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        claim.write_text("unit1\trun1\tsess1\t%s\n" % stamp)
        metadata = meta(parent=OTHER)
        metadata["payload"]["cwd"] = str(repo)
        spawn = metadata["payload"]["source"]["subagent"]["thread_spawn"]
        spawn["agent_path"] = "/root/stu_" + role
        path = self.transcript([metadata] + [usage(context, i * context) for i in range(1, count + 1)])
        return {"hook_event_name": "PostToolUse", "session_id": OTHER,
                "transcript_path": str(path), "cwd": str(repo),
                "tool_name": "Bash", "tool_use_id": "call1"}, claim

    def test_hook_own_verified_child_warns_as_json_and_deduplicates_parallel_tools(self):
        payload, _ = self.hook_world()
        first = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual(first.returncode, 0, first.stderr)
        message = json.loads(first.stdout)["hookSpecificOutput"]
        self.assertEqual(message["hookEventName"], "PostToolUse")
        self.assertIn("CONTEXT HARD", message["additionalContext"])
        self.assertIn("170,000", message["additionalContext"])
        again = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual((again.returncode, again.stdout, again.stderr), (0, "", ""))

    def test_hook_native_agent_id_must_match_own_child_when_present(self):
        payload, _ = self.hook_world()
        # Native Codex currently reports agent_type=default even when the task
        # path identifies a Stu role. agent_id is its stronger identity field.
        payload.update(agent_id=OTHER, agent_type="default")
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "", ""))
        self.assertFalse((self.root / "guard").exists())
        payload["agent_id"] = OWN
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertIn("CONTEXT HARD", got.stdout)

    def test_hook_never_counts_parent_or_unrelated_child(self):
        payload, _ = self.hook_world()
        for record in (meta(OTHER), meta(parent="unrelated")):
            p = self.transcript([record, usage(250000, 250000)])
            payload["transcript_path"] = str(p)
            got = self.run_script("codex_turn_guard.py", payload)
            self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "", ""))
        self.assertFalse((self.root / "guard").exists())

    def test_hook_verified_child_path_handles_parent_inherited_environment(self):
        payload, _ = self.hook_world()
        self.env["CODEX_THREAD_ID"] = OTHER
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("CONTEXT HARD", json.loads(got.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_depth_two_hook_accepts_verified_root_session_with_own_or_root_environment(self):
        payload, _ = self.hook_world(role="implementer", context=200000)
        path = Path(payload["transcript_path"])
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        spawn = rows[0]["payload"]["source"]["subagent"]["thread_spawn"]
        spawn.update(parent_thread_id="intermediate-orchestrator", depth=2,
                     agent_path="/root/stu_orchestrator/stu_implementer")
        # Metadata session_id and hook session_id name the root; immediate
        # parent_thread_id instead names the intervening orchestrator.
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        for env_id in (OWN, OTHER, None):
            with self.subTest(environment_identity=env_id):
                if env_id is None:
                    self.env.pop("CODEX_THREAD_ID", None)
                else:
                    self.env["CODEX_THREAD_ID"] = env_id
                self.env["RUN_TURN_GUARD_DIR"] = str(self.root / ("guard-" + str(env_id)))
                got = self.run_script("codex_turn_guard.py", payload)
                self.assertEqual((got.returncode, got.stderr), (0, ""))
                self.assertIn("CONTEXT HARD", got.stdout)
        payload["session_id"] = "unrelated-root"
        rejected_guard = self.root / "guard-unrelated-root"
        self.env["RUN_TURN_GUARD_DIR"] = str(rejected_guard)
        self.assertEqual(self.run_script("codex_turn_guard.py", payload).stdout, "")
        self.assertFalse(rejected_guard.exists())
        payload["session_id"] = OTHER
        self.env["CODEX_THREAD_ID"] = "unrelated-thread"
        self.assertEqual(self.run_script("codex_turn_guard.py", payload).stdout, "")
        self.assertFalse(rejected_guard.exists())

    def test_stu_issue_suffix_preserves_role_budget_with_strict_name_boundary(self):
        payload, _ = self.hook_world(role="implementer_issue_2", context=195000)
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertIn("CONTEXT HARD", got.stdout)
        self.assertIn("hard 190,000", got.stdout)
        path = Path(payload["transcript_path"])
        for name in ("stu_implementer_issue_unrelated", "stu_implementer_issue_2_extra"):
            with self.subTest(agent_name=name):
                rejected_guard = self.root / ("guard-" + name)
                self.env["RUN_TURN_GUARD_DIR"] = str(rejected_guard)
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                rows[0]["payload"]["source"]["subagent"]["thread_spawn"]["agent_path"] = "/root/" + name
                path.write_text("".join(json.dumps(row) + "\n" for row in rows))
                self.assertEqual(self.run_script("codex_turn_guard.py", payload).stdout, "")
                self.assertFalse(rejected_guard.exists())

    def test_hook_cwd_symlink_is_same_configured_project(self):
        payload, _ = self.hook_world()
        alias = self.root / "repo-alias"
        alias.symlink_to(Path(payload["cwd"]), target_is_directory=True)
        payload["cwd"] = str(alias)
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("CONTEXT HARD", got.stdout)

    def test_hook_requires_live_run_and_stu_agent_name(self):
        payload, claims = self.hook_world(role="unrelated")
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual((got.returncode, got.stdout), (0, ""))
        path = Path(payload["transcript_path"])
        path.write_text(path.read_text().replace("stu_unrelated", "stu_orchestrator"))
        claims.unlink()
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual((got.returncode, got.stdout), (0, ""))
        self.assertFalse((self.root / "guard").exists())

    def test_hook_counts_model_requests_and_does_not_claim_hard_max_turns(self):
        payload, _ = self.hook_world(count=120, context=2000)
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual(got.returncode, 0, got.stderr)
        message = json.loads(got.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("120 model requests", message)
        self.assertNotIn("maxTurns", message)

    def test_hook_partial_record_is_counted_when_completed_then_compaction_uses_latest(self):
        payload, _ = self.hook_world(context=10000)
        path = Path(payload["transcript_path"])
        partial = json.dumps(usage(170000, 180000))
        with path.open("a") as f:
            f.write(partial[:30])
        self.assertEqual(self.run_script("codex_turn_guard.py", payload).stdout, "")
        with path.open("a") as f:
            f.write(partial[30:] + "\n")
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertIn("CONTEXT HARD", got.stdout)
        with path.open("a") as f:
            f.write(json.dumps({"type": "compacted", "payload": {}}) + "\n")
            f.write(json.dumps(usage(10000, 190000)) + "\n")
        self.assertEqual(self.run_script("codex_turn_guard.py", payload).stdout, "")

    def test_hook_errors_remain_silent_and_never_block(self):
        payload, _ = self.hook_world()
        for value in ([], None, {"hook_event_name": "SessionStart"}, payload):
            if value is payload:
                Path(payload["transcript_path"]).write_text("not-json\n")
            got = self.run_script("codex_turn_guard.py", value)
            self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "", ""))

    def test_parallel_hook_invocations_emit_one_warning_for_same_child(self):
        payload, _ = self.hook_world()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.run_script("codex_turn_guard.py", payload), range(8)))
        self.assertTrue(all(r.returncode == 0 and r.stderr == "" for r in results))
        self.assertEqual(sum(bool(r.stdout) for r in results), 1)

    def test_child_context_states_are_isolated_with_same_parent(self):
        payload, _ = self.hook_world()
        own = Path(payload["transcript_path"])
        other_id = "21234567-89ab-cdef-0123-456789abcdef"
        second = self.transcript([], sid=other_id)
        second.write_text(own.read_text().replace(OWN, other_id).replace("170000", "10000"))
        first = self.run_script("codex_turn_guard.py", payload)
        self.assertIn("CONTEXT HARD", first.stdout)
        self.env["CODEX_THREAD_ID"] = other_id
        payload["transcript_path"] = str(second)
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertEqual((got.returncode, got.stdout, got.stderr), (0, "", ""))
        self.assertEqual(len(list((self.root / "guard").glob("*.json"))), 2)

    def test_replaced_transcript_restarts_counters(self):
        payload, _ = self.hook_world(context=10000)
        self.assertEqual(self.run_script("codex_turn_guard.py", payload).stdout, "")
        path = Path(payload["transcript_path"])
        replacement = path.with_suffix(".tmp")
        replacement.write_text(path.read_text().replace("10000", "170000"))
        replacement.replace(path)
        got = self.run_script("codex_turn_guard.py", payload)
        self.assertIn("CONTEXT HARD", got.stdout)

    def test_ambiguous_exact_session_files_error_instead_of_choosing_newest(self):
        path = self.transcript([meta(), usage(60000, 60000)])
        other_dir = self.root / "sessions" / "2025"
        other_dir.mkdir()
        (other_dir / path.name).write_text(path.read_text())
        got = self.run_script()
        self.assertEqual(got.returncode, 2)
        self.assertIn("2 transcripts match", got.stderr)

    def test_missing_cumulative_usage_fails_instead_of_inventing_request_count(self):
        record = usage(60000, 60000)
        del record["payload"]["info"]["total_token_usage"]
        self.transcript([meta(), record])
        got = self.run_script()
        self.assertEqual(got.returncode, 2)
        self.assertIn("usage snapshot", got.stderr)

    def test_claude_scan_contract_keeps_cache_sum_sidechain_filter_and_growth_shape(self):
        import ctx
        path = self.root / "claude.jsonl"
        base = {"input_tokens": 1000, "cache_creation_input_tokens": 2000,
                "cache_read_input_tokens": 3000}
        path.write_text("".join(json.dumps(r) + "\n" for r in [
            {"message": {"id": "one", "usage": base}},
            {"message": {"id": "one", "usage": base}},
            {"isSidechain": True, "message": {"id": "child", "usage": {"input_tokens": 999999}}},
            {"message": {"id": "two", "usage": {"input_tokens": 2000}}},
        ]))
        with mock.patch.dict(os.environ, {"STU_RUNTIME": "claude"}):
            self.assertEqual(ctx.scan(path), (2000, 6000, 2, [6000, 2000]))


if __name__ == "__main__":
    unittest.main()
