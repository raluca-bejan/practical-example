PYTHON ?= python3
PY := .venv/bin/python
APP_DIR ?= ..
TRACE ?= $(APP_DIR)/docs/demo-invoice-txt.jsonl
SCHEMA ?= $(APP_DIR)/schemas/invoice.schema.json
ENV_FILE ?= $(APP_DIR)/.env
OUTPUT ?= output

.PHONY: setup test test_llm

setup:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -r requirements.txt

test:
	$(PY) -m pytest -q test_llm_judge.py

test_llm:
	$(PY) llm_judge.py --trace "$(TRACE)" --schema "$(SCHEMA)" --env-file "$(ENV_FILE)" --output-dir "$(OUTPUT)"
