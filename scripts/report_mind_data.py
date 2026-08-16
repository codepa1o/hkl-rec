from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_summary(normalized_dir: Path) -> dict[str, Any]:
    manifest = _load_json(normalized_dir / "normalization_manifest.json")
    articles = pq.read_table(
        normalized_dir / "articles.parquet",
        columns=[
            "article_id",
            "category",
            "subcategory",
            "abstract",
            "first_seen_train_ts",
            "first_seen_dev_ts",
        ],
    ).to_pandas()
    train_requests = pq.read_table(
        normalized_dir / "requests_train.parquet",
        columns=[
            "request_id",
            "user_id",
            "history_article_ids",
            "candidate_count",
            "positive_count",
        ],
    ).to_pandas()
    dev_requests = pq.read_table(
        normalized_dir / "requests_dev.parquet",
        columns=[
            "request_id",
            "user_id",
            "history_article_ids",
            "candidate_count",
            "positive_count",
        ],
    ).to_pandas()
    train_impressions = pq.read_table(
        normalized_dir / "impressions_train.parquet",
        columns=["article_id", "clicked"],
    ).to_pandas()
    dev_impressions = pq.read_table(
        normalized_dir / "impressions_dev.parquet",
        columns=["article_id", "clicked"],
    ).to_pandas()

    exposure = train_impressions.groupby("article_id").agg(
        impressions=("clicked", "size"),
        clicks=("clicked", "sum"),
    )
    exposure["ctr"] = exposure["clicks"] / exposure["impressions"]
    sorted_exposure = exposure["impressions"].sort_values(ascending=False)
    top_one_percent = max(1, round(len(sorted_exposure) * 0.01))
    top_ten_percent = max(1, round(len(sorted_exposure) * 0.10))
    total_exposure = int(sorted_exposure.sum())
    train_users = set(train_requests["user_id"].astype(int))
    dev_users = set(dev_requests["user_id"].astype(int))
    train_articles = set(train_impressions["article_id"].astype(int))
    dev_articles = set(dev_impressions["article_id"].astype(int))
    return {
        "dataset": "MIND-small",
        "normalized_fingerprint": manifest["normalized_fingerprint"],
        "splits": {
            "train": {
                **manifest["split_summary"]["train"],
                "mean_candidates_per_request": round(
                    float(train_requests["candidate_count"].mean()), 6
                ),
                "mean_positives_per_request": round(
                    float(train_requests["positive_count"].mean()), 6
                ),
                "median_history_length": int(
                    train_requests["history_article_ids"].map(len).median()
                ),
            },
            "dev": {
                **manifest["split_summary"]["dev"],
                "mean_candidates_per_request": round(
                    float(dev_requests["candidate_count"].mean()), 6
                ),
                "mean_positives_per_request": round(
                    float(dev_requests["positive_count"].mean()), 6
                ),
                "median_history_length": int(dev_requests["history_article_ids"].map(len).median()),
            },
        },
        "content": {
            "unique_articles": len(articles),
            "categories": int(articles["category"].nunique()),
            "subcategories": int(articles["subcategory"].nunique()),
            "empty_abstract_ratio": round(float((articles["abstract"] == "").mean()), 6),
            "top_categories": articles["category"].value_counts().head(10).to_dict(),
        },
        "overlap_and_cold_start": {
            "train_dev_user_overlap": len(train_users & dev_users),
            "dev_known_user_ratio": round(len(train_users & dev_users) / len(dev_users), 6),
            "train_dev_article_overlap": len(train_articles & dev_articles),
            "dev_cold_article_ratio": round(
                len(dev_articles - train_articles) / len(dev_articles),
                6,
            ),
        },
        "exposure": {
            "article_count_with_train_exposure": len(exposure),
            "ctr_quantiles": {
                str(quantile): round(float(exposure["ctr"].quantile(quantile)), 6)
                for quantile in (0.0, 0.25, 0.5, 0.75, 0.95, 1.0)
            },
            "top_1_percent_exposure_share": round(
                float(sorted_exposure.head(top_one_percent).sum()) / total_exposure,
                6,
            ),
            "top_10_percent_exposure_share": round(
                float(sorted_exposure.head(top_ten_percent).sum()) / total_exposure,
                6,
            ),
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    train = summary["splits"]["train"]
    dev = summary["splits"]["dev"]
    content = summary["content"]
    overlap = summary["overlap_and_cold_start"]
    exposure = summary["exposure"]
    top_categories = "\n".join(
        f"| {category} | {count:,} |" for category, count in content["top_categories"].items()
    )
    return f"""# MIND-small 数据分析

本报告由规范化后的公开 MIND 数据生成。数据指纹：
`{summary["normalized_fingerprint"]}`.

## 规模

| 数据集 | 请求数 | 候选项数 | 正样本数 | 用户数 | 每请求平均候选项 | 每请求平均正样本 |
|---|---:|---:|---:|---:|---:|---:|
| 训练集 | {train["requests"]:,} | {train["candidates"]:,} | {train["positives"]:,} | {train["users"]:,} | {train["mean_candidates_per_request"]:.2f} | {train["mean_positives_per_request"]:.2f} |
| 开发集 | {dev["requests"]:,} | {dev["candidates"]:,} | {dev["positives"]:,} | {dev["users"]:,} | {dev["mean_candidates_per_request"]:.2f} | {dev["mean_positives_per_request"]:.2f} |

训练集的历史长度中位数为 {train["median_history_length"]}，开发集为
{dev["median_history_length"]}。每个规范化候选项都是真实曝光项，
没有引入随机的未曝光负样本。

## 内容

- {content["unique_articles"]:,} 篇唯一文章；
- {content["categories"]} 个类别和 {content["subcategories"]} 个子类别；
- 空摘要比例：{content["empty_abstract_ratio"]:.2%}；
- 每篇规范化文章都包含标题、类别和子类别。

| 主要类别 | 文章数 |
|---|---:|
{top_categories}

## 曝光与点击率

- 文章点击率中位数：{exposure["ctr_quantiles"]["0.5"]:.4f}；
- 文章点击率第 95 百分位：{exposure["ctr_quantiles"]["0.95"]:.4f}；
- 曝光量最高的 1% 文章获得训练集 {exposure["top_1_percent_exposure_share"]:.2%} 的曝光；
- 曝光量最高的 10% 文章获得 {exposure["top_10_percent_exposure_share"]:.2%} 的曝光。

这些是数据集时间窗口内的经验统计值，并非在线产品点击率。

## 训练集/开发集重叠与冷启动

- 重叠用户数：{overlap["train_dev_user_overlap"]:,}
  （占开发集用户的 {overlap["dev_known_user_ratio"]:.2%}）；
- 重叠曝光文章数：{overlap["train_dev_article_overlap"]:,}；
- 开发集冷启动文章比例：{overlap["dev_cold_article_ratio"]:.2%}。

由于开发集已知用户覆盖率较低，协同检索采用训练集内部的时间顺序留出法评估。
官方开发集则作为独立的冷启动内容/类别评估场景报告。

## 在线目录

在线 PostgreSQL 导入和搜索索引均以本报告的完整规范化目录为输入，目录完整性由
`normalization_manifest.json` 指纹和导入记录共同校验。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 MIND 数据汇总报告。")
    parser.add_argument(
        "--normalized-dir",
        type=Path,
        default=ROOT / "build" / "mind_normalized",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / "docs" / "metrics" / "mind_data_summary.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=ROOT / "docs" / "data_analysis_report.md",
    )
    args = parser.parse_args()
    summary = build_summary(args.normalized_dir)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(render_markdown(summary), encoding="utf-8")
    print(f"wrote {args.json_output} and {args.markdown_output}")


if __name__ == "__main__":
    main()
