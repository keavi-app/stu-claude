#!/usr/bin/env python3
"""Exercise Codex config lookup without altering Claude's lookup contract."""
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
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('GIT_', 'STU_', 'CLAUDE', 'CODEX'))}
        self.env.update(HOME=str(self.home), GIT_CONFIG_NOSYSTEM='1', STU_RUNTIME='codex')
        subprocess.run(['git','init','-q',str(self.repo)],check=True,env=self.env)
        subprocess.run(['git','-C',str(self.repo),'-c','user.name=Test','-c','user.email=test@example.com','commit','--allow-empty','-qm','init'],check=True,env=self.env)
        (self.repo/'CLAUDE.md').write_text('Claude guide\n')
        (self.repo/'AGENTS.md').write_text('Agent guide\n')
    def config(self, folder, owner='shared'):
        p=self.repo/folder/'stu.md'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('---\nowner: '+owner+'\nproject: fixture\nbase: main\n---\n')
        return p
    def run_env(self, **extra):
        env=dict(self.env, **extra)
        p=subprocess.run([sys.executable,str(ROOT/'scripts/stu_env.py'),'--defaults','--json'],cwd=self.repo,env=env,text=True,capture_output=True)
        return p, json.loads(p.stdout) if p.returncode==0 else {}
    def test_codex_reads_neutral_config_and_agents_guide(self):
        config=self.config('.stu')
        p,out=self.run_env()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(out['CONFIG_PATH'],str(config.resolve()))
        self.assertEqual(out['PROJECT_GUIDE'],'AGENTS.md')
    def test_claude_keeps_legacy_lookup_and_guide(self):
        self.config('.stu','neutral')
        legacy=self.config('.claude','legacy')
        p,out=self.run_env(STU_RUNTIME='claude')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(out['CONFIG_PATH'],str(legacy.resolve()))
        self.assertEqual(out['PROJECT_GUIDE'],'CLAUDE.md')
    def test_codex_reuses_existing_claude_config(self):
        legacy=self.config('.claude')
        p,out=self.run_env()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(out['CONFIG_PATH'],str(legacy.resolve()))
    def test_codex_conflicting_configs_require_explicit_selection(self):
        self.config('.stu')
        legacy=self.config('.claude')
        p,_=self.run_env()
        self.assertEqual(p.returncode,3)
        self.assertIn('STU_CONFIG',p.stderr)
        p,out=self.run_env(STU_CONFIG=str(legacy))
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(out['CONFIG_PATH'],str(legacy.resolve()))
    def test_explicit_guide_is_preserved(self):
        config=self.config('.stu')
        config.write_text('---\nowner: shared\nguide: CUSTOM.md\n---\n')
        p,out=self.run_env()
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(out['PROJECT_GUIDE'],'CUSTOM.md')
    def test_unmarked_runtime_stays_claude_even_inside_codex_shell(self):
        self.config('.stu')
        legacy=self.config('.claude')
        p,out=self.run_env(STU_RUNTIME='', CODEX_THREAD_ID='inherited-marker')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(out['CONFIG_PATH'],str(legacy.resolve()))
        self.assertEqual(out['PROJECT_GUIDE'],'CLAUDE.md')

if __name__ == '__main__':
    unittest.main()
