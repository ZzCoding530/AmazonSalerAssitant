"""下载中间件：UA 轮换、代理池轮换、重试与指数退避、熔断。

反封禁策略链（按顺序降级）：
1. UA 轮换 → 2. 代理池轮换 → 3. 请求间隔指数退避 → 4. 切换 Playwright → 5. 熔断告警。
"""

from __future__ import annotations

import random
from typing import List, Optional

import requests
from scrapy import signals
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message


def fetch_proxies(pool_url: str) -> List[str]:
    """从代理池拉取代理列表；失败返回空列表（不阻塞采集）。"""
    if not pool_url:
        return []
    try:
        resp = requests.get(pool_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return list(data.get("proxies", data) if isinstance(data, dict) else data)
    except Exception:
        return []


class RandomUserAgentMiddleware:
    """UA 轮换。"""

    def __init__(self, user_agents: List[str], rng: Optional[random.Random] = None):
        self._user_agents = list(user_agents)
        self._rng = rng or random.Random()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings.getlist("ADGENIE_USER_AGENTS") or [])

    def process_request(self, request, spider):
        if self._user_agents:
            request.headers["User-Agent"] = self._rng.choice(self._user_agents)


class ProxyPoolMiddleware:
    """代理池轮换。"""

    def __init__(self, proxies: List[str], rng: Optional[random.Random] = None):
        self._proxies = list(proxies)
        self._rng = rng or random.Random()

    @classmethod
    def from_crawler(cls, crawler):
        proxies = crawler.settings.getlist("ADGENIE_PROXIES") or []
        pool_url = crawler.settings.get("PROXY_POOL_URL", "")
        if not proxies and pool_url:
            proxies = fetch_proxies(pool_url)
        return cls(proxies)

    def process_request(self, request, spider):
        if self._proxies:
            request.meta["proxy"] = self._rng.choice(self._proxies)

    def process_exception(self, request, exception, spider):
        # 代理失败：轮换到下一个代理后重试
        if self._proxies and request.meta.get("proxy"):
            next_proxy = self._rng.choice(self._proxies)
            request.meta["proxy"] = next_proxy
            return request


class BackoffRetryMiddleware(RetryMiddleware):
    """重试 + 指数退避（基于 config.retry_max / backoff_factor）。"""

    def __init__(self, settings):
        super().__init__(settings)
        self._backoff_factor = float(settings.getfloat("ADGENIE_BACKOFF_FACTOR", 2.0))

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def _retry(self, request, reason, spider):
        retries = request.meta.get("retry_times", 0) + 1
        if retries <= self.max_retry_times:
            # 指数退避：通过 download_delay 逐次放大
            request.meta["retry_times"] = retries
            request.meta["download_delay"] = self._backoff_factor ** (retries - 1)
            retry_req = request.copy()
            retry_req.dont_filter = True
            return retry_req
        return None


class CircuitBreakerMiddleware:
    """熔断：连续失败达到阈值后打开熔断，后续请求直接拒绝并告警。"""

    def __init__(self, failure_threshold: int = 5):
        self._threshold = failure_threshold
        self._failures = 0
        self._open = False

    @classmethod
    def from_crawler(cls, crawler):
        threshold = crawler.settings.getint("ADGENIE_CIRCUIT_FAILURES", 5)
        middleware = cls(threshold)
        crawler.signals.connect(middleware._spider_closed, signal=signals.spider_closed)
        return middleware

    def _spider_closed(self, spider):
        self._failures = 0
        self._open = False

    def process_exception(self, request, exception, spider):
        if self._open:
            spider.logger.warning("circuit breaker open, blocking request: %s", request.url)
            request.meta["circuit_open"] = True
            return None
        self._failures += 1
        if self._failures >= self._threshold:
            self._open = True
            spider.logger.error("circuit breaker opened after %d failures", self._failures)
        return None
