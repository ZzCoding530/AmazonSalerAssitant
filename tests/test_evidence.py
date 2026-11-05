"""机制一：证据锚定与编号白名单 单元测试。"""

from adgenie.mechanisms.evidence import (
    build_whitelist,
    enforce_evidence,
    freeze_batch,
    validate_evidence,
)


def _reviews():
    from adgenie.data.domain import RawReview
    return [
        RawReview(review_id="R-001", listing_id="L", asin="A", reviewer_id="u",
                  rating=5.0, content="good", is_verified=True),
        RawReview(review_id="R-002", listing_id="L", asin="A", reviewer_id="u",
                  rating=4.0, content="ok", is_verified=True),
        RawReview(review_id="NV-1", listing_id="L", asin="A", reviewer_id="u",
                  rating=5.0, content="shill", is_verified=False),
    ]


def test_whitelist_only_verified():
    wl = build_whitelist(_reviews())
    assert wl == {"R-001", "R-002"}
    assert "NV-1" not in wl


def test_validate_rejects_fabricated_id():
    wl = {"R-001"}
    result = validate_evidence([{"review_id": "R-001"}, {"review_id": "FAKE-9"}], wl)
    assert result.passed is False
    assert result.action == "REJECT_AND_REPROMPT"
    assert result.violations == ["FAKE-9"]


def test_validate_passes_all_whitelisted():
    wl = {"R-001", "R-002"}
    result = validate_evidence([{"review_id": "R-001"}, {"review_id": "R-002"}], wl)
    assert result.passed is True
    assert result.action == "PASS"


def test_enforce_evidence_rejects_and_drops_after_retries():
    wl = {"R-001"}
    claims = [{"review_id": "R-001"}, {"review_id": "FAKE-1"}]
    # 每次产出都带编造编号 → 用尽重试后剔除编造结论
    accepted, rejected, attempts = enforce_evidence(lambda: claims, wl, max_reprompt=2)
    assert [c["review_id"] for c in accepted] == ["R-001"]
    assert [c["review_id"] for c in rejected] == ["FAKE-1"]
    assert attempts == 3  # 1 次初始 + 2 次重提


def test_enforce_evidence_accepts_immediately():
    wl = {"R-001"}
    accepted, rejected, attempts = enforce_evidence(
        lambda: [{"review_id": "R-001"}], wl, max_reprompt=2)
    assert attempts == 1
    assert rejected == []


def test_freeze_batch_deterministic_and_order_independent():
    reviews = _reviews()
    assert freeze_batch(reviews) == freeze_batch(list(reversed(reviews)))
    assert freeze_batch(reviews[:1]) != freeze_batch(reviews)
