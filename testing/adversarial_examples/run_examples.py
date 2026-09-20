"""Characterize review gaps without changing the app or the extraction skill."""
import argparse
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from invoice_agent.runner import run_invoice
from invoice_agent.schema import dumps, loads

HERE = Path(__file__).resolve().parent
CASES = [
    ("01_placeholders.json", "Missing information disguised as non-empty strings: TBD/UNKNOWN.", "schema_gap"),
    ("02_ambiguous_currency.json", "Currency TBD is ambiguous but satisfies the three-uppercase-letter pattern.", "schema_gap"),
    ("03_due_before_issue.json", "Due date precedes issue date; individually valid dates receive no chronology check.", "business_rule_gap"),
    ("04_draft_not_payable.txt", "The document says it is an unissued draft; the schema has no document-status field.", "business_rule_gap"),
    ("05_provisional_tax.txt", "Printed zero tax and total are explicitly provisional; the skill should leave these unresolved.", "skill_probe"),
    ("06_missing_tax_control.txt", "Missing tax must not be assumed to be zero or derived from the total.", "control"),
    ("07_ambiguous_quantity_control.txt", "Ambiguous quantity must not be selected merely to make arithmetic balance.", "control"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Also run the four text cases (up to four OpenAI calls).")
    args = parser.parse_args()
    directory = ROOT / "testing/output/adversarial-examples" / uuid4().hex
    directory.mkdir(parents=True)
    results = []
    for name, concern, kind in CASES:
        if name.endswith(".txt") and not args.live:
            continue
        source = HERE / "inputs" / name
        run = run_invoice(source.read_bytes(), name, data_dir=directory)
        events = [loads(line) for line in run.trace_path.read_text().splitlines()]
        review_requested = any(e["event"] == "human_review_requested" for e in events)
        row = {
            "file": name, "kind": kind, "concern": concern,
            "status": run.status, "route": run.route,
            "human_review_requested": review_requested,
            "llm_invoked": events[-1]["data"].get("llm_invoked", False),
            "llm_response_ids": events[-1]["data"].get("llm_response_ids", []),
            "trace": str(run.trace_path.relative_to(directory)),
            "invoice": run.invoice, "errors": run.errors,
        }
        results.append(row)
        print(dumps({key: row[key] for key in ("file", "status", "route", "human_review_requested", "llm_invoked")}), flush=True)
    (directory / "results.json").write_text(dumps(results, indent=2) + "\n", encoding="utf-8")
    lines = ["Invoice review-gap examples — observed results", "", "These are synthetic test documents. Application and skill were not changed.", ""]
    for row in results:
        lines += [row["file"], f"  Concern: {row['concern']}", f"  Observed: {row['status']} / {row['route']}", f"  Human review requested: {row['human_review_requested']}", f"  LLM invoked: {row['llm_invoked']}", f"  LLM response IDs: {', '.join(row['llm_response_ids']) or 'none'}", f"  Trace: {row['trace']}", ""]
    (directory / "results.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"Reports and traces: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
