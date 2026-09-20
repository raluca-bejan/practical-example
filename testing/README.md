# Separate invoice evaluation package

This judge reads a **saved agent trace**. It does not run extraction again and is
never called by the Streamlit application. It compares the final invoice with
the schema, field types, arithmetic, and the original source text in the trace.

Apply both change ZIPs over the existing `practical-example` folder. From the
project root:

```sh
make setup-tests
make test
make test_llm
```

`make test` runs offline tests. `make test_llm` makes **one real OpenAI request**
using the existing local `.env` and evaluates `docs/demo-invoice-txt.jsonl` by
default: the previously saved successful semantic run. It does not invoke the
invoice agent. To select another saved run:

```sh
make test_llm TRACE=traces/your-run-id.jsonl
```

Set `OPENAI_JUDGE_MODEL` in your local `.env` to change the judge model; the default
is `gpt-4.1-mini`. The judge is a separate request with its own instructions and
no extraction conversation history. Its text assessment is model judgment;
the local schema/type check cannot be overridden by a positive model verdict.

The testing folder can also run independently of the application code:

```sh
cd testing
make setup
make test
make test_llm APP_DIR=..  # or supply TRACE=..., SCHEMA=..., ENV_FILE=...
```

It needs a trace containing one completed run and its original `source_text`,
the matching schema file, and a local API key. A recorded schema hash, when
present, must match; evaluating against a different schema fails before the API
call. No API key is included in either archive.

## Saved results

The real judge run on the existing saved agent trace passed all 13 field checks.
Its readable result is included in [reports/saved-trace-judge.txt](reports/saved-trace-judge.txt),
with [the OpenAI invocation reference](reports/saved-trace-invocation.json).
These are explicitly selected synthetic-demo artifacts, not general user logs.

Each evaluation creates `testing/output/<evaluation_id>/`:

- **`result.txt`**: readable verdict, schema/type/text/arithmetic findings,
  field-by-field evidence, errors, and agent/judge invocation references.
- `result.json`: the same structured result for automated evaluation.
- `invocation.json`: whether the judge request was attempted, whether a response
  arrived, the OpenAI response ID, HTTP request ID, model, and token usage.
- `input_reference.json`: agent run ID, trace hash, source invoice, extracted
  result, schema, and whether the agent invoked an LLM, with its response IDs.
- `request.json`: all non-secret judge request parameters, including its prompt
  and structured-output schema.

`testing/output/latest.json` points to the latest report. Judge failures still
produce a TXT/JSON report when the output directory is writable. An attempted
request is distinguished from a confirmed response; no API error counts as a
pass. Response IDs are saved as audit references (responses use `store=False`,
so this does not promise later API retrieval).

The judge must assess every expected field exactly once and quote source text
verbatim for a positive text finding. Missing fields, mismatches, malformed
reports, incomplete responses and refusals cannot silently pass. The exit codes
are `0` for passed, `1` for an unsuccessful evaluation, and `2` for execution or
configuration errors (Make itself returns a nonzero status for either failure).

`make package` creates an application-only ZIP. `make package-tests` creates the
separate testing ZIP. `make package-changes` produces two smaller archives with
only files changed or added in this update. Test output is local and excluded
from packaging by default; source invoices and evaluation reports are not
published automatically.

OpenAI integration reference: [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
