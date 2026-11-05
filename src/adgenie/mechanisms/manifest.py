"""机制六：冻结 manifest 可审计协议。

每次评分必须固化 rubric 版本、模型、温度、证据快照指纹，
保证可回放、改版前后历史严格可比；禁止只存最终分数。
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import List

from adgenie.data.ports import ScoreReportStore


@dataclass(frozen=True)
class FrozenManifest:
    rubric_version: str
    model_name: str
    temperature: float
    evidence_snapshot: str
    created_at: datetime

    def to_dict(self) -> dict:
        return asdict(self)


def compute_evidence_fingerprint(evidence_refs: List[str]) -> str:
    """对证据引用列表生成快照指纹（SHA256）。"""
    payload = "|".join(sorted(evidence_refs))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def freeze_manifest(rubric_version: str, model_name: str, temperature: float,
                    evidence_snapshot: str) -> FrozenManifest:
    return FrozenManifest(
        rubric_version=rubric_version,
        model_name=model_name,
        temperature=temperature,
        evidence_snapshot=evidence_snapshot,
        created_at=datetime.now(timezone.utc),
    )


class ManifestService:
    """回放接口：给定 report_id，还原当时完整输入与输出。"""

    def __init__(self, report_store: ScoreReportStore):
        self._report_store = report_store

    def replay(self, report_id: str) -> dict | None:
        report = self._report_store.get(report_id)
        if report is None:
            return None
        return {
            "report_id": report.report_id,
            "listing_id": report.listing_id,
            "copy_version": report.copy_version,
            "rubric_version": report.rubric_version,
            "model_name": report.model_name,
            "temperature": report.temperature,
            "alignment_score": report.alignment_score,
            "persuasion_score": report.persuasion_score,
            "detail": report.detail,
            "evidence_snapshot": report.evidence_snapshot,
            "created_at": report.created_at,
        }

    def verify(self, report_id: str, expected_snapshot: str) -> bool:
        """校验回放报告的 evidence_snapshot 与当前指纹一致（历史严格可比）。"""
        report = self._report_store.get(report_id)
        if report is None:
            return False
        return report.evidence_snapshot == expected_snapshot
