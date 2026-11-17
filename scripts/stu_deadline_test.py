#!/usr/bin/env python3
"""Tests for stu_deadline. The clock is injected by patching time.time / time.sleep in
process, so no test sleeps for real."""
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stu_deadline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class Clock:
    """Wall clock and a separate awake-time counter. sleep() advances both by default;
    system_sleep(n) advances only the wall clock (a Mac asleep)."""
    def __init__(self, start=1_000_000.0):
        self.wall = start
        self.awake_sleeps = 0
        self.log = []

    def time(self):
        return self.wall

    def sleep(self, n):
        self.log.append(n)
        self.wall += n
        if self.jump:
            self.wall += self.jump
            self.jump = 0

    jump = 0


def run(clock, argv):
    out = io.StringIO()
    with mock.patch.object(stu_deadline.time, 'time', clock.time), \
            mock.patch.object(stu_deadline.time, 'sleep', clock.sleep), redirect_stdout(out):
        code = stu_deadline.main(argv)
    return code, out.getvalue()


class DeadlineTest(unittest.TestCase):
    def test_fires_after_wall_clock_jump_and_reports_late(self):
        c = Clock()
        c.jump = 8 * 3600  # the machine slept 8 h during the first poll
        code, out = run(c, ['--seconds', '5400', '--label', 'orch'])
        self.assertEqual(code, 0)
        self.assertEqual(len(c.log), 1)  # fired on the first wake, not after 5400 s of sleeps
        fired = [l for l in out.splitlines() if ' fired at ' in l][0]
        self.assertTrue(fired.startswith('deadline orch fired at '))
        self.assertIn('late %ds)' % (30 + 8 * 3600 - 5400), fired)

    def test_does_not_fire_before_due(self):
        c = Clock()
        code, out = run(c, ['--seconds', '100', '--label', 'x'])
        self.assertEqual(code, 0)
        # every poll but the last happened while wall < due; total slept is exactly 100
        self.assertEqual(sum(c.log), 100)
        self.assertEqual(c.log, [30, 30, 30, 10])
        self.assertIn('late 0s)', out)

    def test_partial_wall_clock_jump_does_not_fire_early(self):
        c = Clock()
        c.jump = 20  # a short nap during the first poll: wall is 50 s in, due at 100 s
        code, out = run(c, ['--seconds', '100', '--label', 'x'])
        self.assertEqual(code, 0)
        # not fired after the jump (that would be 1 sleep); it polls on and fires once due
        self.assertEqual(c.log, [30, 30, 20])
        self.assertEqual(out.count(' fired at '), 1)
        self.assertIn('late 0s)', out)

    def test_start_line_prints_armed_and_due(self):
        c = Clock()
        _, out = run(c, ['--seconds', '60', '--label', 'x'])
        first = out.splitlines()[0]
        self.assertIn('armed 1970-01-12T13:46:40Z due 1970-01-12T13:47:40Z', first)

    def test_bad_arguments_exit_2(self):
        for argv in ([], ['--seconds', '5'], ['--label', 'x'], ['--seconds', 'abc', '--label', 'x'],
                     ['--seconds', '0', '--label', 'x'], ['--seconds', '-3', '--label', 'x'],
                     ['--seconds', '5', '--label', ' ']):
            with self.subTest(argv=argv), mock.patch('sys.stderr', io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    stu_deadline.main(argv)
                self.assertEqual(cm.exception.code, 2)

    def test_wrapper_bad_args_exit_2(self):
        r = subprocess.run([str(ROOT / 'bin/stu-deadline')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_wrapper_is_executable(self):
        self.assertTrue(os.access(ROOT / 'bin/stu-deadline', os.X_OK))


if __name__ == '__main__':
    unittest.main()
