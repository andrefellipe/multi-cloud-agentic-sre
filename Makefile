# Developer and CI entry points. The python-quality workflow runs these same
# targets, so `make lint typecheck coverage` locally matches the PR check.
# Source folders that do not exist yet are skipped, so every target works from
# the first PR on. Unit-scoped commands are in each unit's unit-test-instructions.md.

PYTHON_SOURCES := $(wildcard agents tools/ci tools/lab tools/build tools/skeleton tools/spikes)
PYTHON_LINT_PATHS := $(PYTHON_SOURCES) $(wildcard tests)

.PHONY: lint typecheck test-u1 coverage package

# Ruff lint and format check (REQ-150.1).
lint:
	uv run ruff check $(PYTHON_LINT_PATHS)
	uv run ruff format --check $(PYTHON_LINT_PATHS)

# mypy in strict mode with the Pydantic plugin (REQ-150.1).
typecheck:
	uv run mypy $(PYTHON_SOURCES)

# u1's tests only.
test-u1:
	uv run pytest tests/u1 -q

# Every test, held to the 80% line coverage floor set in pyproject.toml (REQ-150.1).
coverage:
	uv run pytest --cov --cov-report=term-missing

# Reproducible function and runtime packages with a SHA-256 manifest (plan Step 29).
package:
	@if [ -f tools/build/package.py ]; then \
		uv run python tools/build/package.py; \
	else \
		echo "package: tools/build/package.py is not here yet (plan Step 29); nothing to build."; \
	fi
