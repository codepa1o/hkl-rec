import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def evaluate_rules(
    article: Mapping[str, Any], rules: Sequence[Mapping[str, Any]]
) -> tuple[bool, float, list[str]]:
    """Chinese text uses substring matching; domains and topics use exact matching."""
    blocked, boost, reasons = False, 0.0, []
    text = normalize(
        f"{article.get('title', '')} {article.get('abstract', article.get('summary', ''))}"
    )
    topics = {normalize(str(v)) for v in article.get("topics", [])}
    topics.update(normalize(str(article.get(k) or "")) for k in ("category", "subcategory"))
    for rule in rules:
        if not rule["enabled"]:
            continue
        value = normalize(rule["value"])
        kind = rule["target_type"]
        match = (
            value in text
            if kind == "keyword"
            else value == normalize(article.get("source_domain", ""))
            if kind == "source"
            else value in topics
        )
        if not match:
            continue
        effect = rule["effect"]
        blocked |= effect == "block"
        boost += 1.0 if effect == "prefer" else -1.0 if effect == "reduce" else 0
        reasons.append(
            f"{'优先阅读' if effect == 'prefer' else '减少推荐' if effect == 'reduce' else '已屏蔽'}：{rule['value']}"
        )
    return blocked, boost, reasons
