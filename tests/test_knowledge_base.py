"""机制五：知识库自更新闭环 单元测试。"""

from datetime import datetime, timedelta, timezone

from adgenie.config import KnowledgeBaseConfig
from adgenie.data.memory import InMemoryKnowledgeStore
from adgenie.mechanisms.knowledge_base import KnowledgeBase, selling_point_key


def test_selling_point_key_stable_across_text_change():
    assert selling_point_key("long battery life") == selling_point_key("improved battery life")


def test_same_selling_point_does_not_duplicate(settings):
    kb = KnowledgeBase(InMemoryKnowledgeStore(), KnowledgeBaseConfig())
    e1 = kb._store.upsert_selling_point("C1", "battery", "long battery life")
    e2 = kb._store.upsert_selling_point("C1", "battery", "long battery life")
    assert e1.entry_id == e2.entry_id
    assert e1.version == 1


def test_changed_selling_point_bumps_version_and_keeps_history(settings):
    store = InMemoryKnowledgeStore()
    kb = KnowledgeBase(store, KnowledgeBaseConfig())
    e1 = kb._store.upsert_selling_point("C1", "battery", "long battery life")
    e2 = kb._store.upsert_selling_point("C1", "battery", "improved battery life")
    assert e2.version == 2
    assert e2.previous_version_id == e1.entry_id
    history = kb.history("battery")
    assert [h.version for h in history] == [1, 2]


def test_archive_outdated(settings):
    store = InMemoryKnowledgeStore()
    kb = KnowledgeBase(store, KnowledgeBaseConfig())
    old = kb._store.upsert_selling_point("C1", "battery", "old selling point")
    # 手动把创建时间改为很久以前，模拟过期
    old.created_at = datetime.now(timezone.utc) - timedelta(days=400)
    kb._store._entries[old.entry_id] = old
    archived = kb.archive_outdated()
    assert archived == 1
    assert old.archived is True
