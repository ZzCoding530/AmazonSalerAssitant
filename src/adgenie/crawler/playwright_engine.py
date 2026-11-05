"""Playwright 引擎实现（生产级，双引擎之一）。

浏览器上下文管理与复用、显式等待（禁止裸 sleep）、动态元素定位与容错、
截图留证、异常恢复与上下文重建。
"""

from __future__ import annotations

import asyncio
import base64
from typing import List, Optional

from adgenie.config import CrawlerConfig
from adgenie.crawler.base import BaseCrawler, CrawlResult, CrawlTarget, TargetType


class PlaywrightEngine(BaseCrawler):
    def __init__(self, config: CrawlerConfig, headless: bool = True):
        self._config = config
        self._headless = headless
        self._pw = None
        self._browser = None
        self._context = None

    def supports(self, target_type: TargetType) -> bool:
        return True

    async def health_check(self) -> bool:
        return True

    async def _ensure_context(self):
        if self._context is not None:
            return self._context
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)
        ua = (self._config.user_agents[0] if self._config.user_agents else None)
        self._context = await self._browser.new_context(user_agent=ua)
        return self._context

    async def _reset(self) -> None:
        """异常恢复：关闭并重建浏览器上下文。"""
        try:
            if self._context is not None:
                await self._context.close()
        finally:
            self._context = None
            self._browser = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None

    async def _locate(self, page, selectors: List[str], timeout_ms: int = 5000):
        """动态元素定位与容错：依次尝试候选选择器，返回首个命中。"""
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                await locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except Exception:
                continue
        return None

    async def _screenshot(self, page) -> str:
        raw = await page.screenshot(type="png", full_page=False)
        return base64.b64encode(raw).decode("ascii")

    async def crawl(self, target: CrawlTarget) -> CrawlResult:
        try:
            context = await self._ensure_context()
            page = await context.new_page()
            await page.goto(target.url, wait_until="domcontentloaded", timeout=30_000)
            # 显式等待（非裸 sleep）
            await page.wait_for_load_state("domcontentloaded")

            items: List[dict] = []
            if target.target_type == TargetType.COMPETITOR:
                items = await self._parse_competitors(page)
            else:
                items = await self._parse_reviews(page)

            screenshot = await self._screenshot(page)
            await page.close()
            return CrawlResult(items=items, errors=[], screenshots=[screenshot])
        except Exception as exc:  # 异常恢复：重建上下文
            await self._reset()
            return CrawlResult(items=[], errors=[str(exc)], screenshots=[])

    async def _parse_reviews(self, page) -> List[dict]:
        root = await self._locate(page, ["div.review-list", "div.review-detail"])
        if root is None:
            return []
        items = []
        for block in await page.locator(".review").all():
            items.append({
                "review_id": (await block.get_attribute("data-review-id") or "").strip(),
                "listing_id": (await block.get_attribute("data-listing-id") or "").strip(),
                "asin": (await block.get_attribute("data-asin") or "").strip(),
                "rating": self._parse_rating(await self._text(block, ".rating")),
                "title": (await self._text(block, ".review-title")).strip(),
                "content": (await self._text(block, ".review-content")).strip(),
                "is_verified": (await block.locator(".verified-purchase").count()) > 0,
            })
        return items

    async def _parse_competitors(self, page) -> List[dict]:
        root = await self._locate(page, ["div.competitor-list"])
        if root is None:
            return []
        items = []
        for block in await page.locator(".competitor").all():
            items.append({
                "material_id": (await block.get_attribute("data-material-id") or "").strip(),
                "competitor_id": (await block.get_attribute("data-competitor-id") or "").strip(),
                "category": (await self._text(block, ".category")).strip(),
                "price_band": (await self._text(block, ".price-band")).strip(),
                "rating": self._parse_rating(await self._text(block, ".rating")),
                "sales_rank": self._parse_int(await self._text(block, ".sales-rank")),
                "selling_points": await block.locator(".selling-points li").all_inner_texts(),
            })
        return items

    @staticmethod
    async def _text(block, selector: str) -> str:
        loc = block.locator(selector).first
        if await loc.count() == 0:
            return ""
        return await loc.inner_text()

    @staticmethod
    def _parse_rating(text: str) -> float:
        import re
        m = re.search(r"(\d+(?:\.\d+)?)", text or "")
        return float(m.group(1)) if m else 0.0

    @staticmethod
    def _parse_int(text: str) -> int:
        import re
        return int(re.sub(r"[^0-9]", "", text or "") or 0)
