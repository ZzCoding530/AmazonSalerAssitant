"""机制三：构造式评分校准 单元测试。"""

from adgenie.mechanisms.calibration import inject_defect, permutation_test, run_calibration
from adgenie.models import FakeLLM


def _judge():
    judge = FakeLLM(model="glm-4-plus", temperature=0.0)
    # 命中缺陷标记 → 低分（被检出）；否则 → 高分
    judge.register("contradicted", '{"score": 0.4, "items": []}')
    judge.register("广告文案评分裁判", '{"score": 0.9, "items": []}')
    return judge


def test_inject_missing_key_concern_removes_keyword():
    out = inject_defect("battery waterproof fast", "missing_key_concern",
                        ["battery", "waterproof"])
    assert "battery" not in out
    assert "waterproof" in out


def test_inject_contradicts_evidence_appends_marker():
    out = inject_defect("battery good", "contradicts_evidence", [])
    assert "contradicted" in out


def test_permutation_test_p_value_in_range():
    p = permutation_test([True, True, True, True], [False, False, False, False],
                         iterations=500, seed=1)
    assert 0.0 < p <= 1.0


def test_run_calibration_separates_detection_and_false_alarm():
    report, _, _ = _run()
    # 检出率与误判率分开报告，禁止合并成单一准确率
    assert hasattr(report, "detection_rate")
    assert hasattr(report, "false_alarm_rate")
    assert hasattr(report, "p_value")
    assert report.detection_rate == 1.0
    assert report.false_alarm_rate == 0.0
    assert report.p_value < 0.05


def _run():
    return _run_calibration_tuple()


def _run_calibration_tuple():
    judge = _judge()
    result = run_calibration(
        judge=judge,
        rubric_version="v1",
        base_copy="battery waterproof fast charging lightweight",
        concern_keywords=["battery", "waterproof"],
        evidences=[{"review_id": "R-001", "quote": "good battery"}],
        defect_types=["contradicts_evidence"],
        n_perturbed=6,
        n_placebo=6,
        quality_threshold=0.7,
        permutation_iterations=500,
        seed=7,
    )
    return result.report, result.perturbed_detected, result.placebo_detected


def test_run_calibration_returns_perturbed_and_placebo_flags():
    _, perturbed, placebo = _run()
    assert all(perturbed)
    assert not any(placebo)
