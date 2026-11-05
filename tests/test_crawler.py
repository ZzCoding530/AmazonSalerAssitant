"""采集层离线测试：fixture 驱动的 Spider 解析 + Pipeline + 中间件（不联网）。"""

from pathlib import Path

import pytest
from scrapy.exceptions import DropItem
from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings

from adgenie.crawler.items import ReviewItem
from adgenie.crawler.middlewares import (
    BackoffRetryMiddleware,
    CircuitBreakerMiddleware,
    ProxyPoolMiddleware,
    RandomUserAgentMiddleware,
)
from adgenie.crawler.pipelines import (
    CleanPipeline,
    DedupPipeline,
    StoragePipeline,
    VerifiedFilterPipeline,
)
from adgenie.crawler.spiders.competitor_spider import CompetitorSpider
from adgenie.crawler.spiders.review_spider import ReviewSpider
from adgenie.data.memory import (
    InMemoryCacheStore,
    InMemoryMaterialStore,
    InMemoryReviewStore,
)

FIXTURES = Path(__file__).resolve().parents[1] / "src" / "adgenie" / "crawler" / "fixtures"


def _response(name: str, url: str) -> HtmlResponse:
    body = (FIXTURES / name).read_bytes()
    return HtmlResponse(url=url, body=body, encoding="utf-8")


def _items(gen):
    import scrapy
    out, reqs = [], []
    for x in gen:
        if isinstance(x, scrapy.Item):
            out.append(x)
        else:
            reqs.append(x)
    return out, reqs


# ---- Spider 解析 ----
def test_review_spider_parses_list_and_pagination():
    spider = ReviewSpider(target="http://x/reviews", listing_id="L-1001", asin="B000000001")
    items, reqs = _items(spider.parse(_response("reviews_list.html", "http://x/reviews")))
    assert len(items) == 4
    assert len(reqs) == 1  # 分页 follow
    verified = {it["review_id"]: it["is_verified"] for it in items}
    assert verified["R-001"] is True
    assert verified["R-003"] is False  # 无 Verified Purchase 标识


def test_review_spider_parses_detail_page():
    spider = ReviewSpider(target="http://x/detail", listing_id="L-1001", asin="B000000001")
    items, _ = _items(spider.parse_detail(_response("review_detail.html", "http://x/detail")))
    assert len(items) == 1
    assert items[0]["review_id"] == "R-010"
    assert items[0]["is_verified"] is True


def test_review_spider_tolerates_malformed_page():
    spider = ReviewSpider(target="http://x/malformed", listing_id="L-1001", asin="B000000001")
    items, _ = _items(spider.parse(_response("reviews_malformed.html", "http://x/malformed")))
    # 4 个 review 块全部被解析，缺失字段由 Pipeline 兜底，Spider 不崩溃
    assert len(items) == 4
    ids = [it["review_id"] for it in items]
    assert "" in ids  # 缺失 review-id 的块被解析为空的 review_id


def test_competitor_spider_parses_materials():
    spider = CompetitorSpider(target="http://x/comp")
    items, reqs = _items(spider.parse(_response("competitor_list.html", "http://x/comp")))
    assert len(items) == 2
    assert items[0]["material_id"] == "MAT-001"
    assert items[0]["selling_points"] == ["battery life", "fast charging"]
    assert len(reqs) == 1


# ---- Pipeline ----
def _review_item(review_id="R-001", listing_id="L-1001", is_verified=True,
                 rating=4.5, content="battery good"):
    return ReviewItem(review_id=review_id, listing_id=listing_id, asin="A",
                      reviewer_id="u", rating=rating, title="t", content=content,
                      is_verified=is_verified)


def test_clean_pipeline_drops_missing_required_field():
    clean = CleanPipeline()
    bad = ReviewItem(review_id="", listing_id="L-1001")
    with pytest.raises(DropItem):
        clean.process_item(bad, None)


def test_verified_filter_marks_unverified_and_shill():
    vf = VerifiedFilterPipeline()
    ok = vf.process_item(_review_item(is_verified=True), None)
    assert ok["filtered_reason"] == ""
    nv = vf.process_item(_review_item(is_verified=False, rating=3.0, content="meh"), None)
    assert nv["filtered_reason"] == "unverified"
    shill = vf.process_item(_review_item(is_verified=False, rating=5.0, content="BEST BEST BEST"), None)
    assert shill["filtered_reason"] == "shill"


def test_dedup_pipeline_skips_duplicate():
    rs = InMemoryReviewStore()
    dedup = DedupPipeline(rs, InMemoryCacheStore())
    item = _review_item()
    assert dedup.process_item(item, None) is item
    with pytest.raises(DropItem):
        dedup.process_item(_review_item(), None)  # 同 review_id → 去重跳过


def test_storage_pipeline_persists_and_marks_filtered():
    rs = InMemoryReviewStore()
    ms = InMemoryMaterialStore()
    store_p = StoragePipeline(rs, ms)
    item = _review_item(review_id="R-1")
    store_p.process_item(item, None)
    assert rs.exists("L-1001", "R-1") is True
    assert len(rs.get_verified("L-1001")) == 1


# ---- 中间件 ----
def test_user_agent_rotation():
    mw = RandomUserAgentMiddleware(["ua-1", "ua-2"])
    req = Request("http://x")
    mw.process_request(req, None)
    assert req.headers["User-Agent"].decode() in ("ua-1", "ua-2")


def test_proxy_rotation_and_exception_recovery():
    mw = ProxyPoolMiddleware(["http://p1", "http://p2"])
    req = Request("http://x")
    mw.process_request(req, None)
    assert req.meta["proxy"] in ("http://p1", "http://p2")
    retried = mw.process_exception(req, Exception("proxy fail"), None)
    assert retried is req  # 轮换代理后重试


def test_backoff_retry_increments_and_backs_off():
    mw = BackoffRetryMiddleware(Settings({"RETRY_TIMES": 3, "ADGENIE_BACKOFF_FACTOR": 2.0}))
    req = Request("http://x")
    retry = mw._retry(req, "500", None)
    assert retry is not None
    assert retry.meta["retry_times"] == 1
    assert retry.meta["download_delay"] == 1.0  # 2.0 ** 0


class _FakeSpider:
    def __init__(self):
        self._logs = []
        self.logger = self

    def warning(self, msg, *a): self._logs.append(("warn", msg))
    def error(self, msg, *a): self._logs.append(("error", msg))


def test_circuit_breaker_opens_after_threshold():
    mw = CircuitBreakerMiddleware(failure_threshold=3)
    spider = _FakeSpider()
    for _ in range(3):
        mw.process_exception(Request("http://x"), Exception("fail"), spider)
    assert mw._open is True
    mw.process_exception(Request("http://x"), Exception("fail"), spider)
    assert any(k == "warn" for k, _ in spider._logs)
