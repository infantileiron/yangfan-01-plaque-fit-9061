"""按展品编号做整组隔离的数据分组。

同一展品（exhibit_id）的改版纸样必须整体落在同一侧（训练或留出），
避免改版样本在两侧互相泄漏、抬高留出 Brier。本模块只决定分组归属，
不修改行内的其它字段；尽量沿用原始 split，改动以纸样条数计并取最小。
"""
from collections import defaultdict

LABELED_SPLITS = ("训练", "留出")
MIN_TRAIN = 30
MIN_HOLDOUT = 12


def _side_of(rows):
    """原始分组里多数票决定的一侧；平票优先训练（改动纸样数相同且更省训练侧）。"""
    train = sum(row["split"] == "训练" for row in rows)
    holdout = len(rows) - train
    return "训练" if train >= holdout else "留出"


def plan_grouping(rows):
    """返回 {exhibit_id: 侧} 的整组归属及分组报告。

    待校纸样不参与训练/留出划分，但其展品编号不得与有标签展品重复。
    约束：
      - 训练、留出均不少于既有口径的下限；
      - 每一侧都同时包含溢出（是）和未溢出（否）纸样；
      - 训练侧必须覆盖到出现过的每一种版式，给稀有版式留训练样本。
    约束无法满足时抛出 ValueError，并说明原因。
    """
    exhibits = defaultdict(list)
    pending_exhibits = set()
    for row in rows:
        exhibit = row.get("exhibit_id")
        if not exhibit:
            raise ValueError("每条纸样都必须填写展品编号。")
        if row["split"] == "待校":
            pending_exhibits.add(exhibit)
        elif row["split"] in LABELED_SPLITS:
            exhibits[exhibit].append(row)
        else:
            raise ValueError(f"展品 {exhibit} 的数据分组不在 训练/留出/待校 范围内。")
    overlap = pending_exhibits & set(exhibits)
    if overlap:
        raise ValueError(f"待校展品不得与有标签展品共用编号：{', '.join(sorted(overlap))}。")
    if not exhibits:
        raise ValueError("缺少可分组的训练/留出纸样。")

    assignment = {exhibit: _side_of(rows_of) for exhibit, rows_of in exhibits.items()}
    order = sorted(exhibits, key=lambda item: (len(exhibits[item]), item))

    def side_rows(side):
        return [row for exhibit, rows_of in exhibits.items() if assignment[exhibit] == side for row in rows_of]

    def violations():
        problems = []
        train_rows, holdout_rows = side_rows("训练"), side_rows("留出")
        if len(train_rows) < MIN_TRAIN:
            problems.append(f"训练侧仅 {len(train_rows)} 条，少于 {MIN_TRAIN} 条。")
        if len(holdout_rows) < MIN_HOLDOUT:
            problems.append(f"留出侧仅 {len(holdout_rows)} 条，少于 {MIN_HOLDOUT} 条。")
        for side, side_rows_of in (("训练", train_rows), ("留出", holdout_rows)):
            marks = {row["overflow"] for row in side_rows_of}
            if "是" not in marks:
                problems.append(f"{side}侧缺少溢出（是）类纸样。")
            if "否" not in marks:
                problems.append(f"{side}侧缺少未溢出（否）类纸样。")
        rare = sorted({row["template"] for row in rows if row["split"] in LABELED_SPLITS}
                      - {row["template"] for row in train_rows})
        if rare:
            problems.append("稀有版式在训练侧没有样本：" + "、".join(rare) + "。")
        return problems

    def move_cost(exhibit, target):
        return sum(row["split"] != target for row in exhibits[exhibit])

    def constraint_keys():
        # 细粒度约束键：数量、双类（按侧）、稀有版式（按版式），用于判断是否在推进。
        keys = set()
        train_rows, holdout_rows = side_rows("训练"), side_rows("留出")
        if len(train_rows) < MIN_TRAIN:
            keys.add("train_count")
        if len(holdout_rows) < MIN_HOLDOUT:
            keys.add("holdout_count")
        for side, side_rows_of in (("训练", train_rows), ("留出", holdout_rows)):
            marks = {row["overflow"] for row in side_rows_of}
            if "是" not in marks:
                keys.add(f"{side}_positive")
            if "否" not in marks:
                keys.add(f"{side}_negative")
        for template in sorted({row["template"] for row in rows if row["split"] in LABELED_SPLITS}
                               - {row["template"] for row in train_rows}):
            keys.add(f"template_{template}")
        return keys

    # 第一阶段：逐次换侧，优先消除不同的未满足约束，直到全部满足或确认无可行解。
    for _ in range(len(exhibits) * 2 + 1):
        unresolved = constraint_keys()
        if not unresolved:
            break

        # 数量类约束无法靠“单步立刻见效”满足（例如留出至少 12 条而每组只有 3 条），
        # 先按缺口定向搬运，再用通用贪心处理双类与稀有版式。
        train_rows, holdout_rows = side_rows("训练"), side_rows("留出")
        if "holdout_count" in unresolved:
            candidates = [exhibit for exhibit in order if assignment[exhibit] == "训练"]
            if not candidates:
                raise ValueError("无法在整组隔离下满足分组约束：" + "；".join(violations()))
            # 优先搬“原始多数侧就是留出”的展品：这些本来就该在留出侧，改动最小。
            candidates.sort(key=lambda item: (_side_of(exhibits[item]) != "留出",
                                              move_cost(item, "留出"), len(exhibits[item])))
            assignment[candidates[0]] = "留出"
            continue
        if "train_count" in unresolved:
            candidates = [exhibit for exhibit in order if assignment[exhibit] == "留出"]
            if not candidates:
                raise ValueError("无法在整组隔离下满足分组约束：" + "；".join(violations()))
            candidates.sort(key=lambda item: (_side_of(exhibits[item]) != "训练",
                                              move_cost(item, "训练"), -len(exhibits[item])))
            assignment[candidates[0]] = "训练"
            continue

        best = None
        for exhibit in order:
            target = "留出" if assignment[exhibit] == "训练" else "训练"
            previous = assignment[exhibit]
            assignment[exhibit] = target
            remaining = constraint_keys()
            assignment[exhibit] = previous
            healed = len(unresolved - remaining)
            introduced = len(remaining - unresolved)
            score = (-healed, introduced, len(remaining), move_cost(exhibit, target))
            if best is None or score < best[0]:
                best = (score, exhibit, target)
        # 没有任何换侧能消除至少一个当前约束：数据本身不满足整组隔离口径。
        if best is None or best[0][0] == 0:
            raise ValueError("无法在整组隔离下满足分组约束：" + "；".join(violations()))
        assignment[best[1]] = best[2]
    if constraint_keys():
        raise ValueError("无法在整组隔离下满足分组约束：" + "；".join(violations()))

    # 第二阶段：在不破坏可行性的前提下，把不必要的换侧换回去，最小化改动纸样数。
    def total_moved():
        return sum(move_cost(exhibit, assignment[exhibit]) for exhibit in exhibits)

    if total_moved():
        improved = True
        while improved:
            improved = False
            for exhibit in sorted(exhibits, key=lambda item: -move_cost(item, assignment[item])):
                original = _side_of(exhibits[exhibit])
                if assignment[exhibit] == original:
                    continue
                previous = assignment[exhibit]
                assignment[exhibit] = original
                if not violations():
                    improved = True
                    break
                assignment[exhibit] = previous

    # 第三阶段：允许两侧各换一个展品（保持规模与可行性），用顺原分组的替换逆原分组的。
    misplaced = [exhibit for exhibit in exhibits if assignment[exhibit] != _side_of(exhibits[exhibit])]
    if misplaced:
        swapped = True
        rounds = 0
        max_rounds = min(len(misplaced), 30)
        while swapped and rounds < max_rounds:
            swapped = False
            rounds += 1
            for left in sorted(misplaced, key=lambda item: -move_cost(item, assignment[item])):
                left_side = assignment[left]
                right_side = "留出" if left_side == "训练" else "训练"
                # 先用成本增量筛出确实能降本的对侧配对，再做可行性校验。
                promising = []
                for right in exhibits:
                    if right == left or assignment[right] != right_side:
                        continue
                    delta = (move_cost(left, right_side) - move_cost(left, left_side)
                             + move_cost(right, left_side) - move_cost(right, right_side))
                    if delta < 0:
                        promising.append((delta, right))
                for _, right in sorted(promising):
                    assignment[left], assignment[right] = right_side, left_side
                    if not violations():
                        swapped = True
                        break
                    assignment[left], assignment[right] = left_side, right_side
                if swapped:
                    break

    changed = []
    for exhibit in sorted(exhibits):
        for row in exhibits[exhibit]:
            if row["split"] != assignment[exhibit]:
                changed.append({"sample_id": row["sample_id"], "exhibit_id": exhibit,
                                "from": row["split"], "to": assignment[exhibit]})
    train_exhibits = sum(1 for side in assignment.values() if side == "训练")
    holdout_exhibits = len(assignment) - train_exhibits
    return {
        "assignment": assignment,
        "report": {
            "exhibits": len(exhibits),
            "train_exhibits": train_exhibits,
            "holdout_exhibits": holdout_exhibits,
            "moved_samples": total_moved(),
            "changes": changed,
        },
    }


def apply_grouping(rows):
    """按整组归属重写 split，返回 (新行列表, 报告)。待校纸样保持原样。"""
    plan = plan_grouping(rows)
    assignment = plan["assignment"]
    grouped = []
    for row in rows:
        if row["split"] == "待校":
            grouped.append(dict(row))
        else:
            updated = dict(row)
            updated["split"] = assignment[row["exhibit_id"]]
            grouped.append(updated)
    return grouped, plan["report"]
