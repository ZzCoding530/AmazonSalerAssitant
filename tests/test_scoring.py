"""机制二：双标尺评分 单元测试。"""

import pytest

from adgenie.mechanisms.scoring import (
    compute_alignment,
    extract_keywords,
    score_persuasion,
)
from adgenie.models import FakeLLM


def test_extract_keywords_lowercases_and_removes_stopwords():
    kws = extract_keywords("Battery life is Very Good")
    assert "battery" in kws
    assert "life" in kws
    assert "is" not in kws  # 停用词
    assert "very" not in kws


def test_alignment_full_coverage():
    a = compute_alignment("battery waterproof fast charging lightweight",
                          ["battery", "waterproof", "charging", "lightweight"])
    assert a.score == 1.0
    assert a.missing == []


def test_alignment_deducts_missing_concern():
    # 广告文案缺失 "waterproof" 卖点 → 对齐度扣分
    a = compute_alignment("battery fast charging lightweight",
                          ["battery", "waterproof", "charging", "lightweight"])
    assert a.score == 0.75
    assert "waterproof" in a.missing


def test_alignment_empty_concerns_is_one():
    assert compute_alignment("anything", []).score == 1.0


def test_persuasion_requires_judge_temp_zero():
    judge = FakeLLM(model="glm-4-plus", temperature=0.7)  # 违规温度
    with pytest.raises(ValueError):
        score_persuasion(judge, "v1", "copy", [])


def test_persuasion_parses_rubric_json():
    judge = FakeLLM(model="glm-4-plus", temperature=0.0)
    judge.register("广告文案评分裁判",
                   '{"score": 0.82, "items": [{"dimension": "relevance", "score": 0.9, '
                   '"deductions": [{"item": "missing", "reason": "no evidence", '
                   '"evidence_ref": "R-001"}]}]}')
    result = score_persuasion(judge, "v1", "battery good", [{"review_id": "R-001"}])
    assert result.score == 0.82
    assert result.items[0]["dimension"] == "relevance"
    assert result.items[0]["deductions"][0]["evidence_ref"] == "R-001"


def test_persuasion_rejects_invalid_schema():
    judge = FakeLLM(model="glm-4-plus", temperature=0.0)
    judge.register("广告文案评分裁判", '{"not_a_score": true}')
    with pytest.raises(ValueError):
        score_persuasion(judge, "v1", "copy", [])
