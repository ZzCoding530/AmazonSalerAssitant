"""竞品素材采集 Spider。"""

from __future__ import annotations

import re

import scrapy

from adgenie.crawler.items import CompetitorItem
from adgenie.crawler.spiders.review_spider import parse_rating


class CompetitorSpider(scrapy.Spider):
    name = "competitor"

    def __init__(self, target: str = "", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_urls = [target] if target else []

    def parse(self, response):
        for block in response.css(".competitor"):
            item = CompetitorItem()
            item["material_id"] = (block.css("::attr(data-material-id)").get()
                                   or block.css(".material-id::text").get() or "").strip()
            item["competitor_id"] = (block.css("::attr(data-competitor-id)").get()
                                     or block.css(".competitor-id::text").get() or "").strip()
            item["category"] = (block.css(".category::text").get() or "").strip()
            item["price_band"] = (block.css(".price-band::text").get() or "").strip()
            item["rating"] = parse_rating(block.css(".rating::text").get() or "")
            rank = (block.css(".sales-rank::text").get() or "0").strip()
            item["sales_rank"] = int(re.sub(r"[^0-9]", "", rank) or 0)
            item["selling_points"] = block.css(".selling-points li::text").getall()
            yield item

        next_url = response.css("a.next-page::attr(href)").get()
        if next_url:
            yield response.follow(next_url, callback=self.parse)
