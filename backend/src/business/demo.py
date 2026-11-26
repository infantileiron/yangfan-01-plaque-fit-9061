from random import Random

TEMPLATES = [f"LY-T{index:02d}" for index in range(1, 14)]
LANGUAGES = ["中文/英文", "中文/法文", "中文/德文", "中文/日文"]
# 长尾版式权重：前密后疏，最后四类为稀有版式。
TEMPLATE_WEIGHTS = [14, 14, 12, 11, 10, 9, 8, 6, 5, 4, 3, 2, 2]
EXHIBIT_COUNT = 96
HOLDOUT_EXHIBITS = 20


def demo_rows():
    rng = Random(53125)
    exhibits = []
    for index in range(EXHIBIT_COUNT):
        exhibits.append({
            "exhibit_id": f"LY-E{index + 1:03}",
            "template": TEMPLATES[rng.choices(range(13), TEMPLATE_WEIGHTS)[0]],
            "lang": LANGUAGES[rng.randrange(4)],
            "revisions": rng.choice([2, 2, 3]),
        })
    # 先抽留出展品，再把其余全部放进训练；稀有版式必须在训练侧有展品。
    holdout_indexes = set(rng.sample(range(EXHIBIT_COUNT), HOLDOUT_EXHIBITS))
    rare_templates = set(TEMPLATES[-4:])
    for template in rare_templates:
        owners = [index for index, item in enumerate(exhibits) if item["template"] == template]
        if owners and all(index in holdout_indexes for index in owners):
            replacement = next(index for index in holdout_indexes if index not in owners)
            holdout_indexes.discard(owners[0])
            holdout_indexes.add(replacement)

    rows = []
    sample_serial = 1
    for index, item in enumerate(exhibits):
        side = "留出" if index in holdout_indexes else "训练"
        # 同一展品共享版式与参考语，各改版只在几何参数上微调，模拟真实改版纸样。
        width, lines = rng.choice([62, 75, 88, 101]), rng.choice([2, 3, 4])
        base_ratio = round(rng.uniform(0.61, 1.31), 3)
        template_index = TEMPLATES.index(item["template"])
        lang_index = LANGUAGES.index(item["lang"])
        limit = 1.03 + (template_index % 4 - 1.5) * 0.085 + [0.025, 0.0, -0.07, 0.075][lang_index]
        revisions = []
        for _ in range(item["revisions"]):
            ratio = round(base_ratio + rng.gauss(0, 0.03), 3)
            label = "是" if ratio + rng.gauss(0, 0.045) > limit else "否"
            revisions.append([ratio, label])
        # 保证每个留出展品内部能覆盖两种实测结果，避免单展品单类。
        if side == "留出" and len({label for _, label in revisions}) == 1:
            flip = rng.randrange(len(revisions))
            if revisions[flip][1] == "是":
                revisions[flip] = [round(limit - 0.12, 3), "否"]
            else:
                revisions[flip] = [round(min(limit + 0.06, 1.34), 3), "是"]
        for ratio, label in revisions:
            rows.append(sample(
                f"LY-H{sample_serial:03}", item["exhibit_id"], side, item["template"], item["lang"],
                width, lines, ratio, label,
            ))
            sample_serial += 1

    pending = [
        (0, 2, 75, 3, 1.32), (1, 0, 88, 4, 0.65), (4, 2, 62, 3, 1.18),
        (6, 0, 101, 2, 1.07), (2, 3, 75, 4, 0.99), (2, 1, 62, 3, 0.67),
        (8, 3, 88, 3, 1.10), (0, 4, 75, 3, 0.76),
    ]
    for index, (template, lang, width, lines, ratio) in enumerate(pending, start=1):
        language = LANGUAGES[lang] if lang < len(LANGUAGES) else "中文/芬兰文"
        rows.append(sample(f"LY-P{index:02}", f"LY-Q{index:02}", "待校", TEMPLATES[template],
                           language, width, lines, ratio, None))
    return rows


def sample(sample_id, exhibit_id, split, template, language, width, lines, ratio, label):
    return {
        "sample_id": sample_id, "exhibit_id": exhibit_id, "split": split,
        "template": template, "lang_pair": language,
        "width_mm": width, "lines": lines, "ink_mm": round(width * lines * ratio, 2), "overflow": label,
    }
