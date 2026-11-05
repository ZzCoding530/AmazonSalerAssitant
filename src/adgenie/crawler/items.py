"""Scrapy Item 定义。"""

from __future__ import annotations

import scrapy


class ReviewItem(scrapy.Item):
    review_id = scrapy.Field()
    listing_id = scrapy.Field()
    asin = scrapy.Field()
    reviewer_id = scrapy.Field()
    rating = scrapy.Field()
    title = scrapy.Field()
    content = scrapy.Field()
    is_verified = scrapy.Field()   # 由 Pipeline 依据 Verified Purchase 标识判定
    filtered_reason = scrapy.Field()  # 未购/水军/重复，被过滤记录仍需落库便于审计


class CompetitorItem(scrapy.Item):
    material_id = scrapy.Field()
    competitor_id = scrapy.Field()
    category = scrapy.Field()
    price_band = scrapy.Field()
    rating = scrapy.Field()
    sales_rank = scrapy.Field()
    selling_points = scrapy.Field()
