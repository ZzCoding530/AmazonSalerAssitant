"""引擎选择策略：由配置或反爬强度探测选择 Scrapy / Playwright。"""

from __future__ import annotations

from adgenie.config import CrawlerConfig
from adgenie.crawler.base import CrawlTarget


class EngineSelector:
    def __init__(self, config: CrawlerConfig):
        self._config = config

    def select(self, target: CrawlTarget, anti_crawl_signal: bool = False) -> str:
        """返回 'scrapy' 或 'playwright'。"""
        engine = self._config.engine
        if engine in ("scrapy", "playwright"):
            return engine
        # auto：探测到反爬（封禁信号）则切 Playwright，否则 Scrapy
        return "playwright" if anti_crawl_signal else "scrapy"
