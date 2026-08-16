from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.normalize_mind import normalize_dataset  # noqa: E402

_NEWS = (
    ("N1", "news", "local", "Local election results"),
    ("N2", "news", "world", "World leaders meet for climate talks"),
    ("N3", "sports", "football_nfl", "Football team wins championship"),
    ("N4", "sports", "basketball_nba", "Basketball season preview"),
    ("N5", "finance", "markets", "Stock markets close higher"),
    ("N6", "finance", "personalfinance", "Household saving guide"),
    ("N7", "health", "wellness", "Daily exercise supports wellness"),
    ("N8", "health", "nutrition", "Nutrition experts discuss healthy meals"),
    ("N9", "travel", "travelnews", "Rail travel expands between cities"),
    ("N10", "autos", "autosnews", "Electric vehicle technology advances"),
    ("N11", "foodanddrink", "recipes", "Simple seasonal dinner recipes"),
    ("N12", "lifestyle", "lifestylebuzz", "Community volunteers restore park"),
)


def build_fixture(raw_dir: Path, output_dir: Path) -> Path:
    news_rows = [
        "\t".join(
            (
                news_id,
                category,
                subcategory,
                title,
                f"{title} with verified fixture details.",
                f"https://example.com/{news_id.lower()}",
                "[]",
                "[]",
            )
        )
        for news_id, category, subcategory, title in _NEWS
    ]
    train_candidates = " ".join(
        f"{news_id}-{'1' if index in {1, 3, 5} else '0'}"
        for index, (news_id, *_rest) in enumerate(_NEWS, start=1)
    )
    dev_candidates = " ".join(
        f"{news_id}-{'1' if index in {2, 4} else '0'}"
        for index, (news_id, *_rest) in enumerate(_NEWS, start=1)
    )
    split_behaviors = {
        "train": f"1\tU1\t11/13/2019 8:36:57 AM\t\t{train_candidates}",
        "dev": f"1\tU1\t11/14/2019 8:36:57 AM\tN1 N3\t{dev_candidates}",
    }
    for split, behavior in split_behaviors.items():
        split_dir = raw_dir / split
        split_dir.mkdir(parents=True, exist_ok=True)
        (split_dir / "news.tsv").write_text("\n".join(news_rows) + "\n", encoding="utf-8")
        (split_dir / "behaviors.tsv").write_text(behavior + "\n", encoding="utf-8")
    normalize_dataset(raw_dir, output_dir)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic MIND-compatible fixture for isolated CI databases."
    )
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "build" / "ci_mind_raw")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "build" / "ci_mind_normalized",
    )
    args = parser.parse_args()
    output = build_fixture(args.raw_dir, args.output_dir)
    print(f"wrote deterministic CI MIND fixture to {output}")


if __name__ == "__main__":
    main()
