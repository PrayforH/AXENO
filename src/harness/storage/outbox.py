"""Outbox record primitives for durable event publication."""

from datetime import UTC, datetime
from typing import Any

from harness.storage.models import OutboxRow


def new_outbox_record(topic: str, aggregate_id: str, payload: dict[str, Any]) -> OutboxRow:
    return OutboxRow(
        topic=topic,
        aggregate_id=aggregate_id,
        payload=payload,
        created_at=datetime.now(UTC),
        published_at=None,
    )
