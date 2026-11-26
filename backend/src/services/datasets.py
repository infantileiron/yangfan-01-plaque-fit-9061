from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.business.grouping import apply_grouping
from src.business.profile import PROFILE
from src.config.settings import Session
from src.models.dataset import Dataset
from src.schemas.resources import dataset_view
from src.services import lineage
from src.services.audit import record
from src.utils.csv_data import digest, parse_csv


def require(db, dataset_id):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(404, "数据版本不存在。")
    return dataset


def list_datasets():
    with Session() as db:
        return [dataset_view(row) for row in db.scalars(select(Dataset).order_by(Dataset.created_at.desc(), Dataset.id.desc()))]


def save_in(db, name, rows, author, audit=True):
    """持久化一个数据版本。

    导入前先按展品编号做整组隔离校验/最小修复；约束无法满足时直接抛错，
    不留半成品。返回 (dataset, created, recompute_run)。
    """
    grouped, grouping_report = apply_grouping(rows)
    checksum = digest(grouped)
    existing = db.scalar(select(Dataset).where(Dataset.checksum == checksum))
    if existing is not None:
        return existing, False, None
    item = Dataset(
        name=name, checksum=checksum, rows=grouped, author=author,
        batch_key=lineage.batch_key_of(name), grouping_report=grouping_report,
    )
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(select(Dataset).where(Dataset.checksum == checksum).with_for_update())
        if existing is None:
            raise
        return existing, False, None
    recompute = lineage.supersede_and_recompute(db, item, author)
    if audit:
        record(db, author, "dataset_imported", item.id)
    return item, True, recompute


def ingest(name, contents, author):
    try:
        rows = parse_csv(contents, PROFILE["columns"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with Session.begin() as db:
        try:
            item, created, recompute = save_in(db, name, rows, author)
        except ValueError as exc:
            # 整组隔离约束无法满足：说明原因，拒绝导入。
            raise HTTPException(422, str(exc)) from exc
        response = {**dataset_view(item), "created": created}
        if recompute is not None:
            response["auto_recompute_run_id"] = recompute.id
        return response
