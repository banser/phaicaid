.PHONY: test lint typecheck format coverage clean

PYTHON ?= python3
VENV_PY = .phaicaid/venv/bin/python

test:
	$(PYTHON) -m pytest tests/ -v

coverage:
	$(PYTHON) -m pytest tests/ --cov --cov-report=term-missing --cov-report=html

lint:
	$(PYTHON) -m ruff check templates/pydaemon/ tests/

typecheck:
	$(PYTHON) -m mypy templates/pydaemon/phaicaid/

format:
	$(PYTHON) -m ruff format templates/pydaemon/ tests/
	$(PYTHON) -m ruff check --fix templates/pydaemon/ tests/

clean:
	rm -rf .pytest_cache htmlcov .coverage .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
