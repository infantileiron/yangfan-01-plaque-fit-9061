"""不依赖 sklearn / 数据库的核心逻辑测试，纯标准库可运行：

    cd backend && python -I tests/test_core.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.business.demo import TEMPLATES, demo_rows  # noqa: E402
from src.business.encoding import SMOOTHING, TargetStats  # noqa: E402
from src.business.grouping import apply_grouping, plan_grouping  # noqa: E402
from src.services.lineage import batch_key_of  # noqa: E402


def row(sample_id, exhibit, split, template="LY-T01", label="否", lang="中文/英文"):
    return {
        "sample_id": sample_id, "exhibit_id": exhibit, "split": split,
        "template": template, "lang_pair": lang,
        "width_mm": 75, "lines": 3, "ink_mm": 180.0, "overflow": label,
    }


def build_rows():
    rows = []
    serial = 1
    # 40 个训练展品、12 个留出展品，每组 2~3 条改版，双类齐全。
    for side, count in (("训练", 40), ("留出", 12)):
        for index in range(count):
            exhibit = f"LY-E-{side}-{index:02d}"
            revisions = 2 + index % 2
            for revision in range(revisions):
                label = "是" if revision == 0 else "否"
                rows.append(row(f"H{serial:03d}", exhibit, side,
                                template=TEMPLATES[index % 13], label=label))
                serial += 1
    return rows


class GroupingTests(unittest.TestCase):
    def test_clean_input_keeps_original_split(self):
        rows = build_rows()
        grouped, report = apply_grouping(rows)
        self.assertEqual(report["moved_samples"], 0)
        self.assertEqual({r["split"] for r in grouped if r["exhibit_id"].startswith("LY-E-训练")}, {"训练"})
        self.assertEqual({r["split"] for r in grouped if r["exhibit_id"].startswith("LY-E-留出")}, {"留出"})

    def test_leaking_exhibit_is_moved_whole(self):
        rows = build_rows()
        # 把一个训练展品的一条改版塞进留出，制造跨侧泄漏。
        rows[0]["split"] = "留出"
        plan = plan_grouping(rows)
        grouped, report = apply_grouping(rows)
        exhibit = rows[0]["exhibit_id"]
        self.assertTrue(all(plan["assignment"][r["exhibit_id"]] == plan["assignment"][exhibit]
                            for r in rows if r["exhibit_id"] == exhibit))
        self.assertEqual(report["moved_samples"], 1)
        train_exhibits = {r["exhibit_id"] for r in grouped if r["split"] == "训练"}
        holdout_exhibits = {r["exhibit_id"] for r in grouped if r["split"] == "留出"}
        self.assertFalse(train_exhibits & holdout_exhibits)

    def test_both_sides_keep_two_classes(self):
        rows = build_rows()
        grouped, _ = apply_grouping(rows)
        for side in ("训练", "留出"):
            labels = {r["overflow"] for r in grouped if r["split"] == side}
            self.assertEqual(labels, {"是", "否"})

    def test_rare_template_kept_in_training(self):
        rows = build_rows()
        rare = TEMPLATES[-1]
        # 稀有版式只出现在一个留出展品上，必须被整组挪回训练。
        for r in rows:
            if r["template"] == rare:
                r["template"] = "LY-T01"
        target = next(r for r in rows if r["exhibit_id"] == "LY-E-留出-11")
        for r in rows:
            if r["exhibit_id"] == target["exhibit_id"]:
                r["template"] = rare
        grouped, report = apply_grouping(rows)
        self.assertIn(rare, {r["template"] for r in grouped if r["split"] == "训练"})
        self.assertGreaterEqual(report["moved_samples"], 2)

    def test_infeasible_explains_reason(self):
        rows = build_rows()
        # 全部有标签纸样都未溢出，任何整组划分都凑不出双类，必须终止并说明。
        for r in rows:
            if r["split"] in ("训练", "留出"):
                r["overflow"] = "否"
        with self.assertRaises(ValueError) as context:
            plan_grouping(rows)
        self.assertIn("溢出", str(context.exception))

    def test_pending_exhibit_must_not_overlap(self):
        rows = build_rows()
        rows.append(row("P01", rows[0]["exhibit_id"], "待校", label=None))
        rows[-1]["overflow"] = None
        with self.assertRaises(ValueError):
            plan_grouping(rows)

    def test_missing_exhibit_id_rejected(self):
        rows = build_rows()
        rows[0]["exhibit_id"] = ""
        with self.assertRaises(ValueError):
            plan_grouping(rows)

    def test_fully_mixed_input_repairs_with_minimal_change(self):
        rows = []
        serial = 1
        for exhibit_index in range(60):
            for revision in range(3):
                rows.append(row(
                    f"H{serial:03d}", f"LY-M{exhibit_index:02d}",
                    "训练" if revision < 2 else "留出",
                    template=TEMPLATES[exhibit_index % 13],
                    label="是" if (exhibit_index + revision) % 3 == 0 else "否",
                ))
                serial += 1
        grouped, report = apply_grouping(rows)
        train_exhibits = {r["exhibit_id"] for r in grouped if r["split"] == "训练"}
        holdout_exhibits = {r["exhibit_id"] for r in grouped if r["split"] == "留出"}
        self.assertFalse(train_exhibits & holdout_exhibits)
        # 理论最小改动：4 个留出组各改 2 条（8）+ 56 个训练组各改回 1 条（56）= 64。
        self.assertEqual(report["moved_samples"], 64)

    def test_holdout_fill_prefers_natural_holdout_exhibits(self):
        rows = []
        serial = 1
        # 52 个天然训练组（3 条全在训练）+ 8 个天然留出组（3 条全在留出）。
        # 人为把部分天然留出组错标进训练，制造留出下限缺口，验证修复取最小改动。
        for exhibit_index in range(60):
            natural = "留出" if exhibit_index >= 52 else "训练"
            for revision in range(3):
                rows.append(row(
                    f"H{serial:03d}", f"LY-N{exhibit_index:02d}", natural,
                    template=TEMPLATES[exhibit_index % 13],
                    label="是" if (exhibit_index + revision) % 3 == 0 else "否",
                ))
                serial += 1
        # 把 6 个天然留出组错标进训练，留出只剩 2 组 6 条，低于 12 条下限。
        for item in rows:
            if item["exhibit_id"] in {f"LY-N{index:02d}" for index in range(52, 58)}:
                item["split"] = "训练"
        # 修复取最小改动：把 2 个天然训练组整组挪到留出（每组改 3 条）只需 6 条，
        # 低于恢复 6 个天然留出组所需的 18 条，因此优化器应选前者。
        grouped, report = apply_grouping(rows)
        self.assertEqual(report["moved_samples"], 6)
        holdout_exhibits = {r["exhibit_id"] for r in grouped if r["split"] == "留出"}
        train_exhibits = {r["exhibit_id"] for r in grouped if r["split"] == "训练"}
        self.assertFalse(holdout_exhibits & train_exhibits)
        self.assertGreaterEqual(len([r for r in grouped if r["split"] == "留出"]), 12)
        for side in ("训练", "留出"):
            self.assertEqual({r["overflow"] for r in grouped if r["split"] == side}, {"是", "否"})

    def test_large_input_stays_fast(self):
        import time
        rows = []
        serial = 1
        for exhibit_index in range(1600):
            for revision in range(3):
                rows.append(row(
                    f"H{serial:05d}", f"LY-B{exhibit_index:04d}",
                    "留出" if exhibit_index % 5 == 0 else "训练",
                    template=TEMPLATES[exhibit_index % 13],
                    label="是" if (exhibit_index + revision) % 2 else "否",
                ))
                serial += 1
        started = time.time()
        _, report = apply_grouping(rows)
        self.assertLess(time.time() - started, 2.0)
        self.assertEqual(report["moved_samples"], 0)


class EncodingTests(unittest.TestCase):
    def test_loo_excludes_whole_exhibit(self):
        rows = build_rows()
        labels = [int(r["overflow"] == "是") for r in rows]
        stats = TargetStats(rows, labels)
        first = rows[0]
        exhibit = first["exhibit_id"]
        encoded = stats.encode(first, labels[0])
        # 手工按整组留一口径重算版式编码，必须一致。
        group = [r for r in rows if r["exhibit_id"] == exhibit]
        group_size = len(group)
        group_positive = sum(int(r["overflow"] == "是") for r in group)
        prior = (sum(labels) - group_positive) / (len(rows) - group_size)
        count = sum(r["template"] == first["template"] for r in rows)
        positive = sum(int(r["overflow"] == "是") for r in rows if r["template"] == first["template"])
        group_count = sum(r["template"] == first["template"] for r in group)
        group_pos = sum(int(r["overflow"] == "是") for r in group if r["template"] == first["template"])
        expected = (positive - group_pos + SMOOTHING * prior) / (count - group_count + SMOOTHING)
        self.assertAlmostEqual(encoded[0], expected)

    def test_holdout_uses_full_mapping(self):
        rows = build_rows()
        labels = [int(r["overflow"] == "是") for r in rows]
        stats = TargetStats(rows, labels)
        holdout = next(r for r in rows if r["split"] == "留出")
        encoded = stats.encode(holdout)  # 不传 own_label
        prior = sum(labels) / len(rows)
        count = sum(r["template"] == holdout["template"] for r in rows)
        positive = sum(int(r["overflow"] == "是") for r in rows if r["template"] == holdout["template"])
        expected = (positive + SMOOTHING * prior) / (count + SMOOTHING)
        self.assertAlmostEqual(encoded[0], expected)


class LineageTests(unittest.TestCase):
    def test_batch_key_normalization(self):
        self.assertEqual(batch_key_of("镭页_常设展铭牌_2026-11-25.csv"),
                         batch_key_of("镭页_常设展铭牌_2026-11-26.csv"))
        self.assertEqual(batch_key_of("展陈底稿v1"), batch_key_of("展陈底稿v2"))
        self.assertNotEqual(batch_key_of("常设展铭牌"), batch_key_of("特展铭牌"))


class DemoDataTests(unittest.TestCase):
    def test_demo_rows_are_group_isolated_and_feasible(self):
        rows = demo_rows()
        grouped, report = apply_grouping(rows)
        self.assertEqual(report["moved_samples"], 0)
        labeled = [r for r in grouped if r["split"] in ("训练", "留出")]
        pending = [r for r in grouped if r["split"] == "待校"]
        self.assertEqual(len(pending), 8)
        self.assertGreaterEqual(len([r for r in labeled if r["split"] == "训练"]), 30)
        self.assertGreaterEqual(len([r for r in labeled if r["split"] == "留出"]), 12)
        for side in ("训练", "留出"):
            self.assertEqual({r["overflow"] for r in labeled if r["split"] == side}, {"是", "否"})
        train_templates = {r["template"] for r in labeled if r["split"] == "训练"}
        self.assertTrue(set(TEMPLATES) <= train_templates)
        # 待校里保留一个陌生参考语组合，驱动“补纸样”分支。
        self.assertTrue(any(r["lang_pair"] == "中文/芬兰文" for r in pending))
        # 纸样与展品编号都唯一。
        self.assertEqual(len({r["sample_id"] for r in rows}), len(rows))
        exhibits = [r["exhibit_id"] for r in labeled]
        self.assertFalse(set(exhibits) & {r["exhibit_id"] for r in pending})


if __name__ == "__main__":
    unittest.main(verbosity=2)
