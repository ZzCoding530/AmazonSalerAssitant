"""Scrapy 引擎实现（生产级，双引擎之一）。

通过 ``BaseCrawler`` 统一接口调度。内部使用 ``CrawlerProcess`` 运行真实
Spider + Pipeline + 中间件。离线测试时对 Spider.parse / Pipeline / Middleware
分别做 fixture 驱动测试（见 tests/test_crawler.py），无需联网。
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from scrapy.crawler import CrawlerProcess

from adgenie.config import CrawlerConfig
from adgenie.crawler.base import BaseCrawler, CrawlResult, CrawlTarget, TargetType
from adgenie.crawler.engine_selector import EngineSelector
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
from adgenie.data.ports import CacheStore, MaterialStore, ReviewStore


class CollectorPipeline:
    """把 Item 收集到共享列表，供引擎返回。"""

    def __init__(self, collector: List[dict]):
        self._collector = collector

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings.get("ADGENIE_COLLECTOR", []))

    def process_item(self, item, spider):
        self._collector.append(dict(item))
        return item


class ScrapyEngine(BaseCrawler):
    def __init__(self, config: CrawlerConfig, review_store: ReviewStore,
                 cache: CacheStore, material_store: MaterialStore,
                 selector: Optional[EngineSelector] = None):
        self._config = config
        self._review_store = review_store
        self._cache = cache
        self._material_store = material_store
        self._selector = selector or EngineSelector(config)

    def supports(self, target_type: TargetType) -> bool:
        return True  # Scrapy 支持评论与竞品两类页面

    async def health_check(self) -> bool:
        return True

    async def crawl(self, target: CrawlTarget) -> CrawlResult:
        return await asyncio.to_thread(self._crawl_sync, target)

    def _spider_cls(self, target: CrawlTarget):
        if target.target_type == TargetType.COMPETITOR:
            return CompetitorSpider
        return ReviewSpider

    def _build_settings(self, collector: List[dict]) -> dict:
        return {
            "DOWNLOAD_DELAY": self._config.download_delay,
            "AUTOTHROTTLE_ENABLED": self._config.autothrottle_enabled,
            "AUTOTHROTTLE_TARGET_CONCURRENCY": self._config.autothrottle_target_concurrency,
            "RETRY_ENABLED": True,
            "RETRY_TIMES": self._config.retry_max,
            "ADGENIE_USER_AGENTS": self._config.user_agents,
            "ADGENIE_BACKOFF_FACTOR": self._config.backoff_factor,
            "ADGENIE_CIRCUIT_FAILURES": self._config.circuit_breaker_failures,
            "ADGENIE_COLLECTOR": collector,
            "ADGENIE_REVIEW_STORE": self._review_store,
            "ADGENIE_MATERIAL_STORE": self._material_store,
            "ADGENIE_CACHE_STORE": self._cache,
            "DOWNLOADER_MIDDLEWARES": {
                RandomUserAgentMiddleware: 400,
                ProxyPoolMiddleware: 750,
                BackoffRetryMiddleware: 550,
                CircuitBreakerMiddleware: 560,
            },
            "ITEM_PIPELINES": {
                CollectorPipeline: 100,
                CleanPipeline: 200,
                VerifiedFilterPipeline: 300,
                DedupPipeline: 400,
                StoragePipeline: 500,
            },
        }

    def _crawl_sync(self, target: CrawlTarget) -> CrawlResult:
        collector: List[dict] = []
        settings = self._build_settings(collector)
        process = CrawlerProcess(settings=settings)
        spider_cls = self._spider_cls(target)
        process.crawl(spider_cls, target=target.url,
                      listing_id=target.listing_id, asin=target.asin)
        process.start(stop_after_crawl=True)
        return CrawlResult(items=collector, errors=[], screenshots=[])
