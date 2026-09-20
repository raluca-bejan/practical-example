import argparse
from pathlib import Path

from invoice_agent.config import ROOT
from invoice_agent.runner import run_invoice
from invoice_agent.schema import dumps
from invoice_agent.tracing import redact


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse an invoice and record actions.json plus a JSONL trace.")
    parser.add_argument("invoice", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        content = args.invoice.read_bytes()
    except OSError:
        parser.error("Could not read the invoice file.")
    result = run_invoice(content, args.invoice.name, data_dir=args.output_dir)
    print(dumps(redact({"run_id": result.run_id, "status": result.status, "route": result.route, "invoice": result.invoice, "errors": result.errors, "trace": str(result.trace_path)}), indent=2))
    return 0 if result.status == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
