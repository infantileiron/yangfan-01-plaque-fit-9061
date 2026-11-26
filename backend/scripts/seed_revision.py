"""生成同批源数据的修订版并重新导入，演示版本谱系与自动重跑。

用法（容器内）：python -m scripts.seed_revision
修订版与首版共享批次键（文件名仅日期不同），导入后首版及其计算单自动失效，
系统按首版最近一次计算参数在新版上自动提交一次重跑。
"""
import json

from sqlalchemy import select

from migrations.bootstrap import migrate
from src.business.demo import demo_rows
from src.business.profile import PROFILE
from src.config.settings import Session, engine, redis
from src.models.dataset import Dataset
from src.services.datasets import save_in
from src.services.runs import WAKE_KEY
from src.utils.csv_data import parse_csv, render_csv

REVISION_NAME = "镭页_常设展铭牌_2026-11-26.csv"


def revised_rows():
    rows = demo_rows()
    for row in rows:
        # 模拟同批源数据更新：部分待校纸样几何参数修订，内容哈希必然变化。
        if row["split"] == "待校":
            row["ink_mm"] = round(row["ink_mm"] * 1.03, 2)
    return rows


def seed_revision():
    columns = PROFILE["columns"]
    rows = parse_csv(render_csv(revised_rows(), [column["key"] for column in columns]), columns)
    with Session.begin() as db:
        item, created, recompute = save_in(db, REVISION_NAME, rows, "seed", audit=True)
        result = {
            "id": item.id, "name": item.name, "created": created,
            "superseded": [row.id for row in db.scalars(
                select(Dataset).where(Dataset.superseded_by == item.id))],
            "auto_recompute_run_id": recompute.id if recompute else None,
        }
    if recompute is not None:
        try:
            redis.lpush(WAKE_KEY, recompute.id)
        except Exception:
            pass
    return result


if __name__ == "__main__":
    migrate(engine)
    print(json.dumps(seed_revision(), ensure_ascii=False))
