"""Convert saved evaluations into rule-based proposals for human approval."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

CATALOG = {
    "provisional_values": {
        "priority": "high",
        "title": "Preserve provisional amounts and route them to review",
        "changes": {
            "skill": "Give footnotes and provisional/placeholder notices precedence over printed numbers. Add confirmed-zero versus provisional-zero few-shot examples.",
            "validation": "Request review when required amounts are provisional even if their numeric values balance.",
            "schema": "Add per-field certainty status and source evidence to a partial-extraction envelope; require confirmed amounts for acceptance.",
        },
        "regression_test": "Provisional zero tax must request review; explicitly confirmed zero tax must still be accepted.",
        "human_decision": "Approve the certainty statuses and the policy for provisional financial fields.",
    },
    "currency": {
        "priority": "high", "title": "Reject unresolved currency placeholders",
        "changes": {
            "skill": "Treat TBD/unknown currency as unresolved; do not select a currency from context alone.",
            "validation": "Apply an approved currency-code set and placeholder checks to both parsing routes.",
            "schema": "Replace the three-letter-only rule with an explicitly maintained currency constraint.",
        },
        "regression_test": "Currency TBD must request review; supported currencies such as EUR must still pass.",
        "human_decision": "Choose the supported currency set and who maintains it.",
    },
    "placeholders": {
        "priority": "high", "title": "Treat mandatory-field placeholders as missing information",
        "changes": {
            "skill": "Add contrastive examples for TBD invoice identifiers and UNKNOWN supplier fields versus genuine unusual names.",
            "validation": "Detect field-appropriate placeholders on JSON and semantic routes; avoid substring-based blanket rejection.",
            "schema": "Represent missing/ambiguous field status separately from required confirmed values.",
        },
        "regression_test": "TBD/UNKNOWN mandatory placeholders require review; legitimate names containing those words do not automatically fail.",
        "human_decision": "Approve placeholder handling per field, including exceptions for genuine names.",
    },
    "document_status": {
        "priority": "medium", "title": "Preserve document status before deciding acceptance",
        "changes": {
            "skill": "Extract draft/pro-forma/not-issued notices as document status instead of dropping them.",
            "validation": "Apply a reviewed policy for draft versus issued invoices independently of arithmetic.",
            "schema": "Introduce document_type and document_status without silently treating legacy inputs as confirmed invoices.",
        },
        "regression_test": "A draft marked DO NOT PAY must follow the approved review policy; an issued invoice must still pass.",
        "human_decision": "Decide whether drafts should be reviewed, rejected, or stored as nonpayable extractions.",
    },
    "date_order": {
        "priority": "medium", "title": "Define a date-order policy with explicit exceptions",
        "changes": {
            "validation": "Flag due_date earlier than issue_date according to an approved policy, with reissue exceptions.",
            "schema": "Retain both dates; add explicit reissue context only if the business requires it.",
        },
        "regression_test": "Exercise normal date order, the observed earlier due date, and a legitimate reissued invoice.",
        "human_decision": "Agree whether reversed dates are errors or warnings and define reissue exceptions.",
    },
    "text_grounding": {
        "priority": "high", "title": "Improve extraction grounding for the judged fields",
        "changes": {
            "skill": "Add the observed disagreement as a few-shot case; preserve source qualifiers and never invent missing values.",
            "validation": "Check evidence links and unresolved fields; do not equate an exact quote with correct interpretation.",
            "schema": "Record raw source evidence alongside normalized values and uncertainty statuses.",
        },
        "regression_test": "Replay the failed extraction and a correct neighboring example against held-out evaluation data.",
        "human_decision": "Verify the judge's finding against the original invoice before approving a rule change.",
    },
    "schema_validation": {
        "priority": "high", "title": "Investigate schema or arithmetic disagreement",
        "changes": {
            "validation": "Review the recorded field/type/arithmetic errors, preserve deterministic checks, and add regression coverage.",
            "schema": "Confirm the intended field contract and migration policy before changing requiredness or types.",
        },
        "regression_test": "The offending values must not be accepted; a valid counterpart must continue to pass.",
        "human_decision": "Determine whether extraction, validation, or the contract is incorrect; do not relax constraints simply to get a pass.",
    },
    "evaluation_quality": {
        "priority": "medium", "title": "Repair the evaluator before changing invoice rules",
        "changes": {"evaluation": "Review incomplete field coverage or unsupported evidence quotes in the judge's report."},
        "regression_test": "Malformed evidence must not produce a passing judgment; valid field coverage and exact quotes should pass.",
        "human_decision": "Confirm this is an evaluator defect rather than an invoice extraction defect.",
    },
}


def classify_case(case):
    invoice = case.get("invoice") or {}
    concern = case.get("concern", "").lower()
    if "provisional" in concern or "unconfirmed" in concern:
        return "provisional_values"
    if "currency" in concern:
        return "currency"
    if "placeholder" in concern or "tbd" in concern or "unknown" in concern:
        return "placeholders"
    if "draft" in concern or "not issued" in concern:
        return "document_status"
    if "due date" in concern and isinstance(invoice, dict):
        return "date_order"
    return "text_grounding"


def propose(paths):
    proposals = {}
    notes = []

    def add(code, reference, finding):
        if code not in proposals:
            proposals[code] = {"id": code, **CATALOG[code], "review": {"decision": "pending", "reviewer": None, "comment": None}, "evidence": []}
        proposals[code]["evidence"].append({**reference, "finding": finding})

    for path in paths:
        raw = path.read_bytes()
        data = json.loads(raw)
        reference = {"evaluation_file": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
        if isinstance(data, list):
            for case in data:
                if not isinstance(case, dict):
                    raise ValueError("Expected evaluation case objects.")
                # Require an explicit concern and an observed acceptance, not a guessed failure.
                if case.get("status") == "success" and case.get("human_review_requested") is False and case.get("concern"):
                    evidence = {**reference, "case": case.get("file"), "trace": case.get("trace"), "llm_response_ids": case.get("llm_response_ids", [])}
                    add(classify_case(case), evidence, case["concern"])
                else:
                    notes.append({**reference, "case": case.get("file"), "message": "No accepted-with-concern finding; no rule change proposed."})
        elif isinstance(data, dict) and data.get("status") in {"passed", "failed", "error"}:
            reference.update(evaluation_id=data.get("evaluation_id"), invocation=data.get("invocation"), agent_reference=data.get("agent_reference"))
            if data["status"] == "error":
                notes.append({**reference, "message": "Evaluation did not complete; fix execution/configuration before proposing invoice rule changes.", "errors": data.get("errors", [])})
                continue
            if data.get("judge_errors"):
                add("evaluation_quality", reference, data["judge_errors"])
                # An invalid judgment is not reliable evidence of an extraction defect.
                continue
            verdict = data.get("verdict") or {}
            if data.get("schema_errors") or any(verdict.get(key) is False for key in ("schema_correct", "types_correct", "arithmetic_correct")):
                add("schema_validation", reference, {"schema_errors": data.get("schema_errors", []), "summary": verdict.get("summary")})
            bad_fields = [field for field in verdict.get("field_checks", []) if field.get("text_correct") is False]
            if verdict.get("text_correct") is False or bad_fields:
                add("text_grounding", reference, {"fields": bad_fields, "summary": verdict.get("summary")})
            if data["status"] == "passed":
                notes.append({**reference, "message": "Passing evaluation; no change inferred from this case alone."})
        else:
            raise ValueError("Expected a judge result.json or an adversarial results.json array.")
    return {"created_at": datetime.now(timezone.utc).isoformat(), "generator": "deterministic_rules_v1", "llm_invoked": False, "status": "pending_human_review" if proposals else "no_proposals", "changes_applied": False, "proposals": list(proposals.values()), "notes": notes}


def render(report):
    lines = ["Improvement proposals for human review", f"Status: {report['status']}", "Generator: deterministic rules; no LLM invoked", "No production rules or skill files have been changed.", ""]
    for proposal in report["proposals"]:
        lines += [f"[{proposal['priority']}] {proposal['title']}", "Review decision: pending"]
        for area, change in proposal["changes"].items():
            lines.append(f"  {area}: {change}")
        lines += [f"  Regression test: {proposal['regression_test']}", f"  Human decision: {proposal['human_decision']}"]
        for evidence in proposal["evidence"]:
            lines += [f"  Evidence: {evidence['evaluation_file']} / {evidence.get('case') or evidence.get('evaluation_id', '')}", f"  Finding: {evidence['finding']}"]
        lines.append("")
    for note in report["notes"]:
        lines.append(f"Note: {note['message']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluations", type=Path, nargs="+")
    parser.add_argument("--output-dir", type=Path, default=Path("testing/output/improvements"))
    args = parser.parse_args()
    try:
        report = propose(args.evaluations)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Could not read evaluation results ({type(error).__name__}). Supply a valid evaluation JSON file.\n")
    directory = args.output_dir / uuid4().hex
    directory.mkdir(parents=True)
    # Evaluation data may contain arbitrary source strings; redact key-like values.
    encoded = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", json.dumps(report, indent=2))
    (directory / "proposals.json").write_text(encoded + "\n", encoding="utf-8")
    (directory / "proposals.txt").write_text(render(json.loads(encoded)), encoding="utf-8")
    print(f"{len(report['proposals'])} proposals pending human review; no changes applied.")
    print(directory / "proposals.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
