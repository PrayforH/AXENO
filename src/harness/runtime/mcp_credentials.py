"""Request-scoped MCP credential resolution and boundary redaction."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Protocol, cast

from pydantic import SecretStr

from harness.core.models import ExecutionIdentity


class McpCredentialError(ValueError):
    """Raised before SDK execution when required MCP credentials are unavailable."""


type CredentialScope = tuple[str, str, str, str]
type CredentialValues = Mapping[str, SecretStr]


class DynamicMcpCredentialProvider(Protocol):
    async def resolve(
        self,
        server_reference: str,
        identity: ExecutionIdentity,
        required_keys: frozenset[str],
    ) -> CredentialValues: ...


def _missing(server_reference: str, keys: frozenset[str]) -> McpCredentialError:
    names = ", ".join(f"{server_reference}.{key}" for key in sorted(keys))
    return McpCredentialError(f"missing MCP credentials: {names}")


class EmptyMcpCredentialProvider:
    async def resolve(
        self,
        server_reference: str,
        identity: ExecutionIdentity,
        required_keys: frozenset[str],
    ) -> CredentialValues:
        del identity
        if required_keys:
            raise _missing(server_reference, required_keys)
        return MappingProxyType({})


class RequestMcpCredentialProvider:
    """Credential envelope already authenticated and scoped by the API boundary."""

    def __init__(
        self,
        credentials: Mapping[
            CredentialScope, Mapping[str, Mapping[str, SecretStr]]
        ],
    ) -> None:
        self._credentials = {
            scope: {
                server: MappingProxyType(dict(values))
                for server, values in servers.items()
            }
            for scope, servers in credentials.items()
        }

    @staticmethod
    def scope(identity: ExecutionIdentity) -> CredentialScope:
        return (
            identity.tenant_id,
            identity.user_id,
            identity.project_id,
            identity.run_id,
        )

    async def resolve(
        self,
        server_reference: str,
        identity: ExecutionIdentity,
        required_keys: frozenset[str],
    ) -> CredentialValues:
        values = self._credentials.get(self.scope(identity), {}).get(
            server_reference, MappingProxyType({})
        )
        missing = required_keys.difference(values)
        if missing:
            raise _missing(server_reference, frozenset(missing))
        return values


class ServerSecretReferenceProvider:
    """Resolve logical secret references from a server-owned secret envelope."""

    def __init__(
        self,
        *,
        references: Mapping[str, Mapping[str, str]],
        secrets: Mapping[str, SecretStr],
    ) -> None:
        self._references = {
            server: MappingProxyType(dict(values))
            for server, values in references.items()
        }
        self._secrets = MappingProxyType(dict(secrets))

    async def resolve(
        self,
        server_reference: str,
        identity: ExecutionIdentity,
        required_keys: frozenset[str],
    ) -> CredentialValues:
        del identity
        references = self._references.get(server_reference, MappingProxyType({}))
        resolved = {
            key: secret
            for key, secret_ref in references.items()
            if (secret := self._secrets.get(secret_ref)) is not None
        }
        missing = required_keys.difference(resolved)
        if missing:
            raise _missing(server_reference, frozenset(missing))
        return MappingProxyType(resolved)


def redact_mcp_credentials(
    value: Any,
    *,
    sensitive_names: frozenset[str],
    sensitive_values: frozenset[str],
) -> Any:
    """Remove resolved MCP credential material from SDK-derived payloads."""

    lowered_names = frozenset(name.lower() for name in sensitive_names)

    def redact(current: Any) -> Any:
        if isinstance(current, Mapping):
            mapping = cast(Mapping[object, Any], current)
            return {
                str(key): (
                    "[REDACTED]"
                    if str(key).lower() in lowered_names
                    else redact(child)
                )
                for key, child in mapping.items()
            }
        if isinstance(current, list):
            return [redact(child) for child in cast(list[Any], current)]
        if isinstance(current, tuple):
            return tuple(redact(child) for child in cast(tuple[Any, ...], current))
        if isinstance(current, str):
            redacted = current
            if redacted.lower() in lowered_names:
                return "[REDACTED]"
            for secret in sensitive_values:
                if secret:
                    redacted = redacted.replace(secret, "[REDACTED]")
            return redacted
        return current

    return redact(value)
