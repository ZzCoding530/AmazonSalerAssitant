"""配置红线校验 单元测试。"""

import pytest

from adgenie.config import (
    LLMConfig,
    LLMEndpointConfig,
    RetrievalConfig,
    Settings,
)


def test_data_source_only_seed_or_live():
    with pytest.raises(ValueError):
        Settings(data_source="mocked")


def test_judge_temperature_must_be_zero():
    with pytest.raises(ValueError):
        Settings(llm=LLMConfig(
            writer=LLMEndpointConfig(model="qwen-max", temperature=0.7),
            judge=LLMEndpointConfig(model="glm-4-plus", temperature=0.7),
        ))


def test_writer_judge_cannot_share_model():
    with pytest.raises(ValueError):
        Settings(llm=LLMConfig(
            writer=LLMEndpointConfig(model="same-model", temperature=0.7),
            judge=LLMEndpointConfig(model="same-model", temperature=0.0),
        ))


def test_coarse_filter_cannot_be_disabled():
    with pytest.raises(ValueError):
        RetrievalConfig(coarse_filter=False)


def test_valid_settings_accept():
    s = Settings(
        data_source="seed",
        llm=LLMConfig(
            writer=LLMEndpointConfig(model="qwen-max", temperature=0.7),
            judge=LLMEndpointConfig(model="glm-4-plus", temperature=0.0),
        ),
    )
    assert s.llm.judge.temperature == 0.0
