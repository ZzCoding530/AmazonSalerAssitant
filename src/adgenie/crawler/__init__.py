"""采集层：双引擎 + 代理池 + 限流 + 增量去重。"""

from adgenie.crawler.base import BaseCrawler, CrawlResult, CrawlTarget, TargetType
from adgenie.crawler.engine_selector import EngineSelector

__all__ = ["BaseCrawler", "CrawlResult", "CrawlTarget", "TargetType", "EngineSelector"]
