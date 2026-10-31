#!/usr/bin/env python3
"""Contract adapter regressions, independent of a running Codex session."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def adapter():
    spec = importlib.util.spec_from_file_location('stu_codex', ROOT / 'scripts/stu_codex.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Contracts(unittest.TestCase):
    def test_every_contract_renders_and_has_native_runtime(self):
        module = adapter()
        for name in module.SOURCES:
            with self.subTest(name=name):
                result = module.render(name, ROOT)
                self.assertIn('collaboration.spawn_agent', result)
                self.assertIn('fork_turns: "none"', result)
                self.assertIn('STU_RUNTIME=codex', result)
                self.assertNotIn('${CLAUDE_PLUGIN_ROOT}', result)
                self.assertNotIn('$PATH=', result)
                self.assertNotIn('$stu-run', result)
                self.assertNotIn('$stu-settle', result)
                self.assertNotIn('`Edit` and `Write` are blocked', result)
                self.assertNotIn('**You have no `Write` or `Edit`', result)
                self.assertNotIn('! "<plugin root>', result)
                self.assertNotIn('<plugin root>', result)
                for forbidden in ('subagent_type:', 'run_in_background', 'TaskStop', 'SendMessage',
                                  'ListAgents', 'claude -p', 'sleep 5400', 'maxTurns', 'cacheTtl',
                                  'model: "opus"', 'model: "sonnet"', 'model: haiku'):
                    self.assertNotIn(forbidden, result)

    def test_common_run_checks_are_not_forked(self):
        module = adapter()
        original = (ROOT / 'skills/run/SKILL.md').read_text()
        common = original.split('### Fail-closed checks — all five, every return\n', 1)[1]
        common = common.split('### One repair request, then fail closed\n', 1)[0]
        rendered = module.render('run', ROOT)
        self.assertIn(module.bind(common, ROOT), rendered)
        for field in ('PREMISE_CLAIM:', 'INTEGRATED_IDS:', 'AFTER_PASS_FAILED:', 'APPROVAL_IDS:'):
            self.assertIn(field, rendered)

    def test_gate_return_is_retained(self):
        module = adapter()
        original = (ROOT / 'agents/merge-gate.md').read_text()
        common = original.split('## Return contract\n', 1)[1]
        self.assertIn(module.bind(common, ROOT), module.render('merge-gate', ROOT))

    def test_live_canonical_edits_are_reflected_and_runtime_drift_fails_closed(self):
        module = adapter()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'copy with spaces'
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            source = root / 'agents/reviewer.md'
            source.write_text(source.read_text() + '\nCANONICAL SENTINEL: new evidence rule.\n')
            self.assertIn('CANONICAL SENTINEL: new evidence rule.', module.render('reviewer', root))
            source = root / 'skills/run/SKILL.md'
            source.write_text(source.read_text().replace('### Liveness: one deadline timer per dispatch, not a poll',
                                                        '### Liveness: changed runtime'))
            with self.assertRaises(module.ContractDrift):
                module.render('run', root)
            source.write_text((ROOT / 'skills/run/SKILL.md').read_text().replace(
                '### Liveness: one deadline timer per dispatch, not a poll\n',
                '### Liveness: one deadline timer per dispatch, not a poll\nNEW POLICY: do not silently discard.\n'))
            with self.assertRaises(module.ContractDrift):
                module.render('run', root)

    def test_helper_works_from_another_repo_and_space_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'package with spaces'
            for directory in ('scripts', 'bin', 'codex', 'skills', 'agents'):
                shutil.copytree(ROOT / directory, root / directory,
                                ignore=shutil.ignore_patterns('__pycache__'))
            other = Path(tmp) / 'other repository'
            other.mkdir()
            result = subprocess.run([str(root / 'bin/stu-codex'), 'contract', 'reviewer'],
                                    cwd=other, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(root), result.stdout)
            self.assertIn('exact SHA', result.stdout)
            self.assertIn('STU_RUNTIME=codex', result.stdout)

    def test_native_runtime_and_command_boundaries(self):
        module = adapter()
        result = module.render('run', ROOT)
        self.assertIn('Next: $stu:settle', result)
        self.assertIn('stu_orchestrator_cycle_2', result)
        self.assertIn('live concurrency slot cap', result)
        self.assertIn('six hours', result)
        self.assertIn('final 90-minute', result)
        self.assertIn('permissions', result)
        prefix = 'PATH=' + str(ROOT / 'bin') + ':$PATH STU_RUNTIME=codex '
        self.assertIn(prefix + 'stu-env', result)
        self.assertEqual(module.bind('`Next: /stu:run "resume"`', ROOT), '`Next: $stu:run "resume"`')
        self.assertEqual(module.bind('`stu-env\n --repo home`', ROOT), '`' + prefix + 'stu-env\n --repo home`')

    def test_codex_startup_reports_known_private_plan_limit_as_unknown(self):
        module = adapter()
        command = 'stu-forge repo-settings --slug <REPO_SLUG> --base <the row\'s BASE>'
        canonical = (ROOT / 'skills/run/SKILL.md').read_text()
        self.assertIn('`' + command + '`', canonical)
        self.assertNotIn('--allow-unavailable-rules', canonical)
        rendered = module.render('run', ROOT)
        self.assertIn(command + ' --allow-unavailable-rules', rendered)
        self.assertIn('known GitHub Free private-repository plan limitation', rendered)
        self.assertIn('unknown, never disabled', rendered)
        self.assertIn('Authentication, rate-limit and partial-data errors still stop', rendered)

    def test_doctor_reports_manual_trust_without_claiming_it(self):
        result = subprocess.run([str(ROOT / 'bin/stu-codex'), 'doctor'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Contract root: ' + str(ROOT), result.stdout)
        self.assertIn('Codex version:', result.stdout)
        self.assertIn('Context telemetry:', result.stdout)
        self.assertIn('Hook trust: MANUAL', result.stdout)
        self.assertIn('manifest presence is not trust', result.stdout)

    def test_skill_wrappers_resolve_install_root(self):
        for name in ('init', 'run', 'settle', 'fix-campaign'):
            wrapper = ROOT / 'codex/skills' / name / 'SKILL.md'
            text = wrapper.read_text()
            self.assertIn('parents[3]', text)
            self.assertIn('name: ' + name + '\n', text)
            self.assertNotIn('name: stu-', text)
            self.assertFalse((ROOT / 'codex/skills' / ('stu-' + name)).exists())
            self.assertIn('contract ' + name, text)
            self.assertIn('absolute', text)


if __name__ == '__main__':
    unittest.main()
