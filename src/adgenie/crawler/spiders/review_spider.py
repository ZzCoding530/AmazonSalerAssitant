"""评论采集 Spider（含多页面类型解析：列表页 + 详情页）。

字段提取、分页、异常结构容错均由本 Spider 负责；
verified 过滤与去重由 Pipeline 负责（Spider 阶段不做过滤）。
"""

from __future__ import annotations

import re

import scrapy

from adgenie.crawler.items import ReviewItem

_RATING_RE = re.compile(r"(\d+(?:\.\d+)?)")


def parse_rating(text: str) -> float:
    """从评分文本稳健提取浮点数；无法解析返回 0.0（容错）。"""
    if not text:
        return 0.0
    m = _RATING_RE.search(text)
    return float(m.group(1)) if m else 0.0


class ReviewSpider(scrapy.Spider):
    name = "review"

    def __init__(self, target: str = "", listing_id: str = "", asin: str = "",
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.listing_id = listing_id
        self.asin = asin
        self.start_urls = [target] if target else []

    def parse(self, response):
        """列表页：解析多条评论并处理分页。"""
        for block in response.css(".review"):
            yield self._extract(block)

        next_url = response.css("a.next-page::attr(href)").get()
        if next_url:
            yield response.follow(next_url, callback=self.parse)

    def parse_detail(self, response):
        """详情页：单条评论。"""
        block = response.css("div.review-detail")
        if block:
            yield self._extract(block)

    def _extract(self, block) -> ReviewItem:
        item = ReviewItem()
        item["review_id"] = (block.css("::attr(data-review-id)").get()
                             or block.css(".review-id::text").get() or "")
        item["listing_id"] = (block.css("::attr(data-listing-id)").get()
                              or self.listing_id)
        item["asin"] = block.css("::attr(data-asin)").get() or self.asin
        item["reviewer_id"] = (block.css(".reviewer::text").get()
                               or block.css("::attr(data-reviewer-id)").get() or "").strip()
        item["rating"] = parse_rating(block.css(".rating::text").get() or "")
        item["title"] = (block.css(".review-title::text").get() or "").strip()
        item["content"] = (block.css(".review-content::text").get() or "").strip()
        # Verified Purchase 标识仅作为原始信号，最终判定在 Pipeline。
        item["is_verified"] = bool(block.css(".verified-purchase"))
        return item
