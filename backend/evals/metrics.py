"""Deterministic scoring helpers (no LLM judge)."""
import re

from app.retrieval import tokens

_CITE = re.compile(r"\[[a-z0-9-]+#[a-z0-9-]+\]")
_NUMBER = re.compile(r"\d+(?:[.:]\d+)?")


def sentence_supported(sentence: str, source: str, min_overlap: float = 0.5) -> bool:
    """A sentence is supported if every number in it is in the source and half its content words are."""
    if any(n not in _NUMBER.findall(source) for n in _NUMBER.findall(sentence)):
        return False
    words = set(tokens(sentence))
    return not words or len(words & set(tokens(source))) / len(words) >= min_overlap


def groundedness(answer: str, source: str) -> float:
    """Share of the answer's sentences supported by the text of the chunks it cites."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", _CITE.sub("", answer).strip()) if s.strip()]
    return sum(sentence_supported(s, source) for s in sentences) / len(sentences) if sentences else 0.0


def routing_report(pairs: list[tuple[str, str]]) -> dict:
    """pairs are (gold, predicted)."""
    labels = sorted({gold for gold, _ in pairs})
    per_class = {}
    for label in labels:
        tp = sum(g == label and p == label for g, p in pairs)
        predicted = sum(p == label for _, p in pairs)
        actual = sum(g == label for g, _ in pairs)
        per_class[label] = {"precision": round(tp / predicted, 3) if predicted else 0.0,
                            "recall": round(tp / actual, 3), "n": actual}
    return {"accuracy": round(sum(g == p for g, p in pairs) / len(pairs), 3), "n": len(pairs), "per_class": per_class}
