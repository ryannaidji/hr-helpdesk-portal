"""Policy corpus and retrieval. Role filtering happens BEFORE ranking, so restricted text never reaches a model."""
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import DATA_DIR

STOPWORDS = set(
    "a an and are as at be but by can do does for from get has have how i if in is it its long many may me much my need "
    "of on or our should the their there this to up us was we what when where which who will with would you your "
    "company halcyon ridge policy".split()
)
AUDIENCE_RANK = {"all": 0, "manager": 1, "hr": 2}
ROLE_RANK = {"employee": 0, "manager": 1, "hr": 2}
MIN_CONFIDENCE = 0.5  # BM25 mode only. Lexical overlap cannot judge paraphrases, so embedding mode does not use it.


@dataclass(frozen=True)
class Chunk:
    id: str  # doc-slug#section-slug, the citation key
    title: str
    section: str
    text: str
    audience: str


@dataclass(frozen=True)
class Retrieved:
    chunk: Chunk
    score: float


def tokens(text: str) -> list[str]:
    out = []
    for token in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()):
        if token in STOPWORDS:
            continue
        out.append(token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token)
    return out


def load_corpus(directory: Path | None = None) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted((directory or DATA_DIR / "policies").glob("*.md")):
        _, front, body = path.read_text(encoding="utf-8").split("---", 2)
        meta = dict(line.split(": ", 1) for line in front.strip().splitlines())
        for block in re.split(r"^## ", body, flags=re.M)[1:]:
            heading, text = block.split("\n", 1)
            slug = re.sub(r"[^a-z0-9]+", "-", heading.strip().lower()).strip("-")
            chunks.append(Chunk(f"{path.stem}#{slug}", meta["title"], heading.strip(), text.strip(), meta["audience"]))
    return chunks


def visible_to(role: str, chunk: Chunk) -> bool:
    return AUDIENCE_RANK.get(chunk.audience, 99) <= ROLE_RANK.get(role, -1)


class Retriever:
    """BM25 by default; cosine over Ollama embeddings when an embed function is given."""

    def __init__(self, corpus: list[Chunk], embed: Callable[[list[str]], list[list[float]]] | None = None):
        self.corpus = corpus
        self.embed = embed
        self.doc_tokens = [tokens(f"{c.title} {c.section} {c.text}") for c in corpus]
        self._stats: dict[str, tuple[Counter, int, float]] = {}
        self.matrix = None
        if embed:
            vectors = np.array(embed([f"{c.title}: {c.section}. {c.text}" for c in corpus]), dtype=float)
            self.matrix = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

    @property
    def uses_embeddings(self) -> bool:
        return self.matrix is not None

    def _role_stats(self, role: str) -> tuple[Counter, int, float]:
        """Corpus statistics over only what this role may read, so restricted text cannot influence a score."""
        if role not in self._stats:
            docs = [d for d, c in zip(self.doc_tokens, self.corpus, strict=True) if visible_to(role, c)]
            self._stats[role] = (Counter(t for d in docs for t in set(d)), len(docs), sum(map(len, docs)) / max(len(docs), 1))
        return self._stats[role]

    def _bm25(self, query: list[str], index: int, role: str, k1: float = 1.5, b: float = 0.75) -> float:
        doc = self.doc_tokens[index]
        freq = Counter(doc)
        df, total, avg_len = self._role_stats(role)
        score = 0.0
        for term in query:
            if term in freq:
                idf = math.log(1 + (total - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * freq[term] * (k1 + 1) / (freq[term] + k1 * (1 - b + b * len(doc) / avg_len))
        return score

    def search(self, query: str, role: str, k: int = 3) -> list[Retrieved]:
        allowed = [i for i, chunk in enumerate(self.corpus) if visible_to(role, chunk)]
        if self.matrix is not None:
            vector = np.array(self.embed([query])[0], dtype=float)
            sims = self.matrix @ (vector / np.linalg.norm(vector))
            scored = [(float(sims[i]), i) for i in allowed]
        else:
            terms = tokens(query)
            scored = [(self._bm25(terms, i, role), i) for i in allowed]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: -item[0])
        return [Retrieved(self.corpus[i], score) for score, i in scored[:k]]

    def _idf(self, term: str, role: str) -> float:
        df, total, _ = self._role_stats(role)
        return math.log(1 + (total - df[term] + 0.5) / (df[term] + 0.5))

    def confidence(self, query: str, hits: list[Retrieved], role: str) -> float:
        """IDF-weighted share of the question's content words found in the retrieved text. Used to abstain.

        Weighting by rarity stops common words ("paid", "days", "year") from vouching for a question
        whose distinctive word ("sabbatical", "jury") appears nowhere in the retrieved policy text.
        """
        terms = set(tokens(query))
        if not terms or not hits:
            return 0.0
        found = set().union(*(set(tokens(f"{h.chunk.title} {h.chunk.section} {h.chunk.text}")) for h in hits))
        return sum(self._idf(t, role) for t in terms & found) / sum(self._idf(t, role) for t in terms)
