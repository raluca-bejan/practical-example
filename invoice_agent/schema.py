from decimal import Decimal, localcontext
from typing import Any

import simplejson as json
from jsonschema import Draft202012Validator, FormatChecker

from invoice_agent.config import ROOT

SCHEMA = json.loads((ROOT / "schemas/invoice.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
TOLERANCE = Decimal("0.01")


def dumps(value: Any, **kwargs: Any) -> str:
    """Keep Decimal values as JSON numbers, without a float round trip."""
    return json.dumps(value, use_decimal=True, ensure_ascii=False, **kwargs)


def _unique_keys(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not allowed.")
        result[key] = value
    return result


def loads(text: str) -> Any:
    # Reject NaN/Infinity and duplicate fields instead of silently choosing a value.
    return json.loads(text, use_decimal=True, allow_nan=False, object_pairs_hook=_unique_keys)


def validate_invoice(invoice: Any) -> list[dict]:
    """Return all schema errors plus every arithmetic check we can evaluate."""
    errors = [
        {"field": ".".join(map(str, error.absolute_path)) or "$", "message": error.message}
        for error in sorted(VALIDATOR.iter_errors(invoice), key=lambda e: str(list(e.absolute_path)))
    ]
    if not isinstance(invoice, dict):
        return errors

    def number(value: Any) -> bool:
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and Decimal(str(value)).is_finite()

    def check(field: str, actual: Any, expected: Decimal) -> None:
        if number(actual) and abs(Decimal(str(actual)) - expected) > TOLERANCE:
            errors.append({"field": field, "message": f"Expected {expected}; found {actual} (tolerance {TOLERANCE})."})

    # Avoid the binary rounding of floats and preserve long numeric inputs.
    with localcontext() as context:
        context.prec = 100
        items = invoice.get("line_items")
        if isinstance(items, list):
            for index, item in enumerate(items):
                if isinstance(item, dict) and all(number(item.get(k)) for k in ("quantity", "unit_price", "amount")):
                    check(f"line_items.{index}.amount", item["amount"], Decimal(str(item["quantity"])) * Decimal(str(item["unit_price"])))
            if items and all(isinstance(item, dict) and number(item.get("amount")) for item in items):
                check("subtotal", invoice.get("subtotal"), sum((Decimal(str(item["amount"])) for item in items), Decimal(0)))
        if number(invoice.get("subtotal")) and number(invoice.get("tax_amount")):
            check("total", invoice.get("total"), Decimal(str(invoice["subtotal"])) + Decimal(str(invoice["tax_amount"])))
    return errors
