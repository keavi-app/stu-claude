#!/usr/bin/env python3
"""Opt-in handling for GitHub plan-unavailable rules, through the real forge CLI."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = "acme/app"
RULES_KEY = "api repos/%s/rules/branches/main" % SLUG

PLAN = "Upgrade to GitHub Pro or make this repository public to enable this feature."
SETTINGS = {"allow_squash_merge": True, "allow_merge_commit": False,
            "allow_rebase_merge": False, "allow_auto_merge": False}
BASE_LINES = ["SETTING squash on", "SETTING merge off", "SETTING rebase off",
              "SETTING auto_merge off"]


def response(message=PLAN, status="403", stderr=None):
    return {"rc": 1, "stdout": json.dumps({"message": message, "status": status,
             "documentation_url": "https://docs.github.com/rest/repos/rules"}) + "\n",
            "stderr": stderr or "gh: %s (HTTP %s)" % (message, status)}


def repo_settings(rule_response, allow=False):
    args = ["repo-settings", "--slug", SLUG, "--base", "main"]
    if allow:
        args.append("--allow-unavailable-rules")
    with tempfile.TemporaryDirectory() as tmp:
        os.symlink(os.path.join(ROOT, "tests", "fake_gh.py"), os.path.join(tmp, "gh"))
        fixture = os.path.join(tmp, "responses.json")
        with open(fixture, "w") as f:
            json.dump({"api repos/" + SLUG: {"json": SETTINGS}, RULES_KEY: rule_response}, f)
        env = dict(os.environ, PATH=tmp + os.pathsep + os.environ["PATH"],
                   FAKE_GH_FIXTURES=fixture)
        p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "stu_forge.py")] + args,
                           env=env, capture_output=True, text=True)
        return p.returncode, p.stdout.splitlines()


class CodexForgeTests(unittest.TestCase):
    def test_default_preserves_partial_error_for_known_plan_response(self):
        rc, lines = repo_settings(response())
        self.assertEqual((rc, lines), (3, ["ERROR partial gh: %s (HTTP 403)" % PLAN]))

    def test_explicit_flag_reports_unknown_for_known_plan_response(self):
        rc, lines = repo_settings(response(), allow=True)
        self.assertEqual((rc, lines), (0, BASE_LINES + ["SETTING merge_queue unknown", "OK"]))

    def test_flag_does_not_suppress_other_failed_reads(self):
        cases = [
            (response("Bad credentials", "401"), "auth"),
            (response("API rate limit exceeded"), "rate-limit"),
            (response("Resource not accessible by integration"), "partial"),
            (response("Server Error", "500"), "partial"),
            ({"rc": 1, "stderr": "gh: Server Error (HTTP 500)"}, "forge"),
            (response(stderr="gh: %s (HTTP 403) API rate limit exceeded" % PLAN), "rate-limit"),
        ]
        for resp, cls in cases:
            with self.subTest(cls=cls, error=resp["stderr"]):
                rc, lines = repo_settings(resp, allow=True)
                self.assertEqual(rc, 3)
                self.assertEqual(lines[0].split()[:2], ["ERROR", cls])
                self.assertEqual(len(lines), 1, lines)

    def test_plan_error_after_partial_page_is_not_allowed(self):
        resp = response()
        resp["stdout"] = '{"type":"merge_queue"}\n' + resp["stdout"]
        rc, lines = repo_settings(resp, allow=True)
        self.assertEqual(rc, 3)
        self.assertEqual(lines[0].split()[:2], ["ERROR", "partial"])
        self.assertEqual(len(lines), 1)

    def test_flag_requires_matching_error_body_and_status(self):
        for resp in (response(status="500", stderr="gh: %s (HTTP 403)" % PLAN),
                     response(message="Forbidden", stderr="gh: %s (HTTP 403)" % PLAN)):
            with self.subTest(response=resp):
                rc, lines = repo_settings(resp, allow=True)
                self.assertEqual(rc, 3)
                self.assertEqual(lines[0].split()[:2], ["ERROR", "partial"])

    def test_flag_keeps_successful_queue_facts(self):
        for rules, queue in (([], "off"), ([{"type": "merge_queue"}], "on")):
            with self.subTest(queue=queue):
                rc, lines = repo_settings({"json": [rules]}, allow=True)
                self.assertEqual((rc, lines),
                                 (0, BASE_LINES + ["SETTING merge_queue " + queue, "OK"]))


if __name__ == "__main__":
    unittest.main()
