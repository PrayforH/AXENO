from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from harness.knowledge.models import KnowledgeChunk

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_CJK = re.compile(r"[\u3400-\u9fff]")


def tokenize(value: str) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in _WORD.findall(value.casefold()):
        terms.append(raw)
        cjk = "".join(character for character in raw if _CJK.match(character))
        if cjk:
            terms.extend(cjk)
            terms.extend(cjk[index : index + 2] for index in range(len(cjk) - 1))
    return tuple(term for term in terms if term)


@dataclass(frozen=True)
class RankedChunk:
    chunk: KnowledgeChunk
    score: float
    matched_terms: tuple[str, ...]


class HybridKnowledgeSearch:
    """Deterministic BM25 + TF-IDF cosine retrieval with RRF and light reranking."""

    def search(
        self,
        chunks: Sequence[KnowledgeChunk],
        query: str,
        *,
        limit: int,
    ) -> tuple[RankedChunk, ...]:
        if not chunks:
            return ()
        query_terms = tokenize(query)
        if not query_terms:
            return ()
        corpus_terms = [item.token_terms or tokenize(item.content) for item in chunks]
        document_frequency: Counter[str] = Counter()
        for terms in corpus_terms:
            document_frequency.update(set(terms))
        query_counts = Counter(query_terms)
        count = len(chunks)
        average_length = max(1, sum(len(item) for item in corpus_terms) / count)
        bm25: list[tuple[int, float]] = []
        vectors: list[tuple[int, float]] = []
        for index, terms in enumerate(corpus_terms):
            frequencies = Counter(terms)
            bm25_score = 0.0
            dot = 0.0
            document_norm = 0.0
            query_norm = 0.0
            for term in set((*frequencies.keys(), *query_counts.keys())):
                inverse = math.log((count + 1) / (document_frequency[term] + 1)) + 1
                document_weight = frequencies[term] * inverse
                query_weight = query_counts[term] * inverse
                dot += document_weight * query_weight
                document_norm += document_weight**2
                query_norm += query_weight**2
                if term in query_counts:
                    frequency = frequencies[term]
                    k1 = 1.5
                    b = 0.75
                    denominator = frequency + k1 * (1 - b + b * len(terms) / average_length)
                    if denominator:
                        bm25_score += (
                            inverse * frequency * (k1 + 1) / denominator * query_counts[term]
                        )
            bm25.append((index, bm25_score))
            cosine = (
                dot / math.sqrt(document_norm * query_norm) if document_norm and query_norm else 0
            )
            vectors.append((index, cosine))
        bm25.sort(key=lambda item: (-item[1], chunks[item[0]].chunk_id))
        vectors.sort(key=lambda item: (-item[1], chunks[item[0]].chunk_id))
        fused: defaultdict[int, float] = defaultdict(float)
        for ranking in (bm25, vectors):
            for rank, (index, score) in enumerate(ranking, start=1):
                if score > 0:
                    fused[index] += 1 / (60 + rank)
        query_folded = " ".join(query.split()).casefold()
        scored: list[tuple[int, float]] = []
        for index, score in fused.items():
            content_folded = chunks[index].content.casefold()
            terms = set(corpus_terms[index])
            coverage = sum(term in terms for term in set(query_terms)) / len(set(query_terms))
            phrase = 1.0 if query_folded and query_folded in content_folded else 0.0
            scored.append((index, score + coverage * 0.01 + phrase * 0.02))
        scored.sort(key=lambda item: (-item[1], chunks[item[0]].chunk_id))
        if not scored:
            return ()
        maximum = max(score for _, score in scored) or 1
        results: list[RankedChunk] = []
        for index, score in scored[:limit]:
            matched = tuple(sorted(set(query_terms).intersection(corpus_terms[index])))
            results.append(
                RankedChunk(
                    chunk=chunks[index],
                    score=min(1.0, score / maximum),
                    matched_terms=matched,
                )
            )
        return tuple(results)
