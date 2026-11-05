"""数据层 单元测试：合成数据可复现、MySQL(SQLite 引擎) 真实 SQL 逻辑。"""

from sqlalchemy import create_engine

from adgenie.data.factory import DataFactory
from adgenie.data.mysql_store import MySQLDataStore


def test_data_factory_reproducible():
    a = DataFactory(seed=42)
    b = DataFactory(seed=42)
    ra = a.verified_reviews("L", "A")
    rb = b.verified_reviews("L", "A")
    assert [r.review_id for r in ra] == [r.review_id for r in rb]
    assert [r.content for r in ra] == [r.content for r in rb]


def test_data_factory_boundary_scenarios(factory):
    assert len(factory.non_verified_reviews("L", "A")) == 3
    assert len(factory.shill_reviews("L", "A")) == 3
    # 矛盾评论覆盖全部广告卖点
    contradictions = factory.contradictory_reviews("L", "A", 5)
    assert len(contradictions) == 5
    # 素材含过期比例
    mats = factory.materials(12, expired_ratio=0.25)
    assert len(mats) == 12


def _store():
    return MySQLDataStore(create_engine("sqlite://"))


def test_mysql_store_dedup(factory):
    store = _store()
    store.create_all()
    r = factory.verified_reviews("L", "A", 1)[0]
    assert store.insert(r) is True
    assert store.insert(r) is False  # 重复评论 → 增量去重


def test_mysql_store_verified_filter(factory):
    store = _store()
    store.create_all()
    for r in factory.verified_reviews("L", "A", 2):
        store.insert(r)
    nv = factory.non_verified_reviews("L", "A", 2)[0]
    store.insert(nv)
    store.mark_filtered(nv.review_id, "unverified")
    assert len(store.get_verified("L")) == 2
    assert len(store.get_by_listing("L")) == 3


def test_mysql_store_knowledge_versioning():
    store = _store()
    store.create_all()
    e1 = store.upsert_selling_point("C1", "battery", "long life")
    e2 = store.upsert_selling_point("C1", "battery", "long life")
    e3 = store.upsert_selling_point("C1", "battery", "changed life")
    assert e1.version == 1 and e2.version == 1 and e3.version == 2
    assert len(store.history("battery")) == 2
