"""Initial schema for a fresh Compose volume, plus lightweight column upgrades."""
from sqlalchemy import text

from src.models.account import Account
from src.models.audit import Event
from src.models.dataset import Dataset
from src.models.review import Review
from src.models.run import Run

SCHEMA = (Account, Dataset, Run, Review, Event)

# 旧卷升级用的补列语句（PostgreSQL 兼容 IF NOT EXISTS）。
_ADDED_COLUMNS = {
    "datasets": (
        "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS batch_key VARCHAR(160) DEFAULT ''",
        "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS superseded_by VARCHAR(36)",
        "ALTER TABLE datasets ADD COLUMN IF NOT EXISTS grouping_report JSON",
    ),
    "runs": (
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS obsolete BOOLEAN DEFAULT FALSE",
        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS auto_recompute BOOLEAN DEFAULT FALSE",
    ),
}
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_datasets_batch_key ON datasets (batch_key)",
    "CREATE INDEX IF NOT EXISTS ix_runs_obsolete ON runs (obsolete)",
)


def migrate(engine):
    tables = [model.__table__ for model in SCHEMA]
    Account.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        for table, statements in _ADDED_COLUMNS.items():
            for statement in statements:
                connection.execute(text(statement))
        for statement in _INDEXES:
            connection.execute(text(statement))
        # 旧数据没有批次键时按名称归一回填，保持同批更新可识别。
        connection.execute(text(
            "UPDATE datasets SET batch_key = name WHERE batch_key IS NULL OR batch_key = ''"
        ))
