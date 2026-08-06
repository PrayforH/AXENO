from datetime import UTC, datetime

from harness.knowledge.models import KnowledgeChunk
from harness.knowledge.search import HybridKnowledgeSearch, tokenize


def chunk(identifier: str, content: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        tenantId="tenant",
        snapshotId="snapshot",
        sourceReference="source",
        chunkId=identifier,
        documentId=identifier,
        ordinal=0,
        title=identifier,
        sourceUri=f"knowledge://file/{identifier}",
        content=content,
        contentHash="0" * 64,
        tokenTerms=tokenize(content),
        createdAt=datetime(2026, 7, 19, tzinfo=UTC),
    )


def test_chinese_bigrams_and_phrase_rerank() -> None:
    values = (
        chunk("other", "这份材料讨论世界杯历史，但没有本届结论。"),
        chunk("answer", "世界杯舆论走向显示球迷更关注裁判判罚。"),
    )

    result = HybridKnowledgeSearch().search(
        values,
        "世界杯舆论走向",
        limit=2,
    )

    assert result[0].chunk.chunk_id == "answer"
    assert "世界杯舆论走向" in tokenize("世界杯舆论走向")
    assert "世界" in tokenize("世界杯舆论走向")


def test_stable_tie_breaking_uses_chunk_id() -> None:
    values = (
        chunk("b", "same query words"),
        chunk("a", "same query words"),
    )

    result = HybridKnowledgeSearch().search(values, "same query", limit=2)

    assert [item.chunk.chunk_id for item in result] == ["a", "b"]
