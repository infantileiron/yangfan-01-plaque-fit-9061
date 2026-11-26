from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, new_id, utcnow


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    checksum: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    rows: Mapped[list] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String(160))
    # 同批源数据的归组键（由版本名称归一得到）；同键更新即形成版本谱系。
    batch_key: Mapped[str] = mapped_column(String(160), default="", index=True)
    superseded_by: Mapped[str | None] = mapped_column(String(36))
    grouping_report: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
