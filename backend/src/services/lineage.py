"""同批源数据的版本谱系。

同一份源底稿更新后以新内容导入：批次键（由版本名称归一得到）相同即视为
同批的新一版。旧版本被标记 superseded_by，其上所有计算单标记 obsolete；
同时按旧版最近一次计算单的参数在新版本上自动提交一次重跑（几何基准与
目标编码两版模型在同一计算单内同时重算、按 Brier 择优）。
"""
import re


def batch_key_of(name):
    """去掉扩展名与结尾日期/版本号，得到同批源数据的归组键。"""
    key = name.strip()
    key = re.sub(r"\.csv$", "", key, flags=re.IGNORECASE)
    key = re.sub(r"[_\-]?v?\d+$", "", key)
    key = re.sub(r"[_\-]?\d{4}-\d{2}-\d{2}$", "", key)
    return key.strip() or name.strip()


def supersede_and_recompute(db, latest, author):
    """把同批次的旧版本置为失效，并在新版本上自动重跑。返回自动重跑单（可空）。"""
    from sqlalchemy import select

    from src.constants.workflow import Stage
    from src.models.dataset import Dataset
    from src.models.run import Run
    from src.services.audit import record

    previous = db.scalars(
        select(Dataset).where(Dataset.batch_key == latest.batch_key, Dataset.id != latest.id)
        .order_by(Dataset.created_at.desc(), Dataset.id.desc())
    ).all()
    if not previous:
        return None
    template_run = db.scalar(
        select(Run).where(Run.dataset_id.in_([item.id for item in previous]))
        .order_by(Run.created_at.desc(), Run.id.desc()).limit(1)
    )
    for item in previous:
        item.superseded_by = latest.id
        for run in db.scalars(select(Run).where(Run.dataset_id == item.id)):
            run.obsolete = True
        record(db, author, "dataset_superseded", item.id)
    if template_run is None:
        return None
    recompute = Run(
        dataset_id=latest.id,
        label=f"同批更新自动重跑（{latest.name}）",
        parameter=template_run.parameter,
        actor=author,
        status=Stage.QUEUED.value,
        auto_recompute=True,
    )
    db.add(recompute)
    db.flush()
    record(db, author, "run_auto_recompute", recompute.id)
    return recompute
