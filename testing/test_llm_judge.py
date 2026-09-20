from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from testing.llm_judge import dumps, evaluate, expected_paths, loads


@pytest.fixture
def saved_run(tmp_path):
    schema = {"type": "object", "additionalProperties": False, "required": ["supplier", "total"], "properties": {"supplier": {"type": "string"}, "total": {"type": "number"}}}
    invoice = {"supplier": "Acme", "total": 10}
    events = [
        {"run_id": "agent-run", "event": "run_started", "data": {"source_text": "Supplier: Acme\nTotal: 10 EUR"}},
        {"run_id": "agent-run", "event": "llm_requested", "data": {}},
        {"run_id": "agent-run", "event": "llm_received", "data": {"response_id": "resp_agent"}},
        {"run_id": "agent-run", "event": "run_completed", "data": {"status": "success", "invoice": invoice}},
    ]
    trace = tmp_path / "agent.jsonl"
    trace.write_text("\n".join(dumps(e) for e in events))
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(dumps(schema))
    return trace, schema_file, tmp_path / "output", tmp_path / ".env"


def verdict():
    return {"schema_correct": True, "types_correct": True, "text_correct": True, "arithmetic_correct": True, "summary": "All extracted fields match.", "field_checks": [
        {"path": "supplier", "expected_type": "string", "actual_type": "string", "type_correct": True, "text_correct": True, "source_quote": "Supplier: Acme", "reason": "Name matches."},
        {"path": "total", "expected_type": "number", "actual_type": "number", "type_correct": True, "text_correct": True, "source_quote": "Total: 10 EUR", "reason": "Amount matches."},
    ]}


def fake_client(judgment=None):
    response = SimpleNamespace(id="resp_judge", _request_id="req_judge", model="judge-test", status="completed", usage=None, output_text=dumps(judgment or verdict()))
    client = Mock()
    client.responses.create.return_value = response
    return client


def test_judge_uses_saved_trace_and_writes_txt_json_and_references(saved_run):
    client = fake_client()
    report, directory = evaluate(*saved_run, client=client)
    assert report["status"] == "passed"
    assert report["agent_reference"]["agent_llm_invoked"] is True
    assert report["agent_reference"]["agent_response_ids"] == ["resp_agent"]
    assert report["invocation"]["response_id"] == "resp_judge"
    assert report["invocation"]["request_id"] == "req_judge"
    assert "Judge response ID: resp_judge" in (directory / "result.txt").read_text()
    assert loads((directory / "result.json").read_text()) == report
    assert loads((directory / "request.json").read_text())["parameters"] == client.responses.create.call_args.kwargs
    payload = loads(client.responses.create.call_args.kwargs["input"][0]["content"])
    assert payload["extracted_invoice"] == {"supplier": "Acme", "total": 10}
    assert payload["source_text"] == "Supplier: Acme\nTotal: 10 EUR"
    evidence_schema = client.responses.create.call_args.kwargs["text"]["format"]["schema"]["properties"]["field_checks"]["items"]["properties"]["source_quote"]
    assert evidence_schema["enum"] == ["", "Supplier: Acme", "Total: 10 EUR"]
    client.responses.create.assert_called_once()


def test_deterministic_run_distinct_from_judge_invocation(saved_run):
    path = saved_run[0]
    events = [loads(line) for line in path.read_text().splitlines()]
    path.write_text("\n".join(dumps(e) for e in events if not e["event"].startswith("llm_")))
    report, _ = evaluate(*saved_run, client=fake_client())
    assert report["agent_reference"]["agent_llm_invoked"] is False
    assert report["invocation"]["request_attempted"] is True


def test_wrong_text_is_a_failed_judgment(saved_run):
    judgment = verdict()
    judgment["text_correct"] = False
    judgment["field_checks"][0].update(text_correct=False, reason="Invented supplier.")
    report, directory = evaluate(*saved_run, client=fake_client(judgment))
    assert report["status"] == "failed"
    assert "Invented supplier" in (directory / "result.txt").read_text()


@pytest.mark.parametrize("problem", ["missing_field", "duplicate", "fabricated_quote"])
def test_incomplete_or_unsupported_judgment_cannot_pass(saved_run, problem):
    judgment = verdict()
    if problem == "missing_field":
        judgment["field_checks"].pop()
    elif problem == "duplicate":
        judgment["field_checks"].append(deepcopy(judgment["field_checks"][0]))
    else:
        judgment["field_checks"][0]["source_quote"] = "Never said in source"
    report, _ = evaluate(*saved_run, client=fake_client(judgment))
    assert report["status"] == "failed"
    assert report["judge_errors"]


def test_local_type_check_cannot_be_overridden_by_llm(saved_run):
    path = saved_run[0]
    events = [loads(line) for line in path.read_text().splitlines()]
    events[-1]["data"]["invoice"]["total"] = "10"
    path.write_text("\n".join(dumps(e) for e in events))
    report, _ = evaluate(*saved_run, client=fake_client())
    assert report["status"] == "failed"
    assert report["schema_errors"][0]["path"] == "total"


def test_missing_key_records_not_invoked(saved_run, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report, directory = evaluate(*saved_run)
    assert report["status"] == "error"
    assert report["invocation"]["request_attempted"] is False
    assert (directory / "result.txt").is_file()


def test_api_error_is_not_a_passing_judgment_and_key_is_redacted(saved_run):
    client = fake_client()
    client.responses.create.side_effect = APIStatusError("sk-secret-no-leak", response=httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com/v1/responses")), body={})
    report, directory = evaluate(*saved_run, client=client)
    assert report["status"] == "error"
    assert report["invocation"]["request_attempted"] is True
    assert report["invocation"]["response_received"] is False
    assert "sk-secret-no-leak" not in (directory / "result.txt").read_text()


def test_connection_failure_records_attempt_but_not_response(saved_run):
    client = fake_client()
    client.responses.create.side_effect = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    report, directory = evaluate(*saved_run, client=client)
    assert report["status"] == "error"
    reference = loads((directory / "invocation.json").read_text())
    assert reference["request_attempted"] and not reference["response_received"]


@pytest.mark.parametrize("status,text", [("incomplete", ""), ("completed", ""), ("completed", "{}")])
def test_incomplete_refused_or_malformed_judge_response(saved_run, status, text):
    client = fake_client()
    client.responses.create.return_value.status = status
    client.responses.create.return_value.output_text = text
    report, directory = evaluate(*saved_run, client=client)
    assert report["status"] == "error"
    assert report["invocation"]["response_received"] is True
    assert report["invocation"]["response_id"] == "resp_judge"
    assert (directory / "result.txt").is_file()


def test_missing_trace_still_writes_txt(saved_run):
    saved_run[0].unlink()
    client = fake_client()
    report, directory = evaluate(*saved_run, client=client)
    assert report["status"] == "error"
    client.responses.create.assert_not_called()
    assert (directory / "result.txt").is_file()


def test_wrong_schema_reference_is_rejected_before_model_call(saved_run):
    path = saved_run[0]
    events = [loads(line) for line in path.read_text().splitlines()]
    events[0]["data"]["schema_sha256"] = "different-schema"
    path.write_text("\n".join(dumps(e) for e in events))
    client = fake_client()
    report, _ = evaluate(*saved_run, client=client)
    assert report["status"] == "error"
    client.responses.create.assert_not_called()


def test_coverage_includes_nested_and_missing_required_fields():
    schema = {"type": "object", "required": ["currency", "supplier", "items"], "properties": {
        "supplier": {"$ref": "#/$defs/party"},
        "items": {"type": "array", "items": {"type": "object", "required": ["amount", "description"], "properties": {}}},
    }, "$defs": {"party": {"type": "object", "required": ["name"], "properties": {}}}}
    assert set(expected_paths(schema, {"supplier": {"name": "Acme"}, "items": [{"amount": 10}]})) == {"currency", "supplier.name", "items.0.amount", "items.0.description"}
