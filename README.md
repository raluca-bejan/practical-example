# Invoice parsing agent

A small Python/Streamlit app: upload a text invoice, validate structured JSON
first, then fall back to an OpenAI agent that loads a parsing skill and calls a
local validation tool. The outcome is a validated invoice or a human-review
request with every error shown in the UI.

This README describes the working implementation and the lessons from recorded
runs. Recommendations below are **proposed improvements**, not behavior already
implemented. The extraction skill is named `skills/parse_invoice.ms` in this
project (the “skill.md” discussed in the design); its extension is intentionally
`.ms`, and it is loaded as plain text.

## What was built

| Part | Files / output | Purpose |
| --- | --- | --- |
| Minimal UI | `app.py` | Upload text, show extracted fields and every error, download JSON and traces |
| Agent workflow | `invoice_agent/runner.py` | Deterministic parsing first, one semantic fallback, validation, success/review |
| Extraction skill | `skills/parse_invoice.ms` | Ground extraction in the source; preserve missing or ambiguous information |
| Invoice contract | `schemas/invoice.schema.json` | Required/optional fields, types, dates and basic constraints |
| Validator | `invoice_agent/schema.py` | JSON Schema checks and Decimal arithmetic with 0.01 tolerance |
| Audit logging | `invoice_agent/tracing.py` | `actions.json` plus one JSONL trace per run, including call parameters |
| Local configuration | `.env`, `.env.example` | Local key/model configuration; actual credentials excluded from Git and ZIPs |
| CLI and setup | `invoice_agent/__main__.py`, `Makefile` | Setup, run, test, demonstrate and package |
| Separate LLM judge | `testing/llm_judge.py` | Evaluate a saved extraction against its source and schema, without rerunning the agent |
| Judge reports | `testing/reports/`, `testing/output/` | TXT/JSON verdicts, per-field evidence and saved OpenAI invocation references |
| Regression tests | `tests/`, `testing/test_llm_judge.py` | Offline validation, workflow, UI, logging, packaging and judge checks |
| Adversarial examples | `testing/adversarial_examples/` | Seven synthetic review probes with actual outcomes and traces |
| Visuals | `ARCHITECTURE.md`, `docs/architecture.svg`, example PNG | Architecture and an illustrative placeholder invoice |
| Packaging | `scripts/package.py` | Separate application/testing packages and change-only ZIPs |

The example picture was generated with the built-in image tool. Its exact
[prompt](testing/adversarial_examples/IMAGE_PROMPT.md) is retained alongside the
[PNG](testing/adversarial_examples/placeholder-invoice.png). It is not an input
supported by the current app.

## Setup and run

Requires Python 3.11+ and Make. From this directory:

```sh
make setup
cp .env.example .env   # only if .env does not already exist
```

Edit `.env` locally and set `OPENAI_API_KEY`. `OPENAI_MODEL` defaults to
`gpt-4.1-mini`. Environment variables override the local file. The key is needed
only for semantic parsing; valid JSON works offline. `make setup` never replaces
an existing `.env`.

```sh
make run
```

Open **http://localhost:8501** and upload one of the included samples:

| File | Expected behavior |
| --- | --- |
| `samples/invoice.json` | Deterministic validation; no OpenAI request |
| `samples/invoice.txt` | Agent extraction and validation; success |
| `samples/needs_review.txt` | Agent preserves the incorrect total; human review |

The UI accepts UTF-8 `.txt` and `.json` files up to 100 KB, displays extracted
fields and all errors, and lets you download the invoice and its JSONL trace.
An initial JSON parse failure remains visible as a recovered warning if semantic
parsing succeeds. A new upload clears the previous result. Streamlit rerenders
do not repeat a model call; click **Parse invoice** to start a new run.

## Schema and flow

The source of truth is [schemas/invoice.schema.json](schemas/invoice.schema.json).
Only `due_date` and `customer` are optional. Required fields are `invoice_number`,
`issue_date`, `currency`, `supplier.name`, `line_items`, `subtotal`, `tax_amount`,
and `total`. Each line requires `description`, `quantity`, `unit_price`, and
`amount`. Dates use `YYYY-MM-DD`; currency is three uppercase letters (syntax
validation, not a currency registry lookup). Extra fields are rejected.

The validator checks every schema error, then all arithmetic it can evaluate:
quantity × unit price = amount; item amounts sum to subtotal; subtotal + tax =
total. Calculations use `Decimal`, with an inclusive `0.01` tolerance. Quantities
must be positive; monetary values must be nonnegative. This first version does
not handle credits, discounts, currency conversion, images, PDFs, or video.

If JSON decoding **or validation** fails, the runner lazily reads
[skills/parse_invoice.ms](skills/parse_invoice.ms). This is a plain-text prompt
file, not executable code. The OpenAI SDK's Responses API receives the skill,
schema, and invoice text, with a required `validate_invoice` function call.
The tool accepts the extracted JSON as a string so incomplete fields can reach
the validator without forcing the model to fill them in. The local validator
is authoritative. Its result ends the run; there is no second model call or
automatic repair loop. One semantic attempt makes at most one API request
(45-second timeout, SDK retries disabled).

Detected missing fields, inconsistent amounts, missing configuration, refusals,
truncated responses, and API failures lead to **Human review required**. This
does not guarantee detection of every semantic problem; see the observed gaps
below. Human handoff
is the agreed UI state and a trace event, not an email or ticket. A reviewer
corrects the source file and uploads it as a new run.

See [the architecture diagram](ARCHITECTURE.md) or open
[the standalone SVG](docs/architecture.svg).

## Actions, traces, and demonstrations

Every processing run writes both:

- `actions.json`: one chronological JSON array across runs; agent messages begin
  with `[agent]`. File locking protects concurrent runs and the array is replaced
  atomically after each action.
- `traces/<run_id>.jsonl`: one JSON event per line for that run, including upload
  metadata, source text, parser decisions, skill/schema hashes, model and token
  usage, tool calls/outputs, errors, outcome, and duration.

For new runs, both logs include the full explicit `client.responses.create` parameters:
model, instructions (loaded skill and schema), input, tool definitions, tool
choice, parallel-call setting, output limit, and storage setting. Local validator
calls record all input parameters too. Credentials are excluded/redacted.
`run_completed` records `llm_invoked` and confirmed `llm_response_ids`; an attempt
without a response is distinguishable from a successful API invocation.
Existing traces are left intact; earlier traces do not retroactively acquire
parameters that were not originally recorded.

These are observable actions, not private model reasoning. Run IDs and sequence
numbers link the two logs. API keys and raw SDK exception payloads are excluded.
Invoice text and extracted data remain in local logs for later evaluation;
those logs are excluded from Git and the distribution ZIP. Semantic fallback
sends the invoice text to OpenAI with `store=False`.

```sh
make setup-tests # install the separate testing dependencies
make test       # offline validator, workflow, logging, packaging and UI tests
make test_llm   # judge the saved semantic trace; does not rerun extraction
make demo-json  # one deterministic run, no API key needed
make demo      # three synthetic runs, including two live OpenAI requests
make package   # application only; excludes tests, .env and runtime logs
make package-tests # separate testing package
make package-changes # application and testing delta ZIPs, separately
```

`make demo` retains the synthetic traces as `docs/demo-*.jsonl` and a
`docs/demo-results.json` summary for review. It reports failure if the observed
route or outcome differs from expectations. No automatic training or learning
system is included; the traces provide inputs for future evaluation.

You can also run any invoice without Streamlit:

```sh
.venv/bin/python -m invoice_agent samples/invoice.txt
```

CLI exit status is `0` for success and `2` for human review. An alternate log
directory can be supplied with `--output-dir /path/to/logs`.

The application ZIP contains code, schema, skill, samples and architecture.
Tests, the LLM judge and recorded synthetic demo traces are provided in the
separate testing ZIP. It includes only `.env.example`, never the real
key, virtual environment, Git history, uploaded invoices, or general run logs.
After unzipping, run `make setup` and configure a new local `.env`.

The independent judge compares the saved extraction to the schema and original
invoice text, including field types and semantic correctness. Its readable report
is `testing/output/<evaluation_id>/result.txt`; JSON results and a saved OpenAI
invocation reference accompany it. `testing/output/latest.json` points to the
latest report. See [the testing instructions](testing/README.md).

## Verified results and limitations

The initial demonstration produced the expected three outcomes: valid JSON
passed offline; invoice prose passed through real OpenAI extraction; an
inconsistent total was preserved and routed to human review. The separate judge
evaluated the existing successful semantic trace and passed all 13 fields. Its
[TXT report](testing/reports/saved-trace-judge.txt) and
[invocation reference](testing/reports/saved-trace-invocation.json) distinguish
an attempted request from a confirmed response. The implementation had 58 passing
offline tests at that stage.

The first judge response contained two table quotes that were not verbatim source
text, despite a positive verdict. The evidence check rejected that report. The
judge now requests complete source lines and, for small invoices, constrains
quotes to an enum of actual lines. Coverage and quote checks prevent that form
of unsupported positive report. A quote alone still does not prove that the
model interpreted its qualification correctly.

We then ran seven synthetic probes without changing the skill or application:

| Probe | Observed outcome | What it reveals |
| --- | --- | --- |
| `TBD` invoice number/description, `UNKNOWN` supplier | Accepted, deterministic | Nonempty strings can represent missing information |
| Currency `TBD` | Accepted, deterministic | Three uppercase letters are not sufficient currency validation |
| Due date before issue date | Accepted, deterministic | Individual date checks do not enforce business chronology |
| Draft marked “NOT ISSUED / DO NOT PAY” | Accepted, semantic | The schema cannot represent document status |
| Zero tax explicitly marked unconfirmed/provisional | Accepted, semantic | The model copied the number and lost the source qualification |
| Tax omitted | Human review, semantic | The missing-required-field rule worked in this run |
| Quantity “2 or 3 (unconfirmed)” | Human review, semantic | The ambiguity rule worked in this run |

The strongest direct skill failure was **provisional tax**: the source said its
zero tax and total were unconfirmed, but the model returned `tax_amount: 0` and
`total: 200`. Both types and arithmetic passed. The application requested no human
review. Missing/ambiguous instructions alone did not enforce source certainty.

See the [observed results](testing/adversarial_examples/observed/results.txt),
[machine-readable results](testing/adversarial_examples/observed/results.json),
and [example guide](testing/adversarial_examples/README.md). Those observations
come from one run each; they are not an estimated false-acceptance rate. The LLM
judge was not run on the adversarial collection. Date order and draft status are
business-policy gaps, not violations of the originally agreed minimal schema.
Absent optional customer/due-date fields are valid and were not counted as errors.

## Learnings: improve the extraction skill

The skill should distinguish **a printed value** from **a confirmed value**.
Proposed changes to `skills/parse_invoice.ms`:

1. Define missingness explicitly: `TBD`, `UNKNOWN`, pending, provisional,
   estimated, question marks, crossed-out values and alternatives are unresolved
   when used as field placeholders. Avoid blindly rejecting a genuine business
   name merely because it contains one of these words.
2. Give qualifications precedence over amounts. A footnote such as “0.00 is a
   placeholder” overrides the printed number. Read nearby annotations, footnote
   markers and document-wide notices before assigning a value.
3. Preserve uncertainty as data: field path, status (`missing`, `ambiguous`,
   `provisional`, `confirmed`), candidate values, exact source evidence and reason.
   This needs a schema change; adding new fields today would fail validation.
4. Detect document kind/status before extracting: issued invoice, draft,
   pro-forma, credit note or unknown. Do not equate successful extraction with
   permission to pay. Let explicit business policy decide accept/review/reject.
5. Keep the existing prohibitions on inventing values, calculating missing
   amounts and silently repairing totals. Keep ambiguous line items, with their
   uncertainty, instead of dropping them to make the total balance.

Add short contrasting few-shot examples rather than only more prohibitions:

| Source fragment | Intended extraction / decision |
| --- | --- |
| `Tax: 0.00 — confirmed tax exemption` | Preserve zero if explicitly stated; retain the evidence |
| `Tax: 0.00*; *placeholder, final tax unknown` | `tax_amount: null`; provisional reason; review |
| `Subtotal: 200; Total: 200` with no tax line | Omit/null tax; never infer zero; review |
| `Quantity: 2 or 3; amount: 200` | Unresolved quantity; do not choose 2 from arithmetic; review |
| `Invoice number: TBD` | Missing invoice number, not the literal valid identifier `TBD`; review |
| `Total: 999` when subtotal + tax = 238 | Preserve 999; report inconsistency; review |
| `DRAFT — NOT ISSUED` with complete amounts | Preserve draft status; business policy determines disposition |

Test both negative examples and valid neighbors so stronger instructions do not
unnecessarily route every zero-tax invoice, unusual name or optional omission
to review. Version the skill and retain its hash in each run, as the app already
does. Evaluate changes on held-out examples and repeated runs, not just the
examples used in the prompt.

## Learnings: improve validation

Keep deterministic validation authoritative, but extend what it checks:

- Apply placeholder and semantic-status checks to **both routes**. Valid uploaded
  JSON currently skips the skill; prompt changes alone cannot fix those cases.
- Separate schema errors, arithmetic errors and business/uncertainty findings.
  Give each finding a stable code, field path, severity, evidence and review reason.
- Check currency against a maintained allowed set; do not rely on `[A-Z]{3}`.
  Make date-order and document-status policies explicit and configurable; some
  reissued invoices can legitimately retain older due dates.
- Require unresolved required fields or provisional financial amounts to trigger
  review even if a numeric value is present and arithmetic balances. The validator
  must inspect extraction metadata/source evidence to detect this; a bare number
  cannot communicate that it was provisional.
- Validate evidence links/quotes and field coverage. Consider a bounded semantic
  check for qualified amounts or source/extraction disagreement, while retaining
  deterministic checks and treating unavailable evaluation as unresolved.
- Make rounding rules currency-aware and define whether calculations round per
  line or only at totals. The current uniform `0.01` tolerance is a prototype
  assumption; do not silently relax it until incorrect invoices pass.
- Run acceptance/review regression tests for every rule change. Measure false
  acceptance and unnecessary review separately, including zero tax, optional
  omissions, genuine unusual names, repeated runs and model changes.

The judge currently runs **separately**, so its verdict cannot change the UI's
review decision. Integrating it into processing would be a separate product
change with explicit cost, latency and failure-handling choices. Human review
currently means a UI state plus a trace event; a real review queue with decisions,
corrections, identities and history is future work.

## Learnings: improve the schema

The minimal schema describes values, but not their provenance or certainty.
Recommended evolution, to review before implementation:

| Proposed addition | Why it helps |
| --- | --- |
| `schema_version` and migration rules | Existing JSON uploads and historical traces remain interpretable |
| `document_type` / `document_status` | Distinguish issued invoices from drafts, estimates and credit notes |
| Extraction envelope: `invoice`, `field_evidence`, `issues` | Preserve source qualification without polluting accounting fields |
| Per-field status and exact source references | Distinguish missing, ambiguous, provisional and confirmed values |
| Structured `review_reasons` | Make the decision inspectable and suitable for a later human-review queue |
| Controlled currency values | Prevent placeholders from looking like valid currency codes |
| Explicit amount/currency precision policy | Represent monetary values consistently across supported currencies |

Use separate contracts for a **partial extraction** and an **accepted invoice**.
Partial extraction must allow null/missing values so ambiguity survives. The
accepted-invoice contract should continue requiring confirmed mandatory fields.
Do not solve the problem by making required fields optional in accepted invoices.
Cross-field arithmetic and nuanced business rules still belong in the validator;
ordinary JSON Schema cannot express every relationship or source-text meaning.

Schema changes alone also cannot detect invented but plausible data. Evidence,
validation and model instructions must agree on the meaning of “confirmed.”
Do not treat an LLM confidence score as proof. Preserve raw source and normalized
values for review. Decide discounts, tax breakdowns, credit notes and multi-currency
support deliberately instead of expanding the schema incidentally.

## Suggested improvement order

Start with the confirmed provisional-tax failure and placeholder cases: add
contrastive skill examples, then an uncertainty/evidence contract and shared
review rules for both parsing routes. Agree on draft and date-order policies
before enforcing them. Turn the seven probes into regression cases, add positive
neighbors and held-out documents, and compare skill/schema versions using saved
traces. Human approval should precede applying any proposed rule change.

The app remains a local prototype: the shared `actions.json` array is rewritten
per action, logs contain invoice text, there is no image ingestion, no persistent
human-review queue, no automatic retraining, and no mechanism that promotes
suggested improvements into production rules automatically.

## OpenAI references

The integration follows OpenAI's [function-calling documentation](https://developers.openai.com/api/docs/guides/function-calling).
The default [GPT-4.1 mini model](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
supports the Responses API and function calling. Change `OPENAI_MODEL` locally
to use another compatible model available to your API account.
