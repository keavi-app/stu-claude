#!/usr/bin/env python3
"""Codex publish-guard regressions using real hook payloads and local git pushes.

Run: python3 scripts/codex_publish_guard_test.py
"""
import os
import subprocess
import tempfile
import unittest

import publish_guard_test as fixtures


class CodexPublishGuardTests(unittest.TestCase):
    def shared_config(self, f):
        f.env = {k: v for k, v in f.env.items() if not k.startswith("STU_")}
        # Keep spaces and a quote in the directory to exercise shell assignment quoting.
        cfg = os.path.join(f.app, ".claude", "owner's config", "stu.md")
        fixtures.write(cfg, fixtures.read(f.cfg))
        os.remove(f.cfg)
        # Both runtimes use .claude/stu.md; a symlink retains the quoting fixture.
        shared = os.path.join(f.app, ".claude", "stu.md")
        os.symlink(cfg, shared)
        return cfg

    def install_codex(self, f):
        return subprocess.run([fixtures.PRE_PUSH, "--install", "--path", f.app],
                              env=dict(f.env, STU_RUNTIME="codex"),
                              capture_output=True, text=True)

    def test_shared_config_human_push_still_scans_private_names(self):
        with fixtures.fam() as f:
            self.shared_config(f)
            self.assertEqual(self.install_codex(f).returncode, 0)
            clean = fixtures.commit(f.app, f.env, msg="clean work")
            result = f.push(f.app, "origin", "main")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(f.remote_ref(f.app_remote), clean)
            fixtures.commit(f.app, f.env, msg="mentions acme/lib private work")
            result = f.push(f.app, "origin", "main")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("private-repo item", result.stderr)
            self.assertEqual(f.remote_ref(f.app_remote), clean)

    def test_shared_config_marked_push_needs_approval_without_runtime_env(self):
        with fixtures.fam() as f:
            self.shared_config(f)
            self.assertEqual(self.install_codex(f).returncode, 0)
            tip = fixtures.commit(f.app, f.env, msg="agent work")
            for marker in ("CODEX_THREAD_ID", "CODEX_SHELL"):
                result = fixtures.git(f.app, dict(f.env, **{marker: "1"}), "push",
                                      "origin", "main", ok_fail=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(tip + " is not approved", result.stderr)

    def test_codex_binding_does_not_reach_chained_hook(self):
        with fixtures.fam() as f:
            self.shared_config(f)
            local = os.path.join(f.app, ".git", "hooks", "pre-push")
            seen = os.path.join(f.tmp, "local-env")
            fixtures.write(local, '#!/bin/sh\nprintf "%s|%s" "$STU_RUNTIME" "$STU_CONFIG" > "' +
                           seen + '"\ncat > /dev/null\n')
            os.chmod(local, 0o755)
            self.assertEqual(self.install_codex(f).returncode, 0)
            fixtures.commit(f.app, f.env, msg="human work")
            self.assertEqual(f.push(f.app, "origin", "main").returncode, 0)
            self.assertEqual(fixtures.read(seen), "|")

    def test_bound_hook_check_and_missing_config_fail_closed(self):
        with fixtures.fam() as f:
            cfg = self.shared_config(f)
            self.assertEqual(self.install_codex(f).returncode, 0)
            result = subprocess.run([fixtures.PRE_PUSH, "--check", "--path", f.app], env=f.env,
                                    capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (0, "INSTALLED"), result.stderr)
            os.remove(cfg)
            fixtures.commit(f.app, f.env, msg="human work")
            self.assertNotEqual(f.push(f.app, "origin", "main").returncode, 0)
            result = subprocess.run([fixtures.PRE_PUSH, "--check", "--path", f.app], env=f.env,
                                    capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (1, "MISSING"))

    def test_check_rejects_old_unbound_codex_hook(self):
        with fixtures.fam() as f:
            # Install the legacy generic hook first, then require a Codex config binding.
            self.assertEqual(f.install(f.app).returncode, 0)
            self.shared_config(f)
            result = subprocess.run([fixtures.PRE_PUSH, "--check", "--path", f.app],
                                    env=dict(f.env, STU_RUNTIME="codex"),
                                    capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (1, "MISSING"))

    def test_pinned_external_config_controls_unmarked_human_pushes(self):
        with fixtures.fam() as f:
            f.env = {k: v for k, v in f.env.items() if not k.startswith("STU_")}
            selected = os.path.join(f.tmp, "selected owner's policy", "stu.md")
            fixtures.write(selected, fixtures.read(f.cfg))
            # The default config permits pushing; the explicitly selected policy scans.
            fixtures.write(f.cfg, fixtures.fam_text(f.app, f.lib, app_over={
                "visibility": "private", "human_checkpoints": None}))
            installed = subprocess.run([fixtures.PRE_PUSH, "--install", "--path", f.app],
                                       env=dict(f.env, STU_RUNTIME="codex", STU_CONFIG=selected),
                                       capture_output=True, text=True)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            clean = fixtures.commit(f.app, f.env, msg="clean work")
            pushed = f.push(f.app, "origin", "main")
            self.assertEqual(pushed.returncode, 0, pushed.stderr)
            self.assertEqual(f.remote_ref(f.app_remote), clean)
            fixtures.commit(f.app, f.env, msg="mentions acme/lib private work")
            pushed = f.push(f.app, "origin", "main")
            self.assertNotEqual(pushed.returncode, 0)
            self.assertIn("private-repo item", pushed.stderr)
            self.assertEqual(f.remote_ref(f.app_remote), clean)

    def test_codex_check_requires_binding_for_explicit_external_config(self):
        with fixtures.fam() as f:
            self.assertEqual(f.install(f.app).returncode, 0)
            config = os.path.join(f.tmp, "chosen", "stu.md")
            fixtures.write(config, fixtures.read(f.cfg))
            result = subprocess.run([fixtures.PRE_PUSH, "--check", "--path", f.app],
                                    env=dict(f.env, STU_RUNTIME="codex", STU_CONFIG=config),
                                    capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (1, "MISSING"))

    def test_codex_check_rejects_binding_to_a_different_selected_config(self):
        with fixtures.fam() as f:
            self.assertEqual(self.install_codex(f).returncode, 0)
            config = os.path.join(f.tmp, "chosen", "stu.md")
            fixtures.write(config, fixtures.read(f.cfg))
            result = subprocess.run([fixtures.PRE_PUSH, "--check", "--path", f.app],
                                    env=dict(f.env, STU_RUNTIME="codex", STU_CONFIG=config),
                                    capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (1, "MISSING"))

    def test_default_hook_check_ignores_unused_neutral_path(self):
        with fixtures.fam() as f:
            self.assertEqual(f.install(f.app).returncode, 0)
            fixtures.write(os.path.join(f.app, ".stu", "stu.md"), "unused config path\n")
            result = subprocess.run([fixtures.PRE_PUSH, "--check", "--path", f.app], env=f.env,
                                    capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout.strip()), (0, "INSTALLED"))

    def test_human_fixtures_strip_all_agent_markers(self):
        with tempfile.TemporaryDirectory() as home:
            with fixtures.inproc(dict(os.environ, CLAUDECODE="1", CODEX_THREAD_ID="t",
                                      CODEX_SHELL="1", CODEX_TEST_SESSION="inherited")):
                env = fixtures.env_for(home)
            for key in ("CLAUDECODE", "CODEX_THREAD_ID", "CODEX_SHELL", "CODEX_TEST_SESSION"):
                self.assertFalse(key in env, key + " leaked into the human fixture")

    def test_codex_push_requires_approval_for_each_marker(self):
        for marker in ("CODEX_THREAD_ID", "CODEX_SHELL"):
            with self.subTest(marker=marker), fixtures.fam() as f:
                self.assertEqual(f.install(f.app).returncode, 0)
                sha = fixtures.commit(f.app, f.env, msg="Codex work")
                before = f.remote_ref(f.app_remote)
                env = dict(f.env, **{marker: "test"})
                denied = fixtures.git(f.app, env, "push", "origin", "main", ok_fail=True)
                self.assertNotEqual(denied.returncode, 0)
                self.assertIn("not approved", denied.stderr)
                self.assertIn(sha, denied.stderr)
                self.assertEqual(f.remote_ref(f.app_remote), before)
                self.assertEqual(f.approve(sha).returncode, 0)
                allowed = fixtures.git(f.app, env, "push", "origin", "main", ok_fail=True)
                self.assertEqual(allowed.returncode, 0, allowed.stderr)
                self.assertEqual(f.remote_ref(f.app_remote), sha)

    def test_empty_codex_markers_allow_human_push(self):
        with fixtures.fam() as f:
            self.assertEqual(f.install(f.app).returncode, 0)
            sha = fixtures.commit(f.app, f.env, msg="human work")
            result = fixtures.git(f.app, dict(f.env, CODEX_THREAD_ID="", CODEX_SHELL=""),
                                  "push", "origin", "main", ok_fail=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(f.remote_ref(f.app_remote), sha)
            self.assertIn("skipped", result.stderr)

    def test_patch_approval_targets_denied(self):
        with fixtures.fam() as f:
            fixtures.write(f.approvals, "owner record\n")
            alias = os.path.join(f.app, "owner-record")
            os.symlink(f.approvals, alias)
            for target in ("approvals.tsv", f.approvals, "owner-record", alias):
                for operation in ("Add File", "Update File", "Delete File", "Move to"):
                    header = ("*** Update File: ordinary.txt\n*** Move to: " + target
                              if operation == "Move to" else "*** %s: %s" % (operation, target))
                    patch = "*** Begin Patch\n%s\n+record\n*** End Patch" % header
                    with self.subTest(target=target, operation=operation):
                        pl = fixtures.payload("apply_patch", f.app, command=patch)
                        self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))
            pl = fixtures.payload("functions.apply_patch", f.app, command=(
                "*** Begin Patch\n*** Delete File: owner-record\n*** End Patch"))
            self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))
            self.assertEqual(fixtures.read(f.approvals), "owner record\n")

    def test_patch_input_shapes_cannot_edit_approvals(self):
        with fixtures.fam() as f:
            patch = "*** Begin Patch\n*** Add File: .claude/approvals.tsv\n+x\n*** End Patch"
            inputs = [("raw", patch), ("empty-command", {"command": "", "input": patch})]
            inputs += [(key, {key: patch}) for key in ("command", "input", "patch")]
            for name, tool_input in inputs:
                with self.subTest(shape=name):
                    pl = fixtures.payload("apply_patch", f.app)
                    pl["tool_input"] = tool_input
                    self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))

    def test_patch_header_whitespace_cannot_mask_approval_paths(self):
        with fixtures.fam() as f:
            for operation in ("Add File", "Update File", "Delete File", "Move to"):
                with self.subTest(operation=operation):
                    patch = "*** Begin Patch\n*** %s:  .claude/APPROVALS.TSV \t\n*** End Patch" % operation
                    pl = fixtures.payload("apply_patch", f.app, command=patch)
                    self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))

    def test_all_patch_text_fields_are_checked(self):
        with fixtures.fam() as f:
            clean = "*** Begin Patch\n*** Add File: ordinary.txt\n+x\n*** End Patch"
            protected = "*** Begin Patch\n*** Delete File: approvals.tsv\n*** End Patch"
            for field in ("command", "input", "patch"):
                with self.subTest(protected_field=field):
                    ti = {key: clean for key in ("command", "input", "patch")}
                    ti[field] = protected
                    pl = fixtures.payload("apply_patch", f.app, **ti)
                    self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))

    def test_unknown_patch_shape_falls_back_to_approval_filename(self):
        with fixtures.fam() as f:
            for ti in ({"future": {"path": "APPROVALS.TSV"}},
                       {"command": None, "patch": {"path": "approvals.tsv"}},
                       {"command": " \t", "future": "approvals.tsv"},
                       ["approvals.tsv"]):
                with self.subTest(tool_input=ti):
                    pl = fixtures.payload("apply_patch", f.app)
                    pl["tool_input"] = ti
                    self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))

    def test_unrelated_patch_and_unknown_no_hit_shapes_are_allowed(self):
        with fixtures.fam() as f:
            clean = "*** Begin Patch\n*** Add File: approvals.py\n+x\n*** End Patch"
            for ti in (clean, {"input": clean}, {"patch": clean},
                       {"future": "approvals.py"}, {"command": None}, None):
                with self.subTest(tool_input=ti):
                    pl = fixtures.payload("apply_patch", f.app)
                    pl["tool_input"] = ti
                    self.assertTrue(fixtures.allowed(pl, f.env), fixtures.verdict(pl, f.env))

    def test_patch_crlf_approval_target_denied(self):
        with fixtures.fam() as f:
            patch = "*** Begin Patch\r\n*** Add File: approvals.tsv\r\n+x\r\n*** End Patch"
            pl = fixtures.payload("apply_patch", f.app, command=patch)
            self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))

    def test_ordinary_patch_content_is_allowed(self):
        with fixtures.fam() as f:
            patch = ("*** Begin Patch\n*** Add File: docs/approval-guide.md\n"
                     "+The owner writes approvals.tsv.\n*** End Patch")
            self.assertTrue(fixtures.allowed(fixtures.payload("apply_patch", f.app,
                                                              command=patch), f.env))
            self.assertTrue(fixtures.allowed(fixtures.payload("apply_patch", f.tmp,
                command="*** Begin Patch\n*** Delete File: ordinary.txt\n*** End Patch"), f.env))

    def test_direct_exec_command_has_shell_checks(self):
        with fixtures.fam() as f:
            for cmd in ("stu-approve app#1 HEAD", "git push --no-verify origin main"):
                pl = fixtures.payload("exec_command", f.app, cmd=cmd)
                self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))
            self.assertTrue(fixtures.allowed(fixtures.payload("exec_command", f.tmp,
                cmd="git push --no-verify origin main"), f.env))
            self.assertTrue(fixtures.allowed(fixtures.payload("exec_command", f.app,
                cmd="git status"), f.env))

    def test_exec_workdir_identifies_strict_repo(self):
        with fixtures.fam() as f:
            for tool in ("exec_command", "functions.exec_command"):
                pl = fixtures.payload(tool, f.tmp, cmd="git push --no-verify origin main",
                                      workdir=f.app)
                self.assertTrue(fixtures.denied(pl, f.env), fixtures.verdict(pl, f.env))


if __name__ == "__main__":
    unittest.main()
