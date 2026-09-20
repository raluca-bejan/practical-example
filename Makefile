PYTHON ?= python3
VENV := .venv
PY := $(VENV)/bin/python
TRACE ?= docs/demo-invoice-txt.jsonl
SCHEMA ?= schemas/invoice.schema.json
JUDGE_OUTPUT ?= testing/output
EVALUATIONS ?= testing/adversarial_examples/observed/results.json

.PHONY: setup setup-tests run test test_llm propose_improvements demo demo-json package package-tests package-changes

setup:
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -r requirements.txt

run:
	$(PY) -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false

setup-tests:
	$(PY) -m pip install -r testing/requirements.txt

test:
	$(PY) -m pytest -q

test_llm:
	$(PY) testing/llm_judge.py --trace "$(TRACE)" --schema "$(SCHEMA)" --env-file .env --output-dir "$(JUDGE_OUTPUT)"

propose_improvements:
	$(PY) testing/improvement_proposals.py "$(EVALUATIONS)"

demo:
	$(PY) scripts/demo.py

demo-json:
	$(PY) -m invoice_agent samples/invoice.json

package:
	$(PY) scripts/package.py

package-tests:
	$(PY) scripts/package.py --tests

package-changes:
	$(PY) scripts/package.py --changes
