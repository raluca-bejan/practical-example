import hashlib

import streamlit as st

from invoice_agent.runner import run_invoice
from invoice_agent.schema import dumps, loads
from invoice_agent.tracing import redact

st.set_page_config(page_title="Invoice parser", page_icon="🧾", layout="centered")
st.title("Invoice parser")
st.write("Upload an invoice as text. We check structured JSON first and use AI extraction when needed.")
st.caption("UTF-8 .txt or .json · 100 KB maximum · Review requests appear here")

upload = st.file_uploader("Invoice", type=["txt", "json"])
content = upload.getvalue() if upload is not None else None
identity = (upload.name, hashlib.sha256(content).hexdigest()) if upload is not None else None
if identity != st.session_state.get("upload_identity"):
    st.session_state.pop("result", None)
    st.session_state.upload_identity = identity

if st.button("Parse invoice", type="primary", disabled=upload is None):
    st.session_state.pop("result", None)
    with st.spinner("Parsing and validating invoice…"):
        try:
            st.session_state.result = run_invoice(content, upload.name)
        except Exception:
            st.error("Could not save the run log. Check that actions.json is valid and the project folder is writable, then retry.")

result = st.session_state.get("result")
if result:
    if result.status == "success":
        st.success("All great — invoice parsed and validated.")
    else:
        st.error("Human review required.")
        st.write("Review the source invoice and the errors below. Correct the invoice file and upload it again.")

    st.caption(f"Route: {result.route} · Run: {result.run_id}")
    if result.invoice is not None:
        st.subheader("Extracted invoice")
        formatted = dumps(redact(result.invoice), indent=2)
        st.json(formatted)
        st.download_button("Download extracted JSON", formatted, file_name="invoice.json", mime="application/json")

    if result.errors:
        st.subheader("Errors encountered")
        for error in result.errors:
            message = redact(f"{error['stage']} · {error['field']}: {error['message']}")
            if result.status == "success":
                st.warning(message + " (Recovered by semantic parsing.)")
            else:
                st.error(message)

    try:
        trace = result.trace_path.read_text(encoding="utf-8")
        with st.expander("Run actions"):
            for line in trace.splitlines():
                action = loads(line)
                st.text(f"{action['sequence']}. {action['message']}")
        st.download_button("Download JSONL trace", trace, file_name=result.trace_path.name, mime="application/x-ndjson")
    except OSError:
        st.error("Could not read the saved trace file.")
