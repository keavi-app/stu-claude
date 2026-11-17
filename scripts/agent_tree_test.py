#!/usr/bin/env python3
"""Regression suite for stu-tree (agent_tree.py) and its shared nonce lookup.

Fixtures are hand-written: <root>/<project>/<session>/subagents/agent-<id>.{meta.json,jsonl}.
Run: python3 scripts/agent_tree_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agent_tree  # noqa: E402

SESSION = "sess-0001"


def prompt_record(text, aid):
    return json.dumps({"isSidechain": True, "agentId": aid, "type": "user",
                       "message": {"role": "user", "content": text}}) + "\n"


class Fixture(object):
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.sdir = os.path.join(self.root, "proj-a", SESSION, "subagents")
        os.makedirs(self.sdir)

    def agent(self, aid, depth, parent=None, finished=None, status=None, prompt="work",
              age=10, write_jsonl=True):
        meta = {"agentType": "x", "spawnDepth": depth}
        if parent:
            meta["parentAgentId"] = parent
        if finished is not None:
            meta["finished"] = finished
        if status:
            meta["status"] = status
        with open(os.path.join(self.sdir, "agent-%s.meta.json" % aid), "w") as fh:
            json.dump(meta, fh)
        if write_jsonl:
            path = os.path.join(self.sdir, "agent-%s.jsonl" % aid)
            with open(path, "w") as fh:
                fh.write(prompt_record(prompt, aid))
            t = time.time() - age
            os.utime(path, (t, t))

    def run(self, *args, **env):
        e = dict(os.environ, STU_PROJECTS_ROOT=self.root, CLAUDE_CODE_SESSION_ID=SESSION)
        e.update(env)
        return subprocess.run([sys.executable, os.path.join(HERE, "agent_tree.py")] + list(args),
                              capture_output=True, text=True, env=e)


class Tree(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        f = self.f
        f.agent("sup", 1, finished=False, status="completed", age=300)
        f.agent("orch", 2, parent="sup", finished=True, age=60)
        f.agent("impl", 3, parent="orch", age=5)
        f.agent("other", 1, finished=True)

    def test_walks_descendants_only(self):
        r = self.f.run("--root", "sup")
        self.assertEqual(r.returncode, 0)
        lines = r.stdout.splitlines()
        self.assertEqual([l.split()[0] for l in lines], ["sup", "orch", "impl"])
        self.assertIn("depth=1 state=live last-write=300s", lines[0])
        self.assertIn("depth=2 state=finished last-write=60s", lines[1])

    def test_completed_status_is_not_done(self):
        r = self.f.run("--root", "sup")
        self.assertIn("sup depth=1 state=live", r.stdout)

    def test_all_finished_exits_one(self):
        self.f.agent("impl", 3, parent="orch", finished=True)
        self.f.agent("sup", 1, finished=True)
        r = self.f.run("--root", "sup")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("state=live", r.stdout)

    def test_live_descendant_under_finished_root_is_live(self):
        self.f.agent("sup", 1, finished=True)
        self.f.agent("orch", 2, parent="sup", finished=True)
        self.assertEqual(self.f.run("--root", "orch").returncode, 0)  # impl still live

    def test_root_accepts_agent_prefix(self):
        self.assertEqual(self.f.run("--root", "agent-orch").stdout.split()[0], "orch")

    def test_missing_transcript_is_unknown_age(self):
        self.f.agent("ghost", 2, parent="sup", write_jsonl=False)
        self.assertIn("ghost depth=2 state=live last-write=unknown",
                      self.f.run("--root", "sup").stdout)

    def test_not_found_exits_three(self):
        r = self.f.run("--root", "nope")
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        # --session pins one folder: the agent is not in another session's folder
        r = self.f.run("--root", "sup", "--session", "other-session")
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        # a bare listing still uses the env session, and fails when it is not found
        r = self.f.run(CLAUDE_CODE_SESSION_ID="other-session")
        self.assertEqual(r.returncode, 3)
        r = self.f.run(CLAUDE_CODE_SESSION_ID="")
        self.assertEqual(r.returncode, 3)

    def test_usage_exits_two(self):
        self.assertEqual(self.f.run("--root", "a", "--nonce", "abcdef").returncode, 2)
        self.assertEqual(self.f.run("--bogus").returncode, 2)

    def test_session_flag_beats_env(self):
        r = self.f.run("--root", "sup", "--session", SESSION, CLAUDE_CODE_SESSION_ID="zzz")
        self.assertEqual(r.returncode, 0)

    def test_nonce_names_the_root(self):
        self.f.agent("sup2", 1, prompt="hello\nSTU-SUPERVISED: nonce-sup-2\nbye")
        r = self.f.run("--nonce", "nonce-sup-2")
        self.assertEqual(r.stdout.split()[0], "sup2")


class AnySession(unittest.TestCase):
    """--root and --nonce without --session search every session folder."""
    def setUp(self):
        self.f = Fixture()
        self.f.agent("sup", 1, prompt="x\nSTU-SUPERVISED: nonce-any-1\n")
        self.f.agent("kid", 2, parent="sup", finished=True)

    def second_session(self, aid, prompt="work"):
        sdir = os.path.join(self.f.root, "proj-b", "sess-0002", "subagents")
        os.makedirs(sdir, exist_ok=True)
        with open(os.path.join(sdir, "agent-%s.meta.json" % aid), "w") as fh:
            json.dump({"spawnDepth": 1}, fh)
        with open(os.path.join(sdir, "agent-%s.jsonl" % aid), "w") as fh:
            fh.write(prompt_record(prompt, aid))

    def ids(self, r):
        return [ln.split()[0] for ln in r.stdout.splitlines()]

    def test_root_resolves_in_another_session_despite_env(self):
        r = self.f.run("--root", "sup", CLAUDE_CODE_SESSION_ID="some-other-session")
        self.assertEqual((r.returncode, self.ids(r)), (0, ["sup", "kid"]))

    def test_nonce_resolves_in_another_session_despite_env(self):
        r = self.f.run("--nonce", "nonce-any-1", CLAUDE_CODE_SESSION_ID="some-other-session")
        self.assertEqual((r.returncode, self.ids(r)), (0, ["sup", "kid"]))

    def test_root_found_only_in_second_session(self):
        self.second_session("lone")
        r = self.f.run("--root", "lone")
        self.assertEqual((r.returncode, self.ids(r)), (0, ["lone"]))

    def test_zero_matches_exit_three(self):
        r = self.f.run("--root", "ghost")
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        r = self.f.run("--nonce", "no-such-nonce")
        self.assertEqual((r.returncode, r.stdout), (3, ""))

    def test_two_matches_exit_three_naming_the_count(self):
        self.second_session("sup")
        r = self.f.run("--root", "sup")
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        self.assertIn("2 sessions", r.stderr)
        self.second_session("dup", prompt="STU-NONCE: nonce-any-1")
        r = self.f.run("--nonce", "nonce-any-1")
        self.assertEqual(r.returncode, 3)
        self.assertIn("2 sessions", r.stderr)

    def test_two_nonce_matches_in_one_session_count_agents_not_sessions(self):
        self.f.agent("n1", 1, prompt="STU-NONCE: nonce-twice-1")
        self.f.agent("n2", 1, prompt="STU-NONCE: nonce-twice-1")
        r = self.f.run("--nonce", "nonce-twice-1")
        self.assertEqual((r.returncode, r.stdout), (3, ""))
        self.assertIn("2 agents match", r.stderr)
        self.assertIn("in 1 session", r.stderr)
        self.assertNotIn("2 sessions", r.stderr)

    def test_session_flag_still_pins_one_folder(self):
        self.second_session("sup")
        r = self.f.run("--root", "sup", "--session", SESSION)
        self.assertEqual((r.returncode, self.ids(r)), (0, ["sup", "kid"]))
        r = self.f.run("--root", "sup", "--session", "sess-0002")
        self.assertEqual((r.returncode, self.ids(r)), (0, ["sup"]))


class Nonce(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        os.environ["STU_PROJECTS_ROOT"] = self.f.root
        self.addCleanup(os.environ.pop, "STU_PROJECTS_ROOT", None)

    def test_finds_the_one_match_in_either_line_form(self):
        self.f.agent("a1", 1, prompt="x\nSTU-SUPERVISED: abc-123-def\n")
        self.f.agent("a2", 2, prompt="y\nSTU-NONCE: zzz-999-yyy\n")
        self.assertEqual(agent_tree.find_by_nonce(SESSION, "abc-123-def")[0], "a1")
        self.assertEqual(agent_tree.find_by_nonce(SESSION, "zzz-999-yyy")[0], "a2")

    def test_block_content_is_read(self):
        path = os.path.join(self.f.sdir, "agent-b1.jsonl")
        self.f.agent("b1", 1)
        with open(path, "w") as fh:
            fh.write(json.dumps({"message": {"content": [
                {"type": "text", "text": "STU-NONCE: block-nonce-1"}]}}) + "\n")
        self.assertEqual(agent_tree.find_by_nonce(SESSION, "block-nonce-1")[0], "b1")

    def test_zero_matches_raises(self):
        self.f.agent("a1", 1, prompt="STU-NONCE: someone-else")
        with self.assertRaises(agent_tree.NotFound):
            agent_tree.find_by_nonce(SESSION, "not-present-1")

    def test_several_matches_raise(self):
        self.f.agent("a1", 1, prompt="STU-NONCE: dup-nonce-1")
        self.f.agent("a2", 1, prompt="STU-SUPERVISED: dup-nonce-1")
        with self.assertRaises(agent_tree.NotFound):
            agent_tree.find_by_nonce(SESSION, "dup-nonce-1")

    def test_only_the_line_form_counts(self):
        self.f.agent("a1", 1, prompt="mentions nonce-in-prose-1 inline, and STU-NONCE: nonce-in-prose-1 mid-line")
        with self.assertRaises(agent_tree.NotFound):
            agent_tree.find_by_nonce(SESSION, "nonce-in-prose-1")

    def test_only_the_first_record_counts(self):
        self.f.agent("a1", 1)
        with open(os.path.join(self.f.sdir, "agent-a1.jsonl"), "a") as fh:
            fh.write(prompt_record("STU-NONCE: later-record-1", "a1"))
        with self.assertRaises(agent_tree.NotFound):
            agent_tree.find_by_nonce(SESSION, "later-record-1")

    def test_a_prefix_of_a_nonce_does_not_match(self):
        self.f.agent("a1", 1, prompt="STU-NONCE: abcdef-extra")
        with self.assertRaises(agent_tree.NotFound):
            agent_tree.find_by_nonce(SESSION, "abcdef")

    def test_bad_nonce_shapes_raise(self):
        for bad in ("", "short", "has space here", "a" * 81, ".*.*.*.*"):
            with self.assertRaises(agent_tree.NotFound):
                agent_tree.find_by_nonce(SESSION, bad)


if __name__ == "__main__":
    unittest.main()
