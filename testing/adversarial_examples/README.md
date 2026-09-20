# Examples that can escape human review

These synthetic invoices were run against the current application and extraction
skill without changing either. Five were accepted without human review. Two
controls correctly requested review. These are observations from one recorded
run, not a guarantee that future LLM extractions produce the same result.

Upload the `.json` and `.txt` files under `inputs/` using the existing Streamlit
UI. The picture is a visual companion only; the application still does not accept
image uploads.

The picture is [placeholder-invoice.png](placeholder-invoice.png). It was
generated using the built-in image tool; the exact prompt is saved in
[IMAGE_PROMPT.md](IMAGE_PROMPT.md).

| Input | Quality concern | Observed route | Human review requested? |
| --- | --- | --- | --- |
| `01_placeholders.json` | Invoice number/description are `TBD`; supplier is `UNKNOWN` | Deterministic | No |
| `02_ambiguous_currency.json` | Currency is `TBD`, which matches the three-letter regex | Deterministic | No |
| `03_due_before_issue.json` | Due date precedes the issue date | Deterministic | No |
| `04_draft_not_payable.txt` | Explicitly an unissued draft marked “DO NOT PAY” | Semantic | No |
| `05_provisional_tax.txt` | Zero tax and total are explicitly unconfirmed placeholders | Semantic | No |
| `06_missing_tax_control.txt` | Tax amount is absent | Semantic | Yes |
| `07_ambiguous_quantity_control.txt` | Quantity says “2 or 3 (unconfirmed)” | Semantic | Yes |

## The most direct skill failure

`05_provisional_tax.txt` includes these printed amounts:

```text
Subtotal: 200.00 EUR
Tax: 0.00 EUR *
Total: 200.00 EUR *

* The zero tax is a system placeholder, not a confirmed tax amount. The tax
amount and final total are not determined. Accounting must confirm them.
```

The skill says ambiguous required values must be omitted or null. In the
recorded run the model instead supplied `tax_amount: 0.00` and `total: 200.00`.
Those values have valid types and balance, so local validation returned success.
The trace contains no `human_review_requested` event. This demonstrates a loss
of qualification from source text, rather than a schema/type failure.

## What the other cases demonstrate

- **Structured JSON bypasses the skill.** Nonempty placeholders satisfy the
  string rules. `TBD` also satisfies `[A-Z]{3}`. The missing-information instruction
  is never consulted for those valid-JSON cases.
- **Individual date validity is not a chronology check.** Both dates are real
  dates. The current contract has no rule connecting them; an earlier due date
  is a reason to inspect this example, not a violation of an agreed schema rule.
- **Document status disappears during extraction.** “Draft / not issued” is not
  represented in the schema. A structurally correct extraction is not confirmation
  that the document is an issued, payable invoice.
- **Absent optional fields are not errors.** Omitting customer or due date is
  permitted by the agreed contract and is not counted as a failure here.

The separate LLM judge is not part of the application's review decision. These
results concern the app's real processing outcomes; the judge was not rerun for
this collection. No validation rules have been weakened to make these pass.

## Reproduce

From the existing project root:

```sh
# Only the three JSON examples; no API call.
.venv/bin/python testing/adversarial_examples/run_examples.py

# All seven examples; up to four OpenAI calls using the existing local .env.
.venv/bin/python testing/adversarial_examples/run_examples.py --live
```

Each execution creates an isolated folder under
`testing/output/adversarial-examples/<id>/` containing `results.txt`,
`results.json`, `actions.json`, and per-run `traces/*.jsonl`.
The exported `observed/` snapshot contains only this collection's
synthetic results and real traces. No credentials are included.

The Streamlit server remains stopped; restart with `make run` when you want to
test through the UI.
