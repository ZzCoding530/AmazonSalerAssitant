"""Item Pipeline：清洗、过滤、去重、入库。

- CleanPipeline：字段清洗 + 必填校验，缺失/异常结构容错（丢弃而非崩溃）。
- VerifiedFilterPipeline：verified 过滤在 Pipeline 阶段完成；被过滤记录仍落库并标记原因。
- DedupPipeline：增量去重（布隆 + 仓储），重复评论跳过。
- StoragePipeline：写入数据访问层（生产同构）。

所有外部依赖（仓储/缓存）通过构造注入，测试可替换为内存实现。
"""

from __future__ import annotations

from datetime import datetime, timezone

from scrapy.exceptions import DropItem

from adgenie.data.domain import Material, RawReview
from adgenie.data.ports import CacheStore, MaterialStore, ReviewStore
from adgenie.crawler.items import CompetitorItem, ReviewItem

_REVIEW_REQUIRED = ("review_id", "listing_id")
_COMPETITOR_REQUIRED = ("material_id", "competitor_id")


def _is_shill(item: ReviewItem) -> bool:
    """水军启发式：非 verified + 极端评分 + 重复/极短话术。"""
    if item.get("is_verified"):
        return False
    rating = float(item.get("rating") or 0.0)
    content = (item.get("content") or "").strip()
    words = content.split()
    if not words:
        return False
    repetitive = content.count(words[0]) >= 3
    return rating >= 5.0 and (len(words) <= 5 or repetitive)


class CleanPipeline:
    """清洗 + 必填校验。"""

    def process_item(self, item, spider):
        if isinstance(item, ReviewItem):
            required = _REVIEW_REQUIRED
        elif isinstance(item, CompetitorItem):
            required = _COMPETITOR_REQUIRED
        else:
            return item

        for key in required:
            value = item.get(key)
            if value is None or str(value).strip() == "":
                raise DropItem(f"missing required field: {key}")

        # 文本字段去空白
        for key in ("title", "content", "category", "price_band"):
            if key in item.fields and item.get(key) is not None:
                item[key] = str(item[key]).strip()
        return item


class VerifiedFilterPipeline:
    """verified 过滤：非 verified 标记 filtered_reason，仍落库。"""

    def process_item(self, item, spider):
        if not isinstance(item, ReviewItem):
            return item
        if item.get("is_verified"):
            item["filtered_reason"] = ""
        else:
            item["filtered_reason"] = "shill" if _is_shill(item) else "unverified"
        return item


class DedupPipeline:
    """增量去重：以 listing_id + review_id 为唯一键，命中布隆/仓储则跳过。"""

    def __init__(self, review_store: ReviewStore, cache: CacheStore):
        self._review_store = review_store
        self._cache = cache

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            review_store=crawler.settings.get("ADGENIE_REVIEW_STORE"),
            cache=crawler.settings.get("ADGENIE_CACHE_STORE"),
        )

    def process_item(self, item, spider):
        if not isinstance(item, ReviewItem):
            return item
        dedup_key = f"dedup:{item.get('listing_id')}"
        review_id = item.get("review_id")
        if self._cache.bloom_contains(dedup_key, review_id) or \
                self._review_store.exists(item.get("listing_id"), review_id):
            raise DropItem(f"duplicate review: {review_id}")
        self._cache.bloom_add(dedup_key, review_id)
        return item


class StoragePipeline:
    """写入数据访问层。"""

    def __init__(self, review_store: ReviewStore, material_store: MaterialStore):
        self._review_store = review_store
        self._material_store = material_store

    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            review_store=crawler.settings.get("ADGENIE_REVIEW_STORE"),
            material_store=crawler.settings.get("ADGENIE_MATERIAL_STORE"),
        )

    def process_item(self, item, spider):
        if isinstance(item, ReviewItem):
            self._review_store.insert(RawReview(
                review_id=item.get("review_id"),
                listing_id=item.get("listing_id"),
                asin=item.get("asin") or "",
                reviewer_id=item.get("reviewer_id") or "",
                rating=float(item.get("rating") or 0.0),
                title=item.get("title") or "",
                content=item.get("content") or "",
                is_verified=bool(item.get("is_verified")),
                filtered_reason=item.get("filtered_reason") or "",
                crawled_at=datetime.now(timezone.utc),
            ))
        elif isinstance(item, CompetitorItem):
            self._material_store.upsert(Material(
                material_id=item.get("material_id"),
                competitor_id=item.get("competitor_id"),
                category=item.get("category") or "",
                price_band=item.get("price_band") or "",
                rating=float(item.get("rating") or 0.0),
                sales_rank=int(item.get("sales_rank") or 0),
                selling_points=list(item.get("selling_points") or []),
            ))
        return item
