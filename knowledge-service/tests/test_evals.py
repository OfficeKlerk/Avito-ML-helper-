import json

from evals.run import main, meets_targets


def test_quality_gate_and_reproducible_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["evals.run", "--check", "--output-dir", str(tmp_path)])
    assert main() == 0
    report = json.loads((tmp_path / "latest.json").read_text())
    assert meets_targets(report)
    assert report["metrics"]["improved"]["dev"]["cases"] == 44
    assert report["metrics"]["improved"]["holdout"]["cases"] == 20
    assert report["metrics"]["improved"]["all"]["leaks"] == 0
    assert len(report["corpus_sha256"]) == 64 and len(report["cases_sha256"]) == 64
    assert "holdout" in (tmp_path / "latest.md").read_text()
    # The gate must fail if either access isolation or no-answer quality regresses.
    report["metrics"]["improved"]["holdout"]["leaks"] = 1
    assert not meets_targets(report)
    report["metrics"]["improved"]["holdout"]["leaks"] = 0
    report["metrics"]["improved"]["holdout"]["empty_accuracy"] = 0.0
    assert not meets_targets(report)
