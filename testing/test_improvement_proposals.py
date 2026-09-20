import json

from testing.improvement_proposals import propose, render


def save(tmp_path, data):
    path = tmp_path / "results.json"
    path.write_text(json.dumps(data))
    return path


def test_observed_gaps_generate_evidence_linked_pending_proposals(tmp_path):
    path = save(tmp_path, [{"file": "example.txt", "status": "success", "human_review_requested": False, "concern": "Tax is provisional", "invoice": {"tax_amount": 0}}])
    report = propose([path])
    assert report["status"] == "pending_human_review"
    assert report["changes_applied"] is False and report["llm_invoked"] is False
    assert report["proposals"][0]["id"] == "provisional_values"
    assert report["proposals"][0]["review"]["decision"] == "pending"
    assert report["proposals"][0]["evidence"][0]["sha256"]
    assert "provisional" in render(report)


def test_successful_review_control_does_not_generate_change(tmp_path):
    path = save(tmp_path, [{"file": "control.txt", "status": "human_review", "human_review_requested": True, "concern": "Missing tax"}])
    assert propose([path])["proposals"] == []


def test_judge_text_failure_proposes_grounding(tmp_path):
    path = save(tmp_path, {"status": "failed", "verdict": {"text_correct": False, "field_checks": [{"path": "supplier.name", "text_correct": False}]}})
    assert propose([path])["proposals"][0]["id"] == "text_grounding"


def test_judge_error_does_not_invent_a_rule_change(tmp_path):
    path = save(tmp_path, {"status": "error", "errors": ["OpenAI timeout"]})
    report = propose([path])
    assert report["proposals"] == []
    assert "did not complete" in report["notes"][0]["message"]


def test_bad_judge_evidence_targets_evaluator_not_skill(tmp_path):
    path = save(tmp_path, {"status": "failed", "judge_errors": ["Quote absent"], "verdict": {"text_correct": False}})
    assert [p["id"] for p in propose([path])["proposals"]] == ["evaluation_quality"]


def test_repeated_findings_group_evidence(tmp_path):
    case = {"status": "success", "human_review_requested": False, "concern": "Currency TBD"}
    path = save(tmp_path, [case, case])
    proposals = propose([path])["proposals"]
    assert len(proposals) == 1 and len(proposals[0]["evidence"]) == 2
