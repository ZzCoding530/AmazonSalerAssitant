"""pytest 共享夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 使 src 下包可被导入（配合 pyproject 的 pythonpath 亦可）
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def settings():
    from adgenie.config import load_settings
    return load_settings()


@pytest.fixture
def factory():
    from adgenie.data.factory import DataFactory
    return DataFactory(seed=42)
