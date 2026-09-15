import numpy as np
import pytest

from backend.app.live_news.topic_classifier import TopicClassifier, input_hash, normalize_input


class Encoder:
    def encode(self, texts, **kwargs):
        return np.array(
            [
                [1.0, 0.0]
                if "technology" in t.lower() or "人工智能" in t or "software" in t
                else [0.0, 1.0]
                for t in texts
            ]
        )


def test_normalized_input_hash_ignores_whitespace():
    assert input_hash(" A  title ", "a\nsummary") == input_hash("A title", "a summary")
    assert normalize_input("正常中文，新闻") == "正常中文,新闻"


def test_local_classifier_is_deterministic_and_bounds_assignments():
    classifier = TopicClassifier(encoder=Encoder())
    first = classifier.classify_many([("人工智能 technology", "software and chips")])[0]
    assert first == classifier.classify_many([("人工智能 technology", "software and chips")])[0]
    assert 1 <= len(first) <= 3
    assert first[0].topic_id == 1000004
    assert all(0 <= x.score <= 1 for x in first)


def test_empty_input_abstains_instead_of_inventing_interest():
    classifier = TopicClassifier(encoder=Encoder())
    result = classifier.classify_many([("", "")])[0]
    assert [x.topic_id for x in result] == [1000014]


def test_missing_model_fails_without_network(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        TopicClassifier(model_dir=tmp_path)


def test_classifier_version_is_stable_across_line_endings(tmp_path, monkeypatch):
    from backend.app.live_news import topic_classifier

    config = topic_classifier.TAXONOMY_PATH.read_bytes()
    original = TopicClassifier(encoder=Encoder()).version
    copied = tmp_path / "topics.json"
    copied.write_bytes(config.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    monkeypatch.setattr(topic_classifier, "TAXONOMY_PATH", copied)
    assert TopicClassifier(encoder=Encoder()).version == original
