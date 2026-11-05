"""内存实现（仅用于测试）。

依据《开发规范》第 4 节：外部存储通过接口抽象注入，便于测试时替换。
这里的实现**只允许出现在测试代码路径**；生产实现见 mysql_store / redis_store /
milvus_store。布隆过滤器使用真实位数组（bytearray），保留误报语义而非用 dict 集合。
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from adgenie.data.domain import (
    KnowledgeEntry,
    Material,
    RawReview,
    ScoreReport,
    UserProfile,
    VectorHit,
)
from adgenie.data.ports import (
    CacheStore,
    KnowledgeStore,
    MaterialStore,
    ProfileStore,
    ReviewStore,
    ScoreReportStore,
    VectorStore,
)


class InMemoryReviewStore(ReviewStore):
    def __init__(self):
        self._rows: dict[tuple[str, str], RawReview] = {}

    def insert(self, review: RawReview) -> bool:
        key = (review.listing_id, review.review_id)
        if key in self._rows:
            return False
        self._rows[key] = review
        return True

    def exists(self, listing_id: str, review_id: str) -> bool:
        return (listing_id, review_id) in self._rows

    def get_by_listing(self, listing_id: str) -> List[RawReview]:
        return [r for (lid, _), r in self._rows.items() if lid == listing_id]

    def get_verified(self, listing_id: str) -> List[RawReview]:
        return [r for (lid, _), r in self._rows.items()
                if lid == listing_id and r.is_verified and not r.filtered_reason]

    def mark_filtered(self, review_id: str, reason: str) -> None:
        for (_, rid), r in self._rows.items():
            if rid == review_id:
                r.filtered_reason = reason


class InMemoryProfileStore(ProfileStore):
    def __init__(self):
        self._profiles: dict[str, UserProfile] = {}

    def save_version(self, profile: UserProfile) -> str:
        self._profiles[profile.version_id] = profile
        return profile.version_id

    def get_latest(self, listing_id: str) -> Optional[UserProfile]:
        candidates = [p for p in self._profiles.values() if p.listing_id == listing_id]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.created_at)

    def get(self, version_id: str) -> Optional[UserProfile]:
        return self._profiles.get(version_id)


class InMemoryScoreReportStore(ScoreReportStore):
    def __init__(self):
        self._reports: dict[str, ScoreReport] = {}

    def save(self, report: ScoreReport) -> str:
        self._reports[report.report_id] = report
        return report.report_id

    def get(self, report_id: str) -> Optional[ScoreReport]:
        return self._reports.get(report_id)

    def list_for_listing(self, listing_id: str) -> List[ScoreReport]:
        return sorted(
            (r for r in self._reports.values() if r.listing_id == listing_id),
            key=lambda r: r.created_at, reverse=True,
        )


class InMemoryMaterialStore(MaterialStore):
    def __init__(self):
        self._materials: dict[str, Material] = {}

    def upsert(self, material: Material) -> None:
        self._materials[material.material_id] = material

    def get(self, material_id: str) -> Optional[Material]:
        return self._materials.get(material_id)

    def list_all(self) -> List[Material]:
        return list(self._materials.values())

    def coarse_filter(self, category, price_band, rating_min, rating_max,
                      sales_rank_max) -> List[Material]:
        out = []
        for m in self._materials.values():
            if m.archived:
                continue
            if category and m.category != category:
                continue
            if price_band and m.price_band != price_band:
                continue
            if rating_min is not None and m.rating < rating_min:
                continue
            if rating_max is not None and m.rating > rating_max:
                continue
            if sales_rank_max is not None and m.sales_rank > sales_rank_max:
                continue
            out.append(m)
        return out


class InMemoryKnowledgeStore(KnowledgeStore):
    def __init__(self):
        self._entries: dict[str, KnowledgeEntry] = {}
        self._by_key: dict[tuple[str, str], list[str]] = {}

    def upsert_selling_point(self, competitor_id, selling_point_key, selling_point) -> KnowledgeEntry:
        key = (competitor_id, selling_point_key)
        versions = self._by_key.get(key, [])
        latest = self._entries[versions[-1]] if versions else None
        if latest is not None and latest.selling_point == selling_point:
            return latest
        version = (latest.version + 1) if latest else 1
        entry = KnowledgeEntry(
            entry_id=f"{competitor_id}:{selling_point_key}:v{version}",
            competitor_id=competitor_id,
            selling_point_key=selling_point_key,
            selling_point=selling_point,
            version=version,
            previous_version_id=latest.entry_id if latest else "",
            created_at=datetime.now(timezone.utc),
        )
        self._entries[entry.entry_id] = entry
        self._by_key.setdefault(key, []).append(entry.entry_id)
        return entry

    def list_active(self) -> List[KnowledgeEntry]:
        return [e for e in self._entries.values() if not e.archived]

    def history(self, selling_point_key: str) -> List[KnowledgeEntry]:
        ids = [eid for (cid, key), eids in self._by_key.items()
               for eid in eids if key == selling_point_key]
        return sorted((self._entries[i] for i in ids), key=lambda e: e.version)

    def archive_outdated(self, older_than_days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        count = 0
        for e in self._entries.values():
            if not e.archived and e.created_at < cutoff:
                e.archived = True
                count += 1
        return count


class InMemoryCacheStore(CacheStore):
    """布隆过滤器使用真实位数组，保留「可能误报、绝不漏报」语义。"""

    def __init__(self, bloom_size: int = 100_000, bloom_hashes: int = 5):
        self._bloom_size = bloom_size
        self._bloom_hashes = bloom_hashes
        self._bits: dict[str, bytearray] = {}
        self._kv: dict[str, str] = {}
        self._rate: dict[str, tuple[int, float]] = {}

    def _positions(self, item: str) -> list[int]:
        digest = hashlib.sha256(item.encode("utf-8")).digest()
        out = []
        for i in range(self._bloom_hashes):
            seed = digest + i.to_bytes(4, "big")
            h = int.from_bytes(hashlib.md5(seed).digest(), "big")
            out.append(h % self._bloom_size)
        return out

    def _bits_for(self, key: str) -> bytearray:
        if key not in self._bits:
            self._bits[key] = bytearray(self._bloom_size // 8 + 1)
        return self._bits[key]

    def bloom_add(self, key: str, item: str) -> bool:
        bits = self._bits_for(key)
        for p in self._positions(item):
            bits[p // 8] |= (1 << (p % 8))
        return True

    def bloom_contains(self, key: str, item: str) -> bool:
        if key not in self._bits:
            return False
        bits = self._bits[key]
        return all((bits[p // 8] >> (p % 8)) & 1 for p in self._positions(item))

    def rate_increment(self, key: str, window_seconds: int) -> int:
        import time
        now = time.monotonic()
        count, window_start = self._rate.get(key, (0, now))
        if now - window_start >= window_seconds:
            count, window_start = 0, now
        count += 1
        self._rate[key] = (count, window_start)
        return count

    def get(self, key: str) -> Optional[str]:
        return self._kv.get(key)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._kv[key] = value


class InMemoryVectorStore(VectorStore):
    def __init__(self):
        self._vectors: dict[str, list[float]] = {}

    def upsert(self, material_id: str, vector: list[float]) -> None:
        self._vectors[material_id] = list(vector)

    def _cosine(self, a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def search(self, query_vector, candidate_ids, top_k) -> List[VectorHit]:
        scored = []
        for mid in candidate_ids:
            if mid in self._vectors:
                scored.append(VectorHit(material_id=mid,
                                        score=self._cosine(query_vector, self._vectors[mid])))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]
