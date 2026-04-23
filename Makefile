# Load .env only for targets that actually need the secrets (e.g. `run`),
# so `make test` doesn't pull API keys into the test environment.
# Sources .env if present, no-op otherwise.
LOAD_ENV := set -a; [ -f .env ] && . ./.env; set +a;

REQUIRED_PYTHON_MINOR := 10
PYTHON_VERSION := $(shell python3 -c 'import sys; print(sys.version_info.minor)')

.PHONY: run test build clean check-python

check-python:
	@if [ "$(PYTHON_VERSION)" -lt "$(REQUIRED_PYTHON_MINOR)" ]; then \
		echo "Error: Python 3.$(REQUIRED_PYTHON_MINOR)+ is required (found 3.$(PYTHON_VERSION))"; \
		exit 1; \
	fi

.venv: check-python
	python3 -m venv .venv
	.venv/bin/pip install --no-build-isolation -r requirements.txt

node_modules:
	npm ci

build: node_modules
	npm run build

run: .venv build
	$(LOAD_ENV) PYTHONPATH=src .venv/bin/python src/main.py

test: .venv
	PYTHONPATH=src .venv/bin/python -m pytest tests/ -v

clean:
	rm -rf .venv node_modules web/js/bundle.js web/js/bundle.js.map
