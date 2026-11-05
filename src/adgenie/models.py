"""模型层抽象与实现（LLM / Embedding / Rerank）。

依据《开发规范》：
- 写判分离：writer 与 judge 必须是不同厂商模型（写 Qwen/DeepSeek，判 GLM），
  Judge 侧 temperature 固定为 0，禁止同一 client 同时承担写与判。
- 所有外部模型能力通过接口注入，生产实现真实存在；测试用确定性实现替换。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from abc import ABC, abstractmethod
from typing import List, Optional

import requests


class LLMClient(ABC):
    model: str
    temperature: float

    @abstractmethod
    def complete(self, prompt: str, system: str | None = None) -> str: ...

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        raw = self.complete(prompt, system)
        return _extract_json(raw)


def _extract_json(text: str) -> dict:
    """从 LLM 输出中稳健提取 JSON（支持代码块包裹）。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


class OpenAICompatibleLLM(LLMClient):
    """OpenAI 兼容 /chat/completions 客户端（Qwen / DeepSeek / GLM 通用）。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float, timeout: int = 60):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self.temperature = temperature
        self._timeout = timeout

    def complete(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = requests.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": self.temperature,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


class FakeLLM(LLMClient):
    """确定性测试替身：按注册的脚本返回，未命中时返回空 JSON。"""

    def __init__(self, model: str = "fake", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature
        self._script: dict[str, str] = {}

    def register(self, prompt_substring: str, response: str) -> None:
        self._script[prompt_substring] = response

    def complete(self, prompt: str, system: str | None = None) -> str:
        for key, value in self._script.items():
            if key in prompt:
                return value
        return "{}"


class Embedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> List[float]: ...


class BGEM3Embedder(Embedder):
    """BGE-M3 向量化实现（懒加载 sentence-transformers，需在部署环境安装）。"""

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, text: str) -> List[float]:
        return [float(x) for x in self._load().encode(text, normalize_embeddings=True)]


class DeterministicEmbedder(Embedder):
    """确定性向量化（特征哈希），仅用于测试。"""

    def __init__(self, dim: int = 128):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for token in text.lower().split():
            h = int.from_bytes(hashlib.md5(token.encode("utf-8")).digest(), "big")
            idx = h % self.dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class Reranker(ABC):
    @abstractmethod
    def rerank(self, query: str, documents: List[str]) -> List[float]: ...


class CrossEncoderReranker(Reranker):
    """Cross-Encoder 精排实现（懒加载，需在部署环境安装）。"""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self._model_name)
        return self._model

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        if not documents:
            return []
        pairs = [(query, d) for d in documents]
        scores = self._load().predict(pairs)
        return [float(s) for s in scores]


class DeterministicReranker(Reranker):
    """确定性精排（基于词重叠），仅用于测试。"""

    def __init__(self, embedder: Optional[Embedder] = None):
        self._embedder = embedder or DeterministicEmbedder()

    def rerank(self, query: str, documents: List[str]) -> List[float]:
        q = self._embedder.embed(query)
        scores = []
        for d in documents:
            dv = self._embedder.embed(d)
            dot = sum(a * b for a, b in zip(q, dv))
            scores.append(max(0.0, dot))
        return scores
