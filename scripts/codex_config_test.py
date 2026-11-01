#!/usr/bin/env python3
"""Option (b): share Claude's config paths; only guide preference depends on runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class CodexConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.repo.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('GIT_', 'STU_', 'CLAUDE', 'CODEX'))}
        self.env.update(HOME=str(self.home), GIT_CONFIG_NOSYSTEM='1', STU_RUNTIME='codex')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, env=self.env)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.com', 'commit', '--allow-empty',
                        '-qm', 'init'], check=True, env=self.env)
        (self.repo / 'CLAUDE.md').write_text('Claude guide\n')
        (self.repo / 'AGENTS.md').write_text('Agent guide\n')

    def config(self, folder, owner='shared'):
        path = self.repo / folder / 'stu.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\nowner: ' + owner + '\nproject: fixture\nbase: main\n---\n')
        return path

    def runtime_env(self, **extra):
        env = dict(self.env)
        for key, value in extra.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run_env(self, **extra):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/stu_env.py'),
                                 '--defaults', '--json'], cwd=self.repo,
                                env=self.runtime_env(**extra), text=True, capture_output=True)
        return result, json.loads(result.stdout) if result.returncode == 0 else {}

    def test_codex_reads_shared_config_and_agents_guide(self):
        config = self.config('.claude')
        result, out = self.run_env()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(out['CONFIG_PATH'], str(config.resolve()))
        self.assertEqual(out['PROJECT_GUIDE'], 'AGENTS.md')

    def test_codex_created_public_config_is_visible_when_runtime_unset(self):
        # Option (b) retains the canonical init location, so Claude's unmarked hooks
        # discover the same strict row without a new lookup rule or pinned environment.
        config = self.config('.claude')
        config.write_text(config.read_text().replace('base: main',
                                                    'base: main\nvisibility: public'))
        for runtime in ('codex', None):
            with self.subTest(runtime=runtime):
                result, out = self.run_env(STU_RUNTIME=runtime)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(out['CONFIG_PATH'], str(config.resolve()))
                self.assertEqual(out['VISIBILITY'], 'public')
                self.assertEqual(out['PROJECT_GUIDE'],
                                 'AGENTS.md' if runtime == 'codex' else 'CLAUDE.md')

    def test_repo_stu_directory_is_not_an_implicit_config(self):
        self.config('.stu')
        for runtime in ('codex', None):
            with self.subTest(runtime=runtime):
                result, out = self.run_env(STU_RUNTIME=runtime)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(out['CONFIG_PATH'], '')

    def test_shared_config_is_not_ambiguous_with_unrecognized_local_path(self):
        self.config('.stu', 'unused')
        shared = self.config('.claude')
        for runtime in ('codex', None):
            with self.subTest(runtime=runtime):
                result, out = self.run_env(STU_RUNTIME=runtime)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(out['CONFIG_PATH'], str(shared.resolve()))
                self.assertEqual(out['OWNER'], 'shared')

    def test_family_discovery_uses_same_shared_config_in_both_runtimes(self):
        self.config('.stu', 'unused')
        shared = self.config('.claude')
        code = ('import json, sys; sys.path.insert(0, sys.argv[1]); '
                'import stu_env; print(json.dumps(stu_env.families()))')
        for runtime in ('codex', None):
            with self.subTest(runtime=runtime):
                result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'scripts')],
                                        cwd=self.repo, env=self.runtime_env(STU_RUNTIME=runtime),
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([row[0] for row in json.loads(result.stdout)],
                                 [str(shared.resolve())])

    def test_external_explicit_config_still_overrides_shared_location(self):
        self.config('.claude')
        config = self.home / 'external.md'
        config.write_text('---\nowner: external\nproject: fixture\nbase: main\n---\n')
        for runtime in ('codex', None):
            with self.subTest(runtime=runtime):
                result, out = self.run_env(STU_RUNTIME=runtime, STU_CONFIG=str(config))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(out['CONFIG_PATH'], str(config.resolve()))
                self.assertEqual(out['OWNER'], 'external')

    def test_explicit_guide_is_preserved(self):
        config = self.config('.claude')
        config.write_text('---\nowner: shared\nguide: CUSTOM.md\n---\n')
        result, out = self.run_env()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(out['PROJECT_GUIDE'], 'CUSTOM.md')

    def test_unmarked_runtime_stays_claude_even_inside_codex_shell(self):
        shared = self.config('.claude')
        result, out = self.run_env(STU_RUNTIME=None, CODEX_THREAD_ID='inherited-marker')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(out['CONFIG_PATH'], str(shared.resolve()))
        self.assertEqual(out['PROJECT_GUIDE'], 'CLAUDE.md')


if __name__ == '__main__':
    unittest.main()
