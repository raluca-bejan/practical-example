import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from invoice_agent.config import ROOT, Settings
from invoice_agent.schema import SCHEMA, dumps, loads, validate_invoice
from invoice_agent.tracing import Trace

MAX_UPLOAD_BYTES = 100_000
SKILL_PATH = ROOT / "skills/parse_invoice.ms"
VALIDATION_TOOL = {
    "type": "function",
    "name": "validate_invoice",
    "description": "Validate extracted invoice JSON, including missing fields and arithmetic. Submit incomplete data honestly.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {"invoice_json": {"type": "string", "description": "The extracted invoice as a JSON object encoded as a string. Missing fields may be omitted or null."}},
        "required": ["invoice_json"],
        "additionalProperties": False,
    },
}


@dataclass
class RunResult:
    run_id: str
    status: str
    route: str
    invoice: Any
    errors: list[dict]
    trace_path: Path


class WorkflowError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def api_error(error: Exception) -> WorkflowError:
    # Do not persist raw SDK exceptions: they may contain credentials or HTTP bodies.
    if isinstance(error, APITimeoutError):
        return WorkflowError("api_timeout", "OpenAI timed out. Try again or review the invoice manually.")
    if isinstance(error, APIConnectionError):
        return WorkflowError("api_connection", "Could not connect to OpenAI. Check your network and retry.")
    status = error.status_code
    messages = {
        401: "OpenAI rejected the API key. Update the local .env file and retry.",
        403: "The OpenAI account does not have permission for this request.",
        404: "The configured OpenAI model is unavailable. Check OPENAI_MODEL in .env.",
        429: "OpenAI rate limit or quota reached. Check API billing/limits and retry.",
    }
    return WorkflowError("api_error", messages.get(status, f"OpenAI returned HTTP {status}. Retry or review the invoice manually."))


def run_invoice(
    content: bytes,
    filename: str,
    *,
    data_dir: Path = ROOT,
    settings: Settings | None = None,
    client: Any = None,
    skill_path: Path = SKILL_PATH,
) -> RunResult:
    trace = Trace(data_dir)
    started = time.monotonic()
    errors: list[dict] = []
    invoice = None
    route = "deterministic"
    llm_calls = 0
    llm_response_ids = []
    stage = "upload"

    def report(stage: str, code: str, message: str, field: str = "$") -> None:
        issue = {"stage": stage, "code": code, "field": field, "message": message}
        errors.append(issue)
        trace.emit("system", "error", message, issue=issue)

    def validate(candidate: Any, call_id: str | None = None) -> list[dict]:
        trace.emit("agent", "validation_requested", "Execute the local invoice validator.", tool="validate_invoice", call_id=call_id, parameters={"invoice": candidate})
        issues = validate_invoice(candidate)
        trace.emit("tool", "validation_result", "Invoice validation completed.", stage=stage, call_id=call_id, valid=not issues, errors=issues, invoice=candidate)
        for issue in issues:
            report(stage, "validation", issue["message"], issue["field"])
        return issues

    def finish(status: str) -> RunResult:
        if status == "human_review":
            trace.emit("agent", "human_review_requested", "Human review required.", invoice=invoice, errors=errors)
        message = "All great — invoice parsed and validated." if status == "success" else "Human review required."
        trace.emit("system", "user_message", message, status=status)
        trace.emit("agent", "run_completed", message, status=status, route=route, llm_calls=llm_calls, llm_invoked=llm_calls > 0, llm_response_ids=llm_response_ids, duration_ms=round((time.monotonic() - started) * 1000), invoice=invoice, errors=errors)
        return RunResult(trace.run_id, status, route, invoice, errors, trace.path)

    trace.emit("user", "upload_received", "Invoice uploaded.", filename=Path(filename).name, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    try:
        if Path(filename).suffix.lower() not in {".txt", ".json"}:
            raise WorkflowError("file_type", "Upload a .txt or .json invoice; images, PDFs and videos are not supported.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise WorkflowError("file_size", "Invoice exceeds the 100 KB text limit.")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise WorkflowError("encoding", "Invoice must be UTF-8 text.") from None
        if not text.strip():
            raise WorkflowError("empty_invoice", "The uploaded invoice is empty.")
        trace.emit("agent", "run_started", "Try deterministic JSON parsing and schema validation.", source_text=text, schema_sha256=hashlib.sha256(dumps(SCHEMA).encode()).hexdigest())
        stage = "deterministic"
        try:
            invoice = loads(text)
        except (ValueError, RecursionError):
            report(stage, "json_parse", "Input is not an unambiguous JSON document; trying the invoice parsing skill.")
        else:
            trace.emit("agent", "deterministic_parsed", "JSON parsed; validate the invoice.")
            if not validate(invoice):
                return finish("success")

        route = "semantic"
        stage = "semantic"
        trace.emit("agent", "fallback_selected", "Deterministic parsing or validation failed; invoke the invoice parsing skill.")
        try:
            skill = skill_path.read_text(encoding="utf-8")
        except OSError:
            raise WorkflowError("skill_unavailable", "Could not read skills/parse_invoice.ms. Restore the skill file and retry.") from None
        if not skill.strip():
            raise WorkflowError("skill_empty", "The invoice parsing skill is empty.")
        trace.emit("agent", "skill_loaded", "Loaded the invoice parsing skill.", skill=skill_path.name, sha256=hashlib.sha256(skill.encode()).hexdigest())
        config = settings or Settings.load()
        if client is None and not config.api_key:
            raise WorkflowError("missing_api_key", "Semantic parsing needs OPENAI_API_KEY in the local .env file.")
        owned_client = client is None
        if owned_client:
            client = OpenAI(api_key=config.api_key, timeout=45.0, max_retries=0)
        parameters = {
            "model": config.model,
            "instructions": skill + "\n\nTarget invoice schema:\n" + dumps(SCHEMA),
            "input": [{"role": "user", "content": text}],
            "tools": [VALIDATION_TOOL],
            "tool_choice": {"type": "function", "name": "validate_invoice"},
            "parallel_tool_calls": False,
            "max_output_tokens": 6000,
            "store": False,
        }
        try:
            llm_calls += 1
            trace.emit("agent", "llm_requested", "Extract invoice fields and call validate_invoice.", operation="client.responses.create", parameters=parameters, client_options={"timeout_seconds": 45, "max_retries": 0}, model=config.model)
            response = client.responses.create(**parameters)
        finally:
            if owned_client:
                client.close()
        usage = response.usage.model_dump() if response.usage else None
        llm_response_ids.append(response.id)
        trace.emit("agent", "llm_received", "Received the extraction response.", response_id=response.id, request_id=getattr(response, "_request_id", None), model=response.model, status=response.status, usage=usage)
        if response.status != "completed":
            raise WorkflowError("incomplete_response", "OpenAI did not complete extraction (for example, its output limit was reached).")
        calls = [item for item in response.output if item.type == "function_call"]
        if len(calls) != 1 or calls[0].name != "validate_invoice":
            raise WorkflowError("missing_tool_call", "OpenAI did not return the required validation tool call (it may have refused the request).")
        call = calls[0]
        trace.emit("agent", "tool_called", "Call validate_invoice with the extracted fields.", tool=call.name, call_id=call.call_id, arguments=call.arguments)
        try:
            arguments = loads(call.arguments)
            if not isinstance(arguments, dict) or set(arguments) != {"invoice_json"} or not isinstance(arguments["invoice_json"], str):
                raise ValueError("Invalid tool arguments")
            invoice = loads(arguments["invoice_json"])
        except (ValueError, RecursionError):
            trace.emit("tool", "validation_result", "Invalid JSON supplied to validate_invoice.", call_id=call.call_id, valid=False)
            raise WorkflowError("invalid_tool_arguments", "The extraction tool received invalid JSON. Human review is required.") from None
        # The tool result is terminal: no second LLM request can override validation.
        return finish("human_review" if validate(invoice, call.call_id) else "success")
    except WorkflowError as error:
        report(stage, error.code, str(error))
    except (APIConnectionError, APIStatusError) as error:
        friendly = api_error(error)
        report(stage, friendly.code, str(friendly))
    except Exception as error:
        # Preserve a useful error category without leaking SDK payloads or local secrets.
        report(stage, "processing_error", f"Processing failed ({type(error).__name__}). Review the invoice and local configuration.")
    return finish("human_review")
