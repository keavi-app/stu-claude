.PHONY: test test-python test-shell

# Both runtime adapters and the shared core use only the standard library.
test: test-python test-shell
	python3 tests/python_floor.py

test-python:
	@set -e; for suite in scripts/*_test.py; do echo "Running $$suite"; python3 "$$suite"; done

test-shell:
	@set -e; for suite in tests/*_test.sh; do echo "Running $$suite"; bash "$$suite"; done
