#!/usr/bin/env python3
"""stu-deadline: a liveness deadline timer that runs on wall-clock time.

Usage: stu-deadline --seconds N --label TEXT

Prints the armed and due times, then wakes every 30 s and compares time.time() with the due
epoch. Plain `sleep N` counts only awake time on macOS, so a Mac that slept overnight never
fires it; the wall clock advances across system sleep, so this fires at the first wake after
the due time. On fire it exits 0 and prints one line:
  deadline <label> fired at <ISO> (armed <ISO>, late <s>s)
Bad arguments exit 2. Python 3.9, standard library only.
"""
import argparse
import sys
import time
from datetime import datetime, timezone

POLL_SECONDS = 30


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write('stu-deadline: ' + message + '\n')
        raise SystemExit(2)


def main(argv=None):
    p = _Parser(prog='stu-deadline')
    p.add_argument('--seconds', type=int, required=True)
    p.add_argument('--label', required=True)
    args = p.parse_args(argv)
    if args.seconds <= 0 or not args.label.strip():
        p.error('--seconds must be positive and --label non-empty')
    armed = time.time()
    due = armed + args.seconds
    print('deadline %s armed %s due %s' % (args.label, iso(armed), iso(due)), flush=True)
    while True:
        now = time.time()
        if now >= due:
            print('deadline %s fired at %s (armed %s, late %ds)'
                  % (args.label, iso(now), iso(armed), int(now - due)), flush=True)
            return 0
        time.sleep(min(POLL_SECONDS, max(due - now, 0)))


if __name__ == '__main__':
    sys.exit(main())
