from collections import Counter, defaultdict

CATEGORIES = ("template", "lang_pair")
SMOOTHING = 8


class TargetStats:
    """仅在训练纸样上拟合的留一平滑目标统计。

    留一以展品（exhibit_id）为单位：编码某条训练纸样时，同展品的全部改版
    纸样都要从计数、正例和先验里扣除，防止同展品改版互相泄漏。待校和留出
    纸样没有自身标签，直接使用完整训练映射；未知类别回退训练先验。
    """

    def __init__(self, rows, labels):
        self.count = len(labels)
        self.positives = sum(labels)
        self.counts = Counter((key, row[key]) for row in rows for key in CATEGORIES)
        self.sums = Counter()
        self.exhibit_counts = defaultdict(Counter)
        self.exhibit_sums = defaultdict(Counter)
        self.exhibit_sizes = Counter()
        self.exhibit_positives = Counter()
        for row, label in zip(rows, labels):
            exhibit = row["exhibit_id"]
            self.exhibit_sizes[exhibit] += 1
            self.exhibit_positives[exhibit] += label
            for key in CATEGORIES:
                self.sums[key, row[key]] += label
                self.exhibit_sums[exhibit][key, row[key]] += label
                self.exhibit_counts[exhibit][key, row[key]] += 1

    def encode(self, row, own_label=None):
        exhibit = row["exhibit_id"]
        if own_label is None:
            # 留出与待校纸样使用完整训练映射，未知类别自然回退训练先验。
            group_counts = group_sums = Counter()
            group_size = 0
        else:
            # 训练留一：整组扣除本展品的全部改版纸样。
            group_counts = self.exhibit_counts[exhibit]
            group_sums = self.exhibit_sums[exhibit]
            group_size = self.exhibit_sizes[exhibit]
        prior = (self.positives - self.exhibit_positives[exhibit]) / (self.count - group_size) \
            if own_label is not None else self.positives / self.count
        return [
            (self.sums[key, row[key]] - group_sums[key, row[key]] + SMOOTHING * prior)
            / (self.counts[key, row[key]] - group_counts[key, row[key]] + SMOOTHING)
            for key in CATEGORIES
        ]

    def unseen(self, row):
        names = {"template": "版式", "lang_pair": "参考语组合"}
        return [names[key] for key in CATEGORIES if self.counts[key, row[key]] == 0]
