# Load .env (API keys etc.) into the environment for local runs
-include .env
export

.PHONY: run test build clean

.venv:
	python3 -m venv .venv
	.venv/bin/pip install --no-build-isolation -r requirements.txt

node_modules:
	npm ci

build: node_modules
	npm run build

run: .venv build
	PYTHONPATH=src .venv/bin/python src/main.py

test: .venv
	PYTHONPATH=src .venv/bin/python -m pytest tests/ -v

clean:
	rm -rf .venv node_modules web/js/bundle.js web/js/bundle.js.map
