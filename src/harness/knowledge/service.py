from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from harness.auth.audit import AuditService
from harness.core.errors import ConflictError, NotFoundError
from harness.knowledge.connectors import (
    KnowledgeConnectorError,
    KnowledgeConnectorRegistry,
)
from harness.knowledge.models import (
    CreateKnowledgeBaseRequest,
    CreateKnowledgeSourceRequest,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeCitation,
    KnowledgeSearchHit,
    KnowledgeSnapshot,
    KnowledgeSnapshotBinding,
    KnowledgeSource,
    KnowledgeSourceHealth,
    KnowledgeSyncRun,
    KnowledgeSyncStatus,
    ReplaceKnowledgeBaseRequest,
    ReplaceKnowledgeSourceRequest,
    SearchKnowledgeResponse,
)
from harness.knowledge.repositories import KnowledgeRepository
from harness.knowledge.search import HybridKnowledgeSearch, tokenize


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class KnowledgeService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        connectors: KnowledgeConnectorRegistry | None = None,
        search: HybridKnowledgeSearch | None = None,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
        chunk_characters: int = 1_600,
        chunk_overlap: int = 240,
    ) -> None:
        if chunk_overlap >= chunk_characters:
            raise ValueError("knowledge chunk overlap must be smaller than chunk size")
        self.repository = repository
        self._connectors = connectors or KnowledgeConnectorRegistry()
        self._search = search or HybridKnowledgeSearch()
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ids = id_generator or _id
        self._chunk_characters = chunk_characters
        self._chunk_overlap = chunk_overlap

    async def create_base(
        self,
        tenant_id: str,
        actor_id: str,
        request: CreateKnowledgeBaseRequest,
    ) -> KnowledgeBase:
        await self._require_sources(tenant_id, request.source_references)
        now = self._clock()
        value = KnowledgeBase(
            tenantId=tenant_id,
            reference=request.reference,
            displayName=request.display_name,
            description=request.description,
            sourceReferences=request.source_references,
            revision=1,
            createdBy=actor_id,
            updatedBy=actor_id,
            createdAt=now,
            updatedAt=now,
        )
        await self.repository.add_base(value)
        await self._record(
            tenant_id,
            actor_id,
            "knowledge.base.create",
            value.reference,
            {"source_count": len(value.source_references)},
        )
        return value

    async def replace_base(
        self,
        tenant_id: str,
        actor_id: str,
        reference: str,
        request: ReplaceKnowledgeBaseRequest,
    ) -> KnowledgeBase:
        current = await self.repository.get_base(tenant_id, reference)
        if current.revision != request.expected_revision:
            raise ConflictError("Knowledge Base revision changed")
        await self._require_sources(tenant_id, request.source_references)
        updated = current.model_copy(
            update={
                "display_name": request.display_name,
                "description": request.description,
                "source_references": request.source_references,
                "revision": current.revision + 1,
                "updated_by": actor_id,
                "updated_at": self._clock(),
            }
        )
        if not await self.repository.compare_and_set_base(current.revision, updated):
            raise ConflictError("Knowledge Base changed while it was updated")
        await self._record(
            tenant_id,
            actor_id,
            "knowledge.base.update",
            reference,
            {"source_count": len(updated.source_references)},
        )
        return updated

    async def list_bases(self, tenant_id: str) -> Sequence[KnowledgeBase]:
        return await self.repository.list_bases(tenant_id)

    async def get_base(self, tenant_id: str, reference: str) -> KnowledgeBase:
        return await self.repository.get_base(tenant_id, reference)

    async def create_source(
        self,
        tenant_id: str,
        actor_id: str,
        request: CreateKnowledgeSourceRequest,
    ) -> tuple[KnowledgeSource, KnowledgeSyncRun | None]:
        now = self._clock()
        value = KnowledgeSource(
            tenantId=tenant_id,
            reference=request.reference,
            displayName=request.display_name,
            description=request.description,
            kind=request.kind,
            config=request.config,
            acl=request.acl,
            revision=1,
            health=KnowledgeSourceHealth.PENDING,
            createdBy=actor_id,
            updatedBy=actor_id,
            createdAt=now,
            updatedAt=now,
        )
        await self.repository.add_source(value)
        await self._record(
            tenant_id,
            actor_id,
            "knowledge.source.create",
            value.reference,
            {"kind": value.kind.value, "visibility": value.acl.visibility.value},
        )
        if not request.sync_now:
            return value, None
        sync = await self.sync_source(tenant_id, actor_id, value.reference)
        return await self.repository.get_source(tenant_id, value.reference), sync

    async def replace_source(
        self,
        tenant_id: str,
        actor_id: str,
        reference: str,
        request: ReplaceKnowledgeSourceRequest,
    ) -> KnowledgeSource:
        current = await self.repository.get_source(tenant_id, reference)
        if current.revision != request.expected_revision:
            raise ConflictError("knowledge source revision changed")
        if request.config.type != current.kind.value:
            raise ConflictError("knowledge source connector kind cannot be changed")
        updated = current.model_copy(
            update={
                "display_name": request.display_name,
                "description": request.description,
                "config": request.config,
                "acl": request.acl,
                "health": (
                    KnowledgeSourceHealth.PENDING
                    if request.enabled
                    else KnowledgeSourceHealth.DISABLED
                ),
                "revision": current.revision + 1,
                "updated_by": actor_id,
                "updated_at": self._clock(),
                "last_error": None,
            }
        )
        if not await self.repository.compare_and_set_source(current.revision, updated):
            raise ConflictError("knowledge source changed while it was updated")
        await self._record(
            tenant_id,
            actor_id,
            "knowledge.source.update",
            reference,
            {"enabled": request.enabled},
        )
        return updated

    async def list_sources(self, tenant_id: str) -> Sequence[KnowledgeSource]:
        return await self.repository.list_sources(tenant_id)

    async def get_source(self, tenant_id: str, reference: str) -> KnowledgeSource:
        return await self.repository.get_source(tenant_id, reference)

    async def sync_source(
        self,
        tenant_id: str,
        actor_id: str,
        reference: str,
    ) -> KnowledgeSyncRun:
        source = await self.repository.get_source(tenant_id, reference)
        if source.health is KnowledgeSourceHealth.DISABLED:
            raise ConflictError("disabled knowledge source cannot be synchronized")
        now = self._clock()
        sync = KnowledgeSyncRun(
            tenantId=tenant_id,
            syncId=self._ids("knowledge_sync"),
            sourceReference=reference,
            sourceRevision=source.revision,
            status=KnowledgeSyncStatus.RUNNING,
            checkpointBefore=source.checkpoint,
            createdBy=actor_id,
            createdAt=now,
            startedAt=now,
        )
        await self.repository.add_sync(sync)
        try:
            result = await self._connectors.resolve(source.kind).sync(
                source.config,
                source.checkpoint,
            )
            if not result.documents:
                raise KnowledgeConnectorError("connector returned no documents")
            if source.active_snapshot_id is not None and result.checkpoint.get(
                "contentHash"
            ) == source.checkpoint.get("contentHash"):
                completed_at = self._clock()
                updated_source = source.model_copy(
                    update={
                        "revision": source.revision + 1,
                        "health": KnowledgeSourceHealth.HEALTHY,
                        "last_sync_id": sync.sync_id,
                        "last_sync_at": completed_at,
                        "last_error": None,
                        "updated_by": actor_id,
                        "updated_at": completed_at,
                    }
                )
                if not await self.repository.compare_and_set_source(
                    source.revision, updated_source
                ):
                    raise ConflictError("knowledge source changed while sync completed")
                completed = sync.model_copy(
                    update={
                        "status": KnowledgeSyncStatus.UNCHANGED,
                        "checkpoint_after": result.checkpoint,
                        "snapshot_id": source.active_snapshot_id,
                        "documents_seen": len(result.documents),
                        "completed_at": completed_at,
                    }
                )
                await self.repository.put_sync(completed)
                return completed

            snapshot_id = self._ids("knowledge_snapshot")
            chunks = self._chunk_documents(
                tenant_id=tenant_id,
                source=source,
                snapshot_id=snapshot_id,
                documents=result.documents,
            )
            if not chunks:
                raise KnowledgeConnectorError("connector documents produced no chunks")
            completed_at = self._clock()
            snapshot = KnowledgeSnapshot(
                tenantId=tenant_id,
                snapshotId=snapshot_id,
                sourceReference=source.reference,
                sourceRevision=source.revision + 1,
                contentHash=KnowledgeSnapshot.digest_chunks(chunks),
                documentCount=len(result.documents),
                chunkCount=len(chunks),
                checkpoint=result.checkpoint,
                createdAt=completed_at,
            )
            completed = sync.model_copy(
                update={
                    "status": KnowledgeSyncStatus.SUCCEEDED,
                    "checkpoint_after": result.checkpoint,
                    "snapshot_id": snapshot_id,
                    "documents_seen": len(result.documents),
                    "chunks_written": len(chunks),
                    "completed_at": completed_at,
                }
            )
            updated_source = source.model_copy(
                update={
                    "revision": source.revision + 1,
                    "health": KnowledgeSourceHealth.HEALTHY,
                    "active_snapshot_id": snapshot_id,
                    "checkpoint": result.checkpoint,
                    "last_sync_id": sync.sync_id,
                    "last_sync_at": completed_at,
                    "last_error": None,
                    "updated_by": actor_id,
                    "updated_at": completed_at,
                }
            )
            if not await self.repository.publish_snapshot(
                expected_source_revision=source.revision,
                source=updated_source,
                snapshot=snapshot,
                chunks=chunks,
                sync=completed,
            ):
                raise ConflictError("knowledge source changed while snapshot was published")
            await self._record(
                tenant_id,
                actor_id,
                "knowledge.source.sync",
                source.reference,
                {
                    "sync_id": sync.sync_id,
                    "snapshot_id": snapshot_id,
                    "documents": len(result.documents),
                    "chunks": len(chunks),
                },
            )
            return completed
        except Exception as error:
            completed_at = self._clock()
            failed = sync.model_copy(
                update={
                    "status": KnowledgeSyncStatus.FAILED,
                    "error_code": type(error).__name__,
                    "error_message": str(error)[:1_000],
                    "completed_at": completed_at,
                }
            )
            await self.repository.put_sync(failed)
            # A concurrent edit or sync conflict is not connector degradation. More
            # importantly, an older failed worker must never overwrite a newer source
            # revision or replace its healthy active snapshot.
            if not isinstance(error, ConflictError):
                degraded = source.model_copy(
                    update={
                        "revision": source.revision + 1,
                        "health": KnowledgeSourceHealth.DEGRADED,
                        "last_sync_id": sync.sync_id,
                        "last_sync_at": completed_at,
                        "last_error": str(error)[:1_000],
                        "updated_by": actor_id,
                        "updated_at": completed_at,
                    }
                )
                await self.repository.compare_and_set_source(
                    source.revision,
                    degraded,
                )
            await self._record(
                tenant_id,
                actor_id,
                "knowledge.source.sync",
                source.reference,
                {
                    "sync_id": sync.sync_id,
                    "outcome": "failed",
                    "error_code": type(error).__name__,
                },
            )
            if isinstance(error, (ConflictError, KnowledgeConnectorError)):
                raise
            raise KnowledgeConnectorError("knowledge source synchronization failed") from error

    async def resolve_bindings(
        self,
        tenant_id: str,
        actor_id: str,
        knowledge_base_references: Sequence[str],
    ) -> tuple[KnowledgeSnapshotBinding, ...]:
        bindings: list[KnowledgeSnapshotBinding] = []
        seen: set[tuple[str, str]] = set()
        for base_reference in knowledge_base_references:
            base = await self.repository.get_base(tenant_id, base_reference)
            for source_reference in base.source_references:
                source = await self.repository.get_source(tenant_id, source_reference)
                key = (base_reference, source_reference)
                if (
                    key in seen
                    or not source.acl.allows(actor_id)
                    or source.health is not KnowledgeSourceHealth.HEALTHY
                    or source.active_snapshot_id is None
                ):
                    continue
                seen.add(key)
                bindings.append(
                    KnowledgeSnapshotBinding(
                        knowledgeBaseReference=base_reference,
                        sourceReference=source_reference,
                        snapshotId=source.active_snapshot_id,
                        trust=source.result_trust,
                    )
                )
        return tuple(bindings)

    async def search(
        self,
        tenant_id: str,
        actor_id: str,
        query: str,
        *,
        knowledge_base_references: Sequence[str] = (),
        bindings: Sequence[KnowledgeSnapshotBinding] = (),
        limit: int = 8,
    ) -> SearchKnowledgeResponse:
        resolved_bindings = (
            tuple(bindings)
            if bindings
            else await self.resolve_bindings(
                tenant_id,
                actor_id,
                knowledge_base_references,
            )
        )
        # Recheck ACL before loading any candidate text. Session-pinned snapshot IDs do not
        # bypass later access revocation.
        allowed: list[KnowledgeSnapshotBinding] = []
        source_by_reference: dict[str, KnowledgeSource] = {}
        for binding in resolved_bindings:
            source = source_by_reference.get(binding.source_reference)
            if source is None:
                source = await self.repository.get_source(tenant_id, binding.source_reference)
                source_by_reference[source.reference] = source
            if source.acl.allows(actor_id):
                allowed.append(binding)
        snapshots = frozenset(item.snapshot_id for item in allowed)
        chunks = await self.repository.list_chunks(tenant_id, snapshots)
        ranked = self._search.search(chunks, query, limit=limit)
        binding_by_pair = {(item.source_reference, item.snapshot_id): item for item in allowed}
        hits: list[KnowledgeSearchHit] = []
        for item in ranked:
            chunk = item.chunk
            binding = binding_by_pair[(chunk.source_reference, chunk.snapshot_id)]
            source = source_by_reference[chunk.source_reference]
            hits.append(
                KnowledgeSearchHit(
                    content=chunk.content,
                    score=item.score,
                    trust=binding.trust,
                    citation=KnowledgeCitation(
                        knowledgeBaseReference=(binding.knowledge_base_reference),
                        sourceReference=chunk.source_reference,
                        sourceDisplayName=source.display_name,
                        snapshotId=chunk.snapshot_id,
                        documentId=chunk.document_id,
                        chunkId=chunk.chunk_id,
                        title=chunk.title,
                        uri=chunk.source_uri,
                    ),
                    matchedTerms=item.matched_terms,
                )
            )
        return SearchKnowledgeResponse(
            hits=tuple(hits),
            searchedSnapshotIds=tuple(sorted(snapshots)),
        )

    async def get_visible_chunk(
        self,
        tenant_id: str,
        actor_id: str,
        snapshot_id: str,
        chunk_id: str,
    ) -> KnowledgeChunk:
        snapshot = await self.repository.get_snapshot(tenant_id, snapshot_id)
        source = await self.repository.get_source(
            tenant_id,
            snapshot.source_reference,
        )
        if not source.acl.allows(actor_id):
            raise NotFoundError("knowledge citation not found")
        chunks = await self.repository.list_chunks(
            tenant_id,
            frozenset({snapshot_id}),
        )
        chunk = next(
            (item for item in chunks if item.chunk_id == chunk_id),
            None,
        )
        if chunk is None:
            raise NotFoundError("knowledge citation not found")
        return chunk

    async def require_bases(
        self,
        tenant_id: str,
        references: Sequence[str],
    ) -> None:
        for reference in references:
            await self.repository.get_base(tenant_id, reference)

    def _chunk_documents(
        self,
        *,
        tenant_id: str,
        source: KnowledgeSource,
        snapshot_id: str,
        documents: Sequence[object],
    ) -> tuple[KnowledgeChunk, ...]:
        from harness.knowledge.models import ConnectorDocument

        chunks: list[KnowledgeChunk] = []
        now = self._clock()
        for raw_document in documents:
            document = ConnectorDocument.model_validate(raw_document)
            content = "\n".join(
                line.rstrip() for line in document.content.replace("\r\n", "\n").splitlines()
            ).strip()
            if not content:
                continue
            start = 0
            ordinal = 0
            while start < len(content):
                stop = min(len(content), start + self._chunk_characters)
                if stop < len(content):
                    boundary = max(
                        content.rfind("\n", start, stop),
                        content.rfind("。", start, stop),
                        content.rfind(". ", start, stop),
                    )
                    if boundary > start + self._chunk_characters // 2:
                        stop = boundary + 1
                chunk_content = content[start:stop].strip()
                if chunk_content:
                    chunk_hash = hashlib.sha256(chunk_content.encode()).hexdigest()
                    chunk_id = hashlib.sha256(
                        (
                            f"{source.reference}\0{document.document_id}\0{ordinal}\0{chunk_hash}"
                        ).encode()
                    ).hexdigest()[:40]
                    chunks.append(
                        KnowledgeChunk(
                            tenantId=tenant_id,
                            snapshotId=snapshot_id,
                            sourceReference=source.reference,
                            chunkId=chunk_id,
                            documentId=document.document_id,
                            ordinal=ordinal,
                            title=document.title,
                            sourceUri=document.source_uri,
                            content=chunk_content,
                            contentHash=chunk_hash,
                            tokenTerms=tokenize(f"{document.title}\n{chunk_content}"),
                            createdAt=now,
                        )
                    )
                    ordinal += 1
                if stop >= len(content):
                    break
                start = max(start + 1, stop - self._chunk_overlap)
        return tuple(chunks)

    async def _require_sources(self, tenant_id: str, references: Sequence[str]) -> None:
        for reference in references:
            await self.repository.get_source(tenant_id, reference)

    async def _record(
        self,
        tenant_id: str,
        actor_id: str,
        action: str,
        resource_id: str,
        details: dict[str, object],
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            tenant_id=tenant_id,
            user_id=actor_id,
            action=action,
            resource_type="knowledge",
            resource_id=resource_id,
            outcome=str(details.get("outcome", "success")),
            details=details,
        )
