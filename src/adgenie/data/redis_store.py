"""Redis 缓存实现（redis-py）。

真实生产实现：
- 去重布隆过滤器基于 Redis SETBIT/GETBIT（不依赖内存 dict）。
- 限流计数基于 INCR + EXPIRE。
- 会话缓存基于 GET/SET。

通过注入 redis 客户端实现，测试可替换为 FakeRedis 风格实现（见 memory.py）。
"""

from __future__ import annotations

import hashlib
from typing import Optional

import redis

from adgenie.data.ports import CacheStore


def build_redis_client(url: str, decode_responses: bool = False) -> "redis.Redis":
    return redis.Redis.from_url(url, decode_responses=decode_responses)


class RedisCacheStore(CacheStore):
    def __init__(self, client: "redis.Redis", bloom_size: int = 100_000, bloom_hashes: int = 5):
        self._client = client
        self._bloom_size = bloom_size
        self._bloom_hashes = bloom_hashes

    def _positions(self, item: str) -> list[int]:
        digest = hashlib.sha256(item.encode("utf-8")).digest()
        positions: list[int] = []
        for i in range(self._bloom_hashes):
            seed = digest + i.to_bytes(4, "big")
            h = int.from_bytes(hashlib.md5(seed).digest(), "big")
            positions.append(h % self._bloom_size)
        return positions

    def bloom_add(self, key: str, item: str) -> bool:
        pipe = self._client.pipeline()
        for p in self._positions(item):
            pipe.setbit(key, p, 1)
        pipe.execute()
        return True

    def bloom_contains(self, key: str, item: str) -> bool:
        return all(self._client.getbit(key, p) for p in self._positions(item))

    def rate_increment(self, key: str, window_seconds: int) -> int:
        count = self._client.incr(key)
        if count == 1:
            self._client.expire(key, window_seconds)
        return int(count)

    def get(self, key: str) -> Optional[str]:
        value = self._client.get(key)
        return value.decode("utf-8") if isinstance(value, bytes) else value

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._client.set(key, value, ex=ttl_seconds)
