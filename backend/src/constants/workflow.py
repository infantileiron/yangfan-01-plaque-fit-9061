from enum import Enum


class Role(str, Enum):
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Stage(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Decision(str, Enum):
    APPROVE = "approve"
    HOLD = "hold"


# 仅用于前端审计文案映射的补充动作（事件本身是自由字符串）。
AUDIT_LABELS = {
    "dataset_imported": "导入数据",
    "dataset_superseded": "旧版失效",
    "run_queued": "提交计算",
    "run_auto_recompute": "自动重跑",
    "run_succeeded": "完成计算",
    "run_failed": "计算失败",
    "review_approve": "签发交接",
    "review_hold": "暂缓交接",
}
