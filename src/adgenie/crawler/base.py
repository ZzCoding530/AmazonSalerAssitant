"""采集层统一抽象接口。

双引擎（Scrapy / Playwright）通过 ``BaseCrawler`` 统一调度，
由配置或反爬强度探测选择引擎。禁止只实现其一后删掉另一接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class TargetType(str, Enum):
    REVIEW = "review"
    COMPETITOR = "competitor"


@dataclass
class CrawlTarget:
    url: str
    target_type: TargetType
    listing_id: str = ""
    asin: str = ""


@dataclass
class CrawlResult:
    items: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)  # base64 或路径引用


class BaseCrawler(ABC):
    @abstractmethod
    async def crawl(self, target: CrawlTarget) -> CrawlResult:
        """执行采集，返回解析结果（真实实现，不做 mock）。"""

    @abstractmethod
    async def health_check(self) -> bool:
        """引擎健康检查。"""

    @abstractmethod
    def supports(self, target_type: TargetType) -> bool:
        """声明该引擎支持的页面类型。"""
