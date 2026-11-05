"""配置加载模块。

设计目标（对应《开发规范》第 4 节）：
- 所有模型名、密钥、限流参数、阈值均来自配置文件 / 环境变量，禁止硬编码。
- 切换 ``data_source`` 从 ``seed`` 到 ``live``，代码无需任何修改。
- 对红线配置项（Judge 温度=0、coarse_filter=true）做启动期校验，违反即抛错。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, List

import yaml
from pydantic import BaseModel, Field, model_validator

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def _resolve_env(value: Any) -> Any:
    """递归解析字符串中的 ``${VAR}`` 占位符；未设置的环境变量解析为空串。"""
    if isinstance(value, str):
        def repl(match: "re.Match[str]") -> str:
            return os.environ.get(match.group(1), "")
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


class ServiceConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5000


class MySQLConfig(BaseModel):
    dsn: str = ""


class RedisConfig(BaseModel):
    url: str = ""


class MilvusConfig(BaseModel):
    uri: str = ""
    collection: str = "adgenie_materials"


class StorageConfig(BaseModel):
    mysql: MySQLConfig = Field(default_factory=MySQLConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    milvus: MilvusConfig = Field(default_factory=MilvusConfig)


class CrawlerConfig(BaseModel):
    engine: str = "auto"
    rate_limit: float = 2.0
    download_delay: float = 0.5
    autothrottle_enabled: bool = True
    autothrottle_target_concurrency: float = 1.0
    retry_max: int = 3
    retry_http_codes: List[int] = Field(default_factory=lambda: [500, 502, 503, 504, 429])
    backoff_factor: float = 2.0
    proxy_pool: str = ""
    user_agents: List[str] = Field(default_factory=list)
    circuit_breaker_failures: int = 5
    circuit_breaker_timeout: int = 300


class LLMEndpointConfig(BaseModel):
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.0
    timeout: int = 60


class LLMConfig(BaseModel):
    writer: LLMEndpointConfig = Field(default_factory=LLMEndpointConfig)
    judge: LLMEndpointConfig = Field(default_factory=LLMEndpointConfig)


class EvidenceConfig(BaseModel):
    max_reprompt: int = 2
    batch_freeze: bool = True


class ScoringConfig(BaseModel):
    rubric_version: str = "v1"
    dual_scale: bool = True

    @model_validator(mode="after")
    def _check_dual_scale(self) -> "ScoringConfig":
        if not self.dual_scale:
            raise ValueError("dual_scale 禁止为 false：双标尺不可合并成单一总分")
        return self


class CalibrationConfig(BaseModel):
    n_perturbed: int = 10
    n_placebo: int = 10
    permutation_iterations: int = 2000
    random_seed: int = 42
    min_detection_rate: float = 0.8
    max_false_alarm_rate: float = 0.2


class RetrievalWeights(BaseModel):
    semantic: float = 0.6
    recency_decay: float = 0.25
    sales_confidence: float = 0.15


class RetrievalConfig(BaseModel):
    coarse_filter: bool = True
    top_k_recall: int = 50
    top_k_final: int = 10
    weights: RetrievalWeights = Field(default_factory=RetrievalWeights)
    recency_half_life_days: int = 90

    @model_validator(mode="after")
    def _check_coarse(self) -> "RetrievalConfig":
        if not self.coarse_filter:
            raise ValueError("coarse_filter 禁止为 false：不可跳过元数据粗筛")
        return self


class KnowledgeBaseConfig(BaseModel):
    recency_threshold_days: int = 365


class ManifestConfig(BaseModel):
    freeze_on_score: bool = True


class Settings(BaseModel):
    data_source: str = "seed"
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    knowledge_base: KnowledgeBaseConfig = Field(default_factory=KnowledgeBaseConfig)
    manifest: ManifestConfig = Field(default_factory=ManifestConfig)

    @model_validator(mode="after")
    def _check_red_lines(self) -> "Settings":
        if self.data_source not in ("seed", "live"):
            raise ValueError("data_source 仅允许 seed 或 live")
        if self.llm.judge.temperature != 0.0:
            raise ValueError("Judge 侧 temperature 必须固定为 0，禁止修改")
        if self.llm.writer.model == self.llm.judge.model and self.llm.writer.model:
            raise ValueError("写判分离不可妥协：writer 与 judge 禁止使用同一模型")
        return self


def load_settings(path: str | Path | None = None) -> Settings:
    """从 YAML 加载配置并解析环境变量占位符。

    环境变量 ``ADGENIE_CONFIG`` 可覆盖默认配置路径。
    """
    config_path = Path(path) if path else Path(
        os.environ.get("ADGENIE_CONFIG", str(_DEFAULT_CONFIG_PATH))
    )
    raw: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    resolved = _resolve_env(raw)
    # 允许通过环境变量直接覆盖 data_source
    if os.environ.get("ADGENIE_DATA_SOURCE"):
        resolved["data_source"] = os.environ["ADGENIE_DATA_SOURCE"]
    return Settings.model_validate(resolved)


_settings: Settings | None = None


def get_settings() -> Settings:
    """全局单例配置（惰性加载）。"""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """测试用：清空缓存，强制下次重新加载。"""
    global _settings
    _settings = None
