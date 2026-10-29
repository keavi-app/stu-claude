#!/usr/bin/env python3
"""Floor check: every scripts/*.py and tests/*.py must parse as Python 3.9.

Exits 1 naming each file that uses a newer construct. Run: python3 tests/python_floor.py
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    bad, count = [], 0
    for pattern in ("scripts/*.py", "tests/*.py"):
        for path in sorted(glob.glob(os.path.join(ROOT, pattern))):
            count += 1
            with open(path, encoding="utf-8") as f:
                src = f.read()
            try:
                ast.parse(src, filename=path, feature_version=(3, 9))
            except SyntaxError as e:
                bad.append("%s:%s: %s" % (os.path.relpath(path, ROOT), e.lineno, e.msg))
    if bad:
        print("FAIL python floor 3.9:")
        for b in bad:
            print("  " + b)
        return 1
    print("ok: %d files parse as Python 3.9" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
