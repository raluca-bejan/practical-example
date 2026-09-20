"""Run synthetic samples and retain real traces for review; two OpenAI requests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from invoice_agent.config import ROOT
from invoice_agent.runner import run_invoice
from invoice_agent.schema import dumps


def main() -> int:
    cases = [("invoice.json", "deterministic", "success"), ("invoice.txt", "semantic", "success"), ("needs_review.txt", "semantic", "human_review")]
    results = []
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    for filename, route, expected in cases:
        sample = ROOT / "samples" / filename
        result = run_invoice(sample.read_bytes(), filename)
        # These explicitly selected fixtures contain synthetic invoice data only.
        trace_name = f"demo-{filename.replace('.', '-')}.jsonl"
        (docs / trace_name).write_bytes(result.trace_path.read_bytes())
        entry = {"sample": filename, "expected": expected, "actual": result.status, "route": result.route, "passed": result.status == expected and result.route == route, "run_id": result.run_id, "trace": trace_name, "errors": result.errors}
        results.append(entry)
        print(dumps(entry))
    (docs / "demo-results.json").write_text(dumps(results, indent=2) + "\n")
    return 0 if all(case["passed"] for case in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
