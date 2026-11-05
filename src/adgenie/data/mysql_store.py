"""MySQL 数据访问实现（SQLAlchemy + PyMySQL）。

生产实现，真实存在。通过 SQLAlchemy ``Engine`` 注入，因此测试可用
SQLite 内存引擎驱动同一套 SQL 逻辑，生产走 MySQL DSN（见 ``build_engine``）。

红线遵守：Material 的向量不落 MySQL（仅存元数据），向量由 Milvus 承担。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from adgenie.data.domain import (
    KnowledgeEntry,
    Material,
    RawReview,
    ScoreReport,
    UserProfile,
)
from adgenie.data.ports import (
    KnowledgeStore,
    MaterialStore,
    ProfileStore,
    ReviewStore,
    ScoreReportStore,
)


class Base(DeclarativeBase):
    pass


class ReviewRow(Base):
    __tablename__ = "reviews_raw"
    __table_args__ = (UniqueConstraint("listing_id", "review_id", name="uq_listing_review"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(String(128), nullable=False)
    listing_id = Column(String(128), nullable=False, index=True)
    asin = Column(String(32))
    reviewer_id = Column(String(128))
    rating = Column(Float)
    title = Column(Text)
    content = Column(Text)
    is_verified = Column(Boolean, default=False)
    filtered_reason = Column(String(64), default="")
    raw_html_ref = Column(Text)
    crawled_at = Column(DateTime)


class ProfileRow(Base):
    __tablename__ = "user_profile_versions"

    version_id = Column(String(128), primary_key=True)
    listing_id = Column(String(128), index=True)
    concerns = Column(JSON)            # list[Concern.model_dump()]
    evidence_manifest = Column(Text)
    prev_version_id = Column(String(128), default="")
    created_at = Column(DateTime)


class ScoreReportRow(Base):
    __tablename__ = "score_reports"

    report_id = Column(String(128), primary_key=True)
    listing_id = Column(String(128), index=True)
    copy_version = Column(String(64))
    rubric_version = Column(String(64))
    model_name = Column(String(128))
    temperature = Column(Float)
    alignment_score = Column(Float)
    persuasion_score = Column(Float)
    detail = Column(JSON)
    evidence_snapshot = Column(Text)
    created_at = Column(DateTime)


class MaterialRow(Base):
    __tablename__ = "materials"

    material_id = Column(String(128), primary_key=True)
    competitor_id = Column(String(128), index=True)
    category = Column(String(64))
    price_band = Column(String(64))
    rating = Column(Float)
    sales_rank = Column(Integer)
    selling_points = Column(JSON)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    archived = Column(Boolean, default=False)


class KnowledgeRow(Base):
    __tablename__ = "knowledge_entries"
    __table_args__ = (UniqueConstraint("competitor_id", "selling_point_key", "version",
                                       name="uq_kb_version"),)

    entry_id = Column(String(128), primary_key=True)
    competitor_id = Column(String(128))
    selling_point_key = Column(String(255), index=True)
    selling_point = Column(Text)
    version = Column(Integer, default=1)
    previous_version_id = Column(String(128), default="")
    created_at = Column(DateTime)
    archived = Column(Boolean, default=False)


def build_engine(dsn: str, echo: bool = False) -> Engine:
    return create_engine(dsn, echo=echo, pool_pre_ping=True)


def _dt(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class MySQLDataStore(ReviewStore, ProfileStore, ScoreReportStore, MaterialStore, KnowledgeStore):
    """把五类存储聚合到一个 MySQL 后端，便于一次注入。"""

    def __init__(self, engine: Engine):
        self._engine = engine
        self._Session = sessionmaker(bind=engine, expire_on_commit=False)

    def create_all(self) -> None:
        Base.metadata.create_all(self._engine)

    # ---- ReviewStore ----
    def insert(self, review: RawReview) -> bool:
        with self._Session() as s:
            if s.query(ReviewRow).filter_by(
                listing_id=review.listing_id, review_id=review.review_id
            ).first() is not None:
                return False
            s.add(ReviewRow(
                review_id=review.review_id,
                listing_id=review.listing_id,
                asin=review.asin,
                reviewer_id=review.reviewer_id,
                rating=review.rating,
                title=review.title,
                content=review.content,
                is_verified=review.is_verified,
                filtered_reason=review.filtered_reason,
                raw_html_ref=review.raw_html_ref,
                crawled_at=_dt(review.crawled_at),
            ))
            s.commit()
            return True

    def exists(self, listing_id: str, review_id: str) -> bool:
        with self._Session() as s:
            return s.query(ReviewRow).filter_by(
                listing_id=listing_id, review_id=review_id
            ).first() is not None

    def get_by_listing(self, listing_id: str) -> List[RawReview]:
        with self._Session() as s:
            rows = s.query(ReviewRow).filter_by(listing_id=listing_id).all()
            return [self._review_from_row(r) for r in rows]

    def get_verified(self, listing_id: str) -> List[RawReview]:
        with self._Session() as s:
            rows = (s.query(ReviewRow)
                    .filter_by(listing_id=listing_id, is_verified=True)
                    .filter(ReviewRow.filtered_reason == "")
                    .all())
            return [self._review_from_row(r) for r in rows]

    def mark_filtered(self, review_id: str, reason: str) -> None:
        with self._Session() as s:
            row = s.query(ReviewRow).filter_by(review_id=review_id).first()
            if row is not None:
                row.filtered_reason = reason
                s.commit()

    @staticmethod
    def _review_from_row(r: "ReviewRow") -> RawReview:
        return RawReview(
            review_id=r.review_id,
            listing_id=r.listing_id,
            asin=r.asin or "",
            reviewer_id=r.reviewer_id or "",
            rating=r.rating or 0.0,
            title=r.title or "",
            content=r.content or "",
            is_verified=bool(r.is_verified),
            filtered_reason=r.filtered_reason or "",
            raw_html_ref=r.raw_html_ref or "",
            crawled_at=r.crawled_at,
        )

    # ---- ProfileStore ----
    def save_version(self, profile: UserProfile) -> str:
        with self._Session() as s:
            s.add(ProfileRow(
                version_id=profile.version_id,
                listing_id=profile.listing_id,
                concerns=[c.model_dump() for c in profile.concerns],
                evidence_manifest=profile.evidence_manifest,
                prev_version_id=profile.prev_version_id,
                created_at=_dt(profile.created_at),
            ))
            s.commit()
        return profile.version_id

    def get_latest(self, listing_id: str) -> Optional[UserProfile]:
        with self._Session() as s:
            row = (s.query(ProfileRow).filter_by(listing_id=listing_id)
                   .order_by(ProfileRow.created_at.desc()).first())
            return self._profile_from_row(row) if row else None

    def get(self, version_id: str) -> Optional[UserProfile]:
        with self._Session() as s:
            row = s.query(ProfileRow).filter_by(version_id=version_id).first()
            return self._profile_from_row(row) if row else None

    @staticmethod
    def _profile_from_row(r: "ProfileRow") -> UserProfile:
        from adgenie.data.domain import Concern, Evidence
        concerns = []
        for c in (r.concerns or []):
            evidences = [Evidence(**e) for e in c.get("evidences", [])]
            concerns.append(Concern(
                concern=c["concern"],
                keywords=c.get("keywords", []),
                evidences=evidences,
            ))
        return UserProfile(
            version_id=r.version_id,
            listing_id=r.listing_id,
            concerns=concerns,
            evidence_manifest=r.evidence_manifest or "",
            prev_version_id=r.prev_version_id or "",
            created_at=r.created_at,
        )

    # ---- ScoreReportStore ----
    def save(self, report: ScoreReport) -> str:
        with self._Session() as s:
            s.add(ScoreReportRow(
                report_id=report.report_id,
                listing_id=report.listing_id,
                copy_version=report.copy_version,
                rubric_version=report.rubric_version,
                model_name=report.model_name,
                temperature=report.temperature,
                alignment_score=report.alignment_score,
                persuasion_score=report.persuasion_score,
                detail=report.detail,
                evidence_snapshot=report.evidence_snapshot,
                created_at=_dt(report.created_at),
            ))
            s.commit()
        return report.report_id

    def get(self, report_id: str) -> Optional[ScoreReport]:
        with self._Session() as s:
            row = s.query(ScoreReportRow).filter_by(report_id=report_id).first()
            return self._report_from_row(row) if row else None

    def list_for_listing(self, listing_id: str) -> List[ScoreReport]:
        with self._Session() as s:
            rows = (s.query(ScoreReportRow).filter_by(listing_id=listing_id)
                    .order_by(ScoreReportRow.created_at.desc()).all())
            return [self._report_from_row(r) for r in rows]

    @staticmethod
    def _report_from_row(r: "ScoreReportRow") -> ScoreReport:
        return ScoreReport(
            report_id=r.report_id,
            listing_id=r.listing_id,
            copy_version=r.copy_version,
            rubric_version=r.rubric_version,
            model_name=r.model_name,
            temperature=r.temperature,
            alignment_score=r.alignment_score,
            persuasion_score=r.persuasion_score,
            detail=r.detail or [],
            evidence_snapshot=r.evidence_snapshot or "",
            created_at=r.created_at,
        )

    # ---- MaterialStore ----
    def upsert(self, material: Material) -> None:
        # 向量不落 MySQL：embedding 由 Milvus 承担，这里只存元数据。
        with self._Session() as s:
            row = s.query(MaterialRow).filter_by(material_id=material.material_id).first()
            if row is None:
                row = MaterialRow(material_id=material.material_id,
                                  competitor_id=material.competitor_id,
                                  created_at=_dt(material.created_at))
                s.add(row)
            row.category = material.category
            row.price_band = material.price_band
            row.rating = material.rating
            row.sales_rank = material.sales_rank
            row.selling_points = material.selling_points
            row.updated_at = _dt(material.updated_at) or _dt(material.created_at)
            row.archived = material.archived
            s.commit()

    def get(self, material_id: str) -> Optional[Material]:
        with self._Session() as s:
            row = s.query(MaterialRow).filter_by(material_id=material_id).first()
            return self._material_from_row(row) if row else None

    def list_all(self) -> List[Material]:
        with self._Session() as s:
            return [self._material_from_row(r) for r in s.query(MaterialRow).all()]

    def coarse_filter(self, category: Optional[str], price_band: Optional[str],
                      rating_min: Optional[float], rating_max: Optional[float],
                      sales_rank_max: Optional[int]) -> List[Material]:
        with self._Session() as s:
            q = s.query(MaterialRow).filter(MaterialRow.archived == False)  # noqa: E712
            if category:
                q = q.filter(MaterialRow.category == category)
            if price_band:
                q = q.filter(MaterialRow.price_band == price_band)
            if rating_min is not None:
                q = q.filter(MaterialRow.rating >= rating_min)
            if rating_max is not None:
                q = q.filter(MaterialRow.rating <= rating_max)
            if sales_rank_max is not None:
                q = q.filter(MaterialRow.sales_rank <= sales_rank_max)
            return [self._material_from_row(r) for r in q.all()]

    @staticmethod
    def _material_from_row(r: "MaterialRow") -> Material:
        return Material(
            material_id=r.material_id,
            competitor_id=r.competitor_id,
            category=r.category or "",
            price_band=r.price_band or "",
            rating=r.rating or 0.0,
            sales_rank=r.sales_rank or 0,
            selling_points=r.selling_points or [],
            embedding=[],
            created_at=r.created_at,
            updated_at=r.updated_at,
            archived=bool(r.archived),
        )

    # ---- KnowledgeStore ----
    def upsert_selling_point(self, competitor_id: str, selling_point_key: str,
                             selling_point: str) -> KnowledgeEntry:
        with self._Session() as s:
            latest = (s.query(KnowledgeRow)
                      .filter_by(competitor_id=competitor_id,
                                 selling_point_key=selling_point_key)
                      .order_by(KnowledgeRow.version.desc()).first())
            if latest is not None and latest.selling_point == selling_point:
                return self._kb_from_row(latest)
            version = (latest.version + 1) if latest else 1
            entry_id = f"{competitor_id}:{selling_point_key}:v{version}"
            row = KnowledgeRow(
                entry_id=entry_id,
                competitor_id=competitor_id,
                selling_point_key=selling_point_key,
                selling_point=selling_point,
                version=version,
                previous_version_id=latest.entry_id if latest else "",
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                archived=False,
            )
            s.add(row)
            s.commit()
            return self._kb_from_row(row)

    def list_active(self) -> List[KnowledgeEntry]:
        with self._Session() as s:
            rows = s.query(KnowledgeRow).filter(KnowledgeRow.archived == False).all()  # noqa: E712
            return [self._kb_from_row(r) for r in rows]

    def history(self, selling_point_key: str) -> List[KnowledgeEntry]:
        with self._Session() as s:
            rows = (s.query(KnowledgeRow).filter_by(selling_point_key=selling_point_key)
                    .order_by(KnowledgeRow.version.asc()).all())
            return [self._kb_from_row(r) for r in rows]

    def archive_outdated(self, older_than_days: int) -> int:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=older_than_days)
        count = 0
        with self._Session() as s:
            rows = s.query(KnowledgeRow).filter(
                KnowledgeRow.archived == False,  # noqa: E712
                KnowledgeRow.created_at < cutoff,
            ).all()
            for r in rows:
                r.archived = True
                count += 1
            s.commit()
        return count

    @staticmethod
    def _kb_from_row(r: "KnowledgeRow") -> KnowledgeEntry:
        return KnowledgeEntry(
            entry_id=r.entry_id,
            competitor_id=r.competitor_id,
            selling_point_key=r.selling_point_key,
            selling_point=r.selling_point,
            version=r.version,
            previous_version_id=r.previous_version_id or "",
            created_at=r.created_at,
            archived=bool(r.archived),
        )
