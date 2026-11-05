"""机制六：冻结 manifest 可审计协议 单元测试。"""

from adgenie.data.domain import ScoreReport
from adgenie.data.memory import InMemoryScoreReportStore
from adgenie.mechanisms.manifest import (
    ManifestService,
    compute_evidence_fingerprint,
    freeze_manifest,
)


def test_fingerprint_deterministic_and_order_independent():
    assert compute_evidence_fingerprint(["R-1", "R-2"]) == \
        compute_evidence_fingerprint(["R-2", "R-1"])
    assert compute_evidence_fingerprint(["R-1"]) != compute_evidence_fingerprint(["R-2"])


def test_freeze_manifest_fields():
    m = freeze_manifest("v1", "glm-4-plus", 0.0, "abc123")
    assert m.rubric_version == "v1"
    assert m.model_name == "glm-4-plus"
    assert m.temperature == 0.0
    assert m.evidence_snapshot == "abc123"
    assert "rubric_version" in m.to_dict()


def test_replay_returns_full_record():
    store = InMemoryScoreReportStore()
    report = ScoreReport(
        report_id="RPT-1", listing_id="L", copy_version="c1", rubric_version="v1",
        model_name="glm-4-plus", temperature=0.0, alignment_score=0.8,
        persuasion_score=0.9, detail=[{"type": "alignment", "score": 0.8}],
        evidence_snapshot="snap",
    )
    store.save(report)
    service = ManifestService(store)
    record = service.replay("RPT-1")
    assert record["report_id"] == "RPT-1"
    assert record["rubric_version"] == "v1"
    assert record["evidence_snapshot"] == "snap"
    assert record["detail"][0]["score"] == 0.8


def test_replay_missing_returns_none():
    service = ManifestService(InMemoryScoreReportStore())
    assert service.replay("nope") is None


def test_verify_snapshot():
    store = InMemoryScoreReportStore()
    store.save(ScoreReport(
        report_id="RPT-2", listing_id="L", copy_version="c1", rubric_version="v1",
        model_name="glm", temperature=0.0, alignment_score=1.0, persuasion_score=1.0,
        evidence_snapshot="snap-a",
    ))
    service = ManifestService(store)
    assert service.verify("RPT-2", "snap-a") is True
    assert service.verify("RPT-2", "snap-b") is False
