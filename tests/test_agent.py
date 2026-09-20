from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from invoice_agent.config import ROOT, Settings
from invoice_agent.runner import MAX_UPLOAD_BYTES, run_invoice
from invoice_agent.schema import dumps, loads, validate_invoice
from invoice_agent.tracing import Trace


@pytest.fixture
def invoice():
    return loads((ROOT / "samples/invoice.json").read_text())


def fake_client(invoice, **changes):
    call = SimpleNamespace(type="function_call", name="validate_invoice", call_id="call_test", arguments=dumps({"invoice_json": dumps(invoice)}))
    response = SimpleNamespace(id="resp_test", model="test-model", status="completed", usage=None, output=[call])
    for key, value in changes.items():
        setattr(response, key, value)
    client = Mock()
    client.responses.create.return_value = response
    return client


def events(result):
    return [loads(line) for line in result.trace_path.read_text().splitlines()]


def test_valid_json_does_not_load_skill_or_call_openai(invoice, tmp_path):
    client = fake_client(invoice)
    result = run_invoice(dumps(invoice).encode(), "invoice.json", data_dir=tmp_path, client=client, skill_path=tmp_path / "missing.ms")
    assert result.status == "success"
    assert result.route == "deterministic"
    assert not result.errors
    client.responses.create.assert_not_called()
    assert events(result)[-1]["data"]["llm_calls"] == 0


def test_semantic_tool_call_validates_and_logs(invoice, tmp_path):
    client = fake_client(invoice)
    result = run_invoice(b"Invoice in prose", "invoice.txt", data_dir=tmp_path, client=client)
    assert result.status == "success"
    assert result.route == "semantic"
    assert result.errors[0]["code"] == "json_parse"
    assert result.invoice == invoice
    request = client.responses.create.call_args.kwargs
    assert "Invoice parsing skill" in request["instructions"]
    assert request["tool_choice"]["name"] == "validate_invoice"
    assert request["store"] is False
    assert request["parallel_tool_calls"] is False
    log = events(result)
    names = [event["event"] for event in log]
    assert names.index("skill_loaded") < names.index("tool_called") < names.index("validation_result")
    assert [e["sequence"] for e in log] == list(range(1, len(log) + 1))
    assert all(e["message"].startswith("[agent]") for e in log if e["actor"] == "agent")
    assert loads((tmp_path / "actions.json").read_text()) == log
    logged_request = next(e for e in log if e["event"] == "llm_requested")
    assert logged_request["data"]["parameters"] == request
    logged_validation = next(e for e in log if e["event"] == "validation_requested")
    assert logged_validation["data"]["parameters"] == {"invoice": invoice}
    assert log[-1]["data"]["llm_invoked"] is True
    assert log[-1]["data"]["llm_response_ids"] == ["resp_test"]


def test_bad_totals_trigger_human_review(invoice, tmp_path):
    invoice["total"] = 999
    result = run_invoice(b"Invoice in prose", "invoice.txt", data_dir=tmp_path, client=fake_client(invoice))
    assert result.status == "human_review"
    assert any(e["field"] == "total" for e in result.errors)
    assert "human_review_requested" in [e["event"] for e in events(result)]


def test_invalid_json_schema_also_uses_semantic_fallback(invoice, tmp_path):
    source = deepcopy(invoice)
    source["issue_date"] = "September 20, 2026"
    result = run_invoice(dumps(source).encode(), "invoice.json", data_dir=tmp_path, client=fake_client(invoice))
    assert result.status == "success" and result.route == "semantic"
    assert any(e["stage"] == "deterministic" and e["field"] == "issue_date" for e in result.errors)


def test_missing_fields_are_not_filled_by_validator(tmp_path):
    result = run_invoice(b"Invoice with unknown currency", "invoice.txt", data_dir=tmp_path, client=fake_client({"invoice_number": "A"}))
    assert result.status == "human_review"
    assert result.invoice == {"invoice_number": "A"}
    assert any("currency" in e["message"] for e in result.errors)


@pytest.mark.parametrize("content,name,code", [
    (b"", "invoice.txt", "empty_invoice"),
    (b"invoice", "invoice.pdf", "file_type"),
    (b"\xff", "invoice.txt", "encoding"),
    (b"x" * (MAX_UPLOAD_BYTES + 1), "invoice.txt", "file_size"),
])
def test_upload_errors_are_traced_without_llm(content, name, code, tmp_path):
    client = Mock()
    result = run_invoice(content, name, data_dir=tmp_path, client=client)
    assert result.status == "human_review"
    assert result.errors[0]["code"] == code
    client.responses.create.assert_not_called()
    assert events(result)[-1]["event"] == "run_completed"


def test_missing_local_key_is_visible(tmp_path):
    result = run_invoice(b"Invoice in prose", "invoice.txt", data_dir=tmp_path, settings=Settings())
    assert result.status == "human_review"
    assert result.errors[-1]["code"] == "missing_api_key"


def test_missing_skill_is_visible(tmp_path):
    result = run_invoice(b"Invoice in prose", "invoice.txt", data_dir=tmp_path, skill_path=tmp_path / "missing.ms")
    assert result.errors[-1]["code"] == "skill_unavailable"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_api_errors_are_visible_and_credentials_are_not_logged(tmp_path, status):
    client = Mock()
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    client.responses.create.side_effect = APIStatusError("private sk-test-must-not-leak", response=response, body={})
    result = run_invoice(b"Invoice in prose", "invoice.txt", data_dir=tmp_path, client=client)
    assert result.status == "human_review"
    assert result.errors[-1]["code"] == "api_error"
    assert "sk-test-must-not-leak" not in result.trace_path.read_text()
    assert events(result)[-1]["data"]["llm_invoked"] is True
    assert events(result)[-1]["data"]["llm_response_ids"] == []


@pytest.mark.parametrize("error_class,code", [(APITimeoutError, "api_timeout"), (APIConnectionError, "api_connection")])
def test_network_errors_finish_with_trace(tmp_path, error_class, code):
    client = Mock()
    client.responses.create.side_effect = error_class(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    result = run_invoice(b"Invoice in prose", "invoice.txt", data_dir=tmp_path, client=client)
    assert result.errors[-1]["code"] == code
    assert events(result)[-1]["event"] == "run_completed"


@pytest.mark.parametrize("change,code", [({"status": "incomplete"}, "incomplete_response"), ({"output": []}, "missing_tool_call")])
def test_incomplete_or_refused_output_is_not_success(invoice, tmp_path, change, code):
    result = run_invoice(b"Invoice", "invoice.txt", data_dir=tmp_path, client=fake_client(invoice, **change))
    assert result.status == "human_review"
    assert result.errors[-1]["code"] == code


def test_invalid_tool_arguments_are_visible(invoice, tmp_path):
    client = fake_client(invoice)
    client.responses.create.return_value.output[0].arguments = '{"invoice_json": "not json"}'
    result = run_invoice(b"Invoice", "invoice.txt", data_dir=tmp_path, client=client)
    assert result.errors[-1]["code"] == "invalid_tool_arguments"


def test_all_structural_and_arithmetic_errors_are_returned(invoice):
    invoice["issue_date"] = "2026-02-30"
    invoice["currency"] = "eur"
    invoice["line_items"][0]["amount"] = 150
    invoice["subtotal"] = 199
    invoice["total"] = 999
    fields = {error["field"] for error in validate_invoice(invoice)}
    assert fields >= {"issue_date", "currency", "line_items.0.amount", "subtotal", "total"}


@pytest.mark.parametrize("field,value", [("invoice_number", " "), ("line_items", []), ("total", True), ("tax_amount", -1), ("currency", None)])
def test_invalid_schema_values(invoice, field, value):
    invoice[field] = value
    assert validate_invoice(invoice)


def test_decimal_arithmetic_and_tolerance(invoice):
    invoice["line_items"][0].update(quantity=3, unit_price=Decimal("0.10"), amount=Decimal("0.30"))
    invoice.update(subtotal=Decimal("0.30"), tax_amount=0, total=Decimal("0.31"))
    assert not validate_invoice(invoice)
    invoice["total"] = Decimal("0.311")
    assert any(e["field"] == "total" for e in validate_invoice(invoice))
    assert loads(dumps(invoice)) == invoice


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"total": NaN}', '{"total": Infinity}'])
def test_ambiguous_json_is_rejected(text):
    with pytest.raises(ValueError):
        loads(text)


def test_optional_fields_may_be_absent(invoice):
    del invoice["customer"]
    del invoice["due_date"]
    assert not validate_invoice(invoice)


def test_unknown_fields_rejected(invoice):
    invoice["bank_account"] = "outside this schema"
    assert validate_invoice(invoice)


def test_utf8_bom_is_accepted(invoice, tmp_path):
    result = run_invoice(dumps(invoice).encode("utf-8-sig"), "invoice.json", data_dir=tmp_path)
    assert result.status == "success"


def test_concurrent_actions_remain_valid_json(tmp_path):
    def write(index):
        trace = Trace(tmp_path)
        trace.emit("agent", "test", "An action.", index=index, secret="sk-test-secret")
        return trace.run_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(write, range(8)))
    actions = loads((tmp_path / "actions.json").read_text())
    assert {entry["run_id"] for entry in actions} == set(ids)
    assert len(actions) == 8
    assert all(entry["data"]["secret"] == "[REDACTED]" for entry in actions)


def test_settings_keep_key_out_of_repr(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    config = tmp_path / ".env"
    config.write_text("OPENAI_API_KEY=sk-test-local\nOPENAI_MODEL=test-model\n")
    settings = Settings.load(config)
    assert settings.api_key == "sk-test-local"
    assert settings.model == "test-model"
    assert "sk-test-local" not in repr(settings)
