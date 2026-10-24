from geoalchemy2 import Geography, WKBElement
from sqlalchemy import Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Geozone(Base, TimestampMixin):
    __tablename__ = "geozones"
    __table_args__ = (
        Index("ix_geozones_user_id", "user_id"),
        Index(
            "ix_geozones_center",
            "center",
            postgresql_using="gist",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    center: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    radius_m: Mapped[float] = mapped_column(Float, nullable=False)
