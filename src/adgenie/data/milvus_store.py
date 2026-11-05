"""Milvus 向量存储实现（pymilvus）。

真实生产实现：负责竞品素材向量的写入与召回。向量只存 Milvus，禁止进 MySQL。
使用 ``MilvusClient`` 高层 API，集合 schema 含主键 ``material_id``（VARCHAR）
与 ``vector``（FLOAT_VECTOR），召回时通过 ``material_id in [...]`` 过滤候选集合，
从机制上保证「必须先粗筛再向量召回」。

注意：该实现需要可用 Milvus 服务才能运行；测试通过 ``memory.InMemoryVectorStore``
替换同一接口（见 ports.VectorStore）。
"""

from __future__ import annotations

import json
from typing import List, Optional

from adgenie.data.domain import VectorHit
from adgenie.data.ports import VectorStore


class MilvusVectorStore(VectorStore):
    def __init__(self, uri: str, collection: str):
        self._uri = uri
        self._collection = collection
        self._client = None
        self._dim: Optional[int] = None

    def _get_client(self):
        if self._client is None:
            from pymilvus import MilvusClient  # 懒加载，避免无服务时导入即连接
            self._client = MilvusClient(uri=self._uri)
        return self._client

    def _ensure_collection(self, dim: int) -> None:
        if self._dim == dim:
            return
        from pymilvus import DataType
        client = self._get_client()
        if not client.has_collection(self._collection):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(field_name="material_id", datatype=DataType.VARCHAR,
                             max_length=128, is_primary=True)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dim)
            index_params = client.prepare_index_params()
            index_params.add_index(field_name="vector", index_type="IVF_FLAT",
                                   metric_type="COSINE", params={"nlist": 128})
            client.create_collection(self._collection, schema=schema, index_params=index_params)
        client.load_collection(self._collection)
        self._dim = dim

    def upsert(self, material_id: str, vector: List[float]) -> None:
        self._ensure_collection(len(vector))
        self._get_client().upsert(
            collection_name=self._collection,
            data=[{"material_id": material_id, "vector": vector}],
        )

    def search(self, query_vector: List[float], candidate_ids: List[str],
               top_k: int) -> List[VectorHit]:
        if not candidate_ids:
            return []
        self._ensure_collection(len(query_vector))
        expr = "material_id in " + json.dumps(candidate_ids)
        result = self._get_client().search(
            collection_name=self._collection,
            data=[query_vector],
            filter=expr,
            limit=min(top_k, len(candidate_ids)),
            output_fields=["material_id"],
        )
        hits: List[VectorHit] = []
        for hit_list in result:
            for hit in hit_list:
                entity = hit.get("entity", {})
                hits.append(VectorHit(
                    material_id=entity.get("material_id", ""),
                    score=float(hit.get("distance", 0.0)),
                ))
        return hits
