from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import socket
from collections.abc import Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Protocol, cast
from urllib.parse import urljoin, urlsplit

import httpx

from harness.knowledge.models import (
    ConnectorDocument,
    ConnectorSyncResult,
    FileKnowledgeConfig,
    KnowledgeSourceConfig,
    KnowledgeSourceKind,
    WebKnowledgeConfig,
)


class KnowledgeConnectorError(ValueError):
    pass


class KnowledgeConnector(Protocol):
    async def sync(
        self,
        config: KnowledgeSourceConfig,
        checkpoint: Mapping[str, str | int],
    ) -> ConnectorSyncResult: ...


class FileKnowledgeConnector:
    async def sync(
        self,
        config: KnowledgeSourceConfig,
        checkpoint: Mapping[str, str | int],
    ) -> ConnectorSyncResult:
        if not isinstance(config, FileKnowledgeConfig):
            raise KnowledgeConnectorError("file connector received another config type")
        documents = tuple(
            ConnectorDocument(
                documentId=item.document_id,
                title=item.title,
                content=item.content,
                sourceUri=item.source_uri or f"knowledge://file/{item.document_id}",
            )
            for item in config.documents
        )
        content_hash = _documents_hash(documents)
        return ConnectorSyncResult(
            documents=documents,
            checkpoint={
                "contentHash": content_hash,
                "documentCount": len(documents),
            },
        )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignored_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        normalized = " ".join(data.split())
        if not normalized:
            return
        if self._in_title:
            self.title = f"{self.title} {normalized}".strip()
        self._parts.append(normalized)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self._parts).splitlines())
        return "\n".join(line for line in lines if line)


def _documents_hash(documents: tuple[ConnectorDocument, ...]) -> str:
    digest = hashlib.sha256()
    for item in sorted(documents, key=lambda value: value.document_id):
        for value in (item.document_id, item.title, item.source_uri, item.content):
            digest.update(value.encode())
            digest.update(b"\0")
    return digest.hexdigest()


def _safe_network_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


async def _assert_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise KnowledgeConnectorError("Web knowledge URLs must use HTTPS")
    if parsed.username or parsed.password or not parsed.hostname:
        raise KnowledgeConnectorError("Web knowledge URL authority is invalid")
    if parsed.port not in (None, 443):
        raise KnowledgeConnectorError("Web knowledge URLs may only use port 443")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not _safe_network_address(str(literal)):
            raise KnowledgeConnectorError("Web knowledge URL resolves to a private network")
        return

    def resolve() -> list[tuple[object, ...]]:
        return cast(
            list[tuple[object, ...]],
            socket.getaddrinfo(
                parsed.hostname,
                443,
                type=socket.SOCK_STREAM,
            ),
        )

    try:
        addresses = await asyncio.to_thread(resolve)
    except OSError as error:
        raise KnowledgeConnectorError("Web knowledge host cannot be resolved") from error
    if not addresses:
        raise KnowledgeConnectorError("Web knowledge host has no addresses")
    for item in addresses:
        sockaddr = cast(tuple[object, ...], item[4])
        if not sockaddr or not _safe_network_address(str(sockaddr[0])):
            raise KnowledgeConnectorError("Web knowledge URL resolves to a private network")


class WebKnowledgeConnector:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20,
        max_redirects: int = 3,
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._max_redirects = max_redirects

    async def sync(
        self,
        config: KnowledgeSourceConfig,
        checkpoint: Mapping[str, str | int],
    ) -> ConnectorSyncResult:
        del checkpoint
        if not isinstance(config, WebKnowledgeConfig):
            raise KnowledgeConnectorError("Web connector received another config type")
        current_url = str(config.url)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=False,
        )
        try:
            raw: bytes | None = None
            response_headers: httpx.Headers | None = None
            response_encoding: str | None = None
            for _ in range(self._max_redirects + 1):
                await _assert_public_url(current_url)
                async with client.stream(
                    "GET",
                    current_url,
                    headers={
                        "Accept": "text/html,text/plain;q=0.9",
                        "User-Agent": "Agent-Studio-Knowledge/1.0",
                    },
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise KnowledgeConnectorError("Web source redirect has no location")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if media_type not in {"text/html", "text/plain"}:
                        raise KnowledgeConnectorError(
                            f"unsupported Web source media type: {media_type or 'unknown'}"
                        )
                    declared_length = response.headers.get("content-length")
                    if (
                        declared_length is not None
                        and declared_length.isdigit()
                        and int(declared_length) > config.max_bytes
                    ):
                        raise KnowledgeConnectorError("Web source exceeds configured byte limit")
                    parts: list[bytes] = []
                    bytes_read = 0
                    async for part in response.aiter_bytes():
                        bytes_read += len(part)
                        if bytes_read > config.max_bytes:
                            raise KnowledgeConnectorError(
                                "Web source exceeds configured byte limit"
                            )
                        parts.append(part)
                    raw = b"".join(parts)
                    response_headers = response.headers
                    response_encoding = response.encoding
                    break
            else:
                raise KnowledgeConnectorError("Web source exceeded redirect limit")
            assert raw is not None
            assert response_headers is not None
            media_type = response_headers.get("content-type", "").split(";", 1)[0].lower()
            try:
                body = raw.decode(response_encoding or "utf-8")
            except UnicodeDecodeError as error:
                raise KnowledgeConnectorError("Web source is not valid text") from error
            title = config.title or current_url
            if media_type == "text/html":
                extractor = _TextExtractor()
                extractor.feed(body)
                body = extractor.text()
                title = config.title or extractor.title or current_url
            else:
                body = body.strip()
            if not body:
                raise KnowledgeConnectorError("Web source produced no readable text")
            document_id = hashlib.sha256(current_url.encode()).hexdigest()[:32]
            document = ConnectorDocument(
                documentId=document_id,
                title=title,
                content=body,
                sourceUri=current_url,
                updatedAt=datetime.now(UTC),
            )
            content_hash = _documents_hash((document,))
            result_checkpoint: dict[str, str | int] = {
                "contentHash": content_hash,
                "url": current_url,
                "documentCount": 1,
            }
            etag = response_headers.get("etag")
            last_modified = response_headers.get("last-modified")
            if etag:
                result_checkpoint["etag"] = etag
            if last_modified:
                result_checkpoint["lastModified"] = last_modified
            return ConnectorSyncResult(
                documents=(document,),
                checkpoint=result_checkpoint,
            )
        except httpx.HTTPError as error:
            raise KnowledgeConnectorError(
                f"Web source request failed: {type(error).__name__}"
            ) from error
        finally:
            if owns_client:
                await client.aclose()


class KnowledgeConnectorRegistry:
    def __init__(
        self,
        connectors: Mapping[KnowledgeSourceKind, KnowledgeConnector] | None = None,
    ) -> None:
        self._connectors = dict(
            connectors
            or {
                KnowledgeSourceKind.FILE: FileKnowledgeConnector(),
                KnowledgeSourceKind.WEB: WebKnowledgeConnector(),
            }
        )

    def resolve(self, kind: KnowledgeSourceKind) -> KnowledgeConnector:
        try:
            return self._connectors[kind]
        except KeyError as error:
            raise KnowledgeConnectorError(
                f"knowledge connector is not registered: {kind.value}"
            ) from error
