"""合成数据工厂（DataFactory）。

依据《开发规范》第 6.3 节：合成数据必须通过 DataFactory / fixture 统一生成，
固定随机种子、可复现，并覆盖边界场景（水军/未购、重复、矛盾卖点、过期素材等）。
数据生成脚本本身属于交付物。
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from adgenie.data.domain import Material, RawReview

# 示例广告卖点（用于对齐度与矛盾评论构造）
AD_SELLING_POINTS: List[str] = [
    "battery life",
    "waterproof",
    "fast charging",
    "lightweight",
    "noise cancellation",
]


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class DataFactory:
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    # ---- 评论 ----
    def _review(self, listing_id: str, review_id: str, asin: str, *, verified: bool,
                rating: float, content: str, title: str = "") -> RawReview:
        return RawReview(
            review_id=review_id,
            listing_id=listing_id,
            asin=asin,
            reviewer_id=_uid(),
            rating=rating,
            title=title or content[:40],
            content=content,
            is_verified=verified,
            crawled_at=datetime.now(timezone.utc),
        )

    def verified_reviews(self, listing_id: str, asin: str, n: int = 5) -> List[RawReview]:
        base = [
            "Battery lasts a full day of heavy use, very happy.",
            "The waterproofing held up in the rain, exactly as advertised.",
            "Charges from 0 to 80 percent in under an hour, impressive.",
            "Super lightweight, easy to carry around all day.",
            "Noise cancellation is solid on flights, blocks engine hum.",
        ]
        return [self._review(listing_id, f"R-{i:03d}", asin, verified=True,
                             rating=4.0 + (i % 2), content=base[i % len(base)])
                for i in range(n)]

    def non_verified_reviews(self, listing_id: str, asin: str, n: int = 3) -> List[RawReview]:
        return [self._review(listing_id, f"NV-{i:03d}", asin, verified=False,
                             rating=3.0, content="Unverified review that must be filtered out.")
                for i in range(n)]

    def shill_reviews(self, listing_id: str, asin: str, n: int = 3) -> List[RawReview]:
        """水军：极端好评 + 重复话术，且非 verified。"""
        texts = ["BEST PRODUCT EVER!!!", "Amazing amazing amazing, buy it now!",
                 "Five stars five stars five stars"]
        return [self._review(listing_id, f"SHILL-{i:03d}", asin, verified=False,
                             rating=5.0, content=texts[i % len(texts)])
                for i in range(n)]

    def duplicate_reviews(self, listing_id: str, asin: str, n: int = 2) -> List[RawReview]:
        """与 verified_reviews 前几条 review_id 完全一致 → 触发增量去重。"""
        return [self._review(listing_id, f"R-{i:03d}", asin, verified=True,
                             rating=4.0, content="duplicate payload") for i in range(n)]

    def contradictory_reviews(self, listing_id: str, asin: str, n: int = 5) -> List[RawReview]:
        """与广告卖点矛盾的评论 → 触发需求对齐度扣分。"""
        contradictions = {
            "battery life": "Battery barely lasted two hours, totally disappointed.",
            "waterproof": "It died after a light splash, waterproof claim is false.",
            "fast charging": "Took all night to charge, no fast charging at all.",
            "lightweight": "Much heavier than expected, not lightweight.",
            "noise cancellation": "Noise cancellation does almost nothing.",
        }
        keys = list(contradictions.keys())
        return [self._review(listing_id, f"C-{i:03d}", asin, verified=True,
                             rating=1.0 + (i % 2), content=contradictions[keys[i % len(keys)]])
                for i in range(n)]

    # ---- 竞品素材 ----
    def materials(self, n: int = 12, *, expired_ratio: float = 0.25) -> List[Material]:
        categories = ["electronics", "electronics", "home", "home"]
        price_bands = ["low", "mid", "high"]
        out: List[Material] = []
        now = datetime.now(timezone.utc)
        n_expired = max(1, int(n * expired_ratio))
        for i in range(n):
            expired = i < n_expired
            updated = now - timedelta(days=400) if expired else now - timedelta(days=self.rng.randint(1, 60))
            out.append(Material(
                material_id=f"MAT-{i:03d}",
                competitor_id=f"COMP-{i % 4:02d}",
                category=categories[i % len(categories)],
                price_band=price_bands[i % len(price_bands)],
                rating=round(3.5 + self.rng.random(), 2),
                sales_rank=self.rng.randint(1, 500),
                selling_points=[AD_SELLING_POINTS[i % len(AD_SELLING_POINTS)]],
                embedding=[round(self.rng.random(), 4) for _ in range(8)],
                created_at=updated,
                updated_at=updated,
                archived=False,
            ))
        return out

    # ---- 模型输出（含编造编号，用于白名单拒收测试）----
    def fake_claims(self, whitelist: List[str], n_fake: int = 2) -> List[dict]:
        """生成 claims：前几条引用白名单编号，后几条引用编造编号。"""
        claims = []
        for i, rid in enumerate(whitelist):
            claims.append({"concern": f"concern {i}", "review_id": rid, "quote": "ok"})
        for j in range(n_fake):
            claims.append({"concern": f"fake {j}", "review_id": f"FAKE-{j:03d}", "quote": "hallucinated"})
        return claims


def write_seed_files(target_dir: str | Path, seed: int = 42) -> dict[str, Path]:
    """把合成数据落盘到 ``data/seed/``，供下游以生产同构方式加载。"""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    factory = DataFactory(seed=seed)
    payload = {
        "verified_reviews": [r.model_dump(mode="json") for r in factory.verified_reviews("L-1001", "B000000001")],
        "non_verified_reviews": [r.model_dump(mode="json") for r in factory.non_verified_reviews("L-1001", "B000000001")],
        "shill_reviews": [r.model_dump(mode="json") for r in factory.shill_reviews("L-1001", "B000000001")],
        "contradictory_reviews": [r.model_dump(mode="json") for r in factory.contradictory_reviews("L-1001", "B000000001")],
        "materials": [m.model_dump(mode="json") for m in factory.materials()],
    }
    out_path = target / "seed_data.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return {"seed_data": out_path}


if __name__ == "__main__":
    import sys
    dest = sys.argv[1] if len(sys.argv) > 1 else "data/seed"
    for name, path in write_seed_files(dest).items():
        print(f"{name} -> {path}")
