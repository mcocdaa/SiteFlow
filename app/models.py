from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[str] = mapped_column(String(10))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, default="{}")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    entry: Mapped[str] = mapped_column(Text, default="")
    cover: Mapped[str] = mapped_column(String(100), default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=lambda: datetime.now(UTC).isoformat())
    updated_at: Mapped[str] = mapped_column(String, default=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict:
        data = {column.name: getattr(self, column.name) for column in self.__table__.columns}
        data["has_password"] = bool(self.password_hash)
        data.pop("password_hash", None)
        return data
