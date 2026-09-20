from streamlit.testing.v1 import AppTest

from invoice_agent.config import ROOT, Settings
from invoice_agent.runner import run_invoice


def test_initial_ui():
    app = AppTest.from_file(str(ROOT / "app.py")).run()
    assert not app.exception
    assert app.title[0].value == "Invoice parser"
    assert app.button[0].disabled


def test_success_ui(tmp_path):
    result = run_invoice((ROOT / "samples/invoice.json").read_bytes(), "invoice.json", data_dir=tmp_path)
    app = AppTest.from_file(str(ROOT / "app.py"))
    app.session_state["result"] = result
    app.run()
    assert not app.exception
    assert "All great" in app.success[0].value
    assert len(app.json) == 1


def test_ui_shows_all_errors_for_review(tmp_path):
    result = run_invoice(b"Plain invoice", "invoice.txt", data_dir=tmp_path, settings=Settings())
    app = AppTest.from_file(str(ROOT / "app.py"))
    app.session_state["result"] = result
    app.run()
    assert not app.exception
    assert "Human review required" in app.error[0].value
    assert len(app.error) == len(result.errors) + 1


def test_new_upload_clears_previous_result(tmp_path):
    result = run_invoice((ROOT / "samples/invoice.json").read_bytes(), "invoice.json", data_dir=tmp_path)
    app = AppTest.from_file(str(ROOT / "app.py"))
    app.session_state["result"] = result
    app.session_state["upload_identity"] = ("previous.json", "old-hash")
    app.run()
    assert not app.exception
    assert not app.success
