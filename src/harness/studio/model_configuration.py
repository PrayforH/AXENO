"""Tenant model connections managed from the Studio control plane.

The capability catalog stores non-secret routing metadata. API keys reuse the
encrypted credential repository under a tenant-owned principal and are never
included in API responses, logs, manifests, or task input.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr

from harness.core.errors import ConflictError, NotFoundError
from harness.core.models import ModelCompatibility
from harness.runtime.cc_switch import CcSwitchClaudeConfig
from harness.studio.catalog_service import CapabilityCatalogService
from harness.studio.mcp_credential_store import (
    McpCredentialService,
    StoredMcpCredential,
)
from harness.studio.models import (
    CapabilityCatalogRecord,
    ModelRouteCapability,
    ReplaceCapabilityCatalogRequest,
    StudioModel,
    UpsertCatalogResourceRequest,
)

_MODEL_CREDENTIAL_OWNER = "tenant:model-control-plane"
_MODEL_IMPORT_ACTOR = "system:model-control-plane-import"
_API_KEY = "api_key"


class ConfigureModelRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    label: str = Field(min_length=1, max_length=160)
    model_type: Literal["chat", "vision", "image_generation", "video_generation"] = Field(
        alias="modelType"
    )
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=300)
    base_url: str = Field(alias="baseUrl", min_length=1, max_length=2048)
    api_format: Literal[
        "anthropic_compatible", "openai_compatible", "openai_images", "openai_videos"
    ] = Field(alias="apiFormat")
    auth_scheme: Literal["bearer", "x-api-key", "none"] = Field(alias="authScheme")
    api_key: SecretStr | None = Field(default=None, alias="apiKey", min_length=1, max_length=16_384)
    enabled: bool = True


class ModelConfiguration(StudioModel):
    route_id: str = Field(alias="routeId")
    label: str
    model_type: Literal["chat", "vision", "image_generation", "video_generation"] = Field(
        alias="modelType"
    )
    provider: str
    model: str
    base_url: str | None = Field(alias="baseUrl")
    api_format: Literal[
        "anthropic_compatible", "openai_compatible", "openai_images", "openai_videos"
    ] = Field(alias="apiFormat")
    auth_scheme: Literal["bearer", "x-api-key", "none"] = Field(alias="authScheme")
    capabilities: tuple[str, ...]
    enabled: bool
    credential_configured: bool = Field(alias="credentialConfigured")
    deletable: bool
    version: int


class ModelConfigurationList(StudioModel):
    revision: int
    models: tuple[ModelConfiguration, ...]
    agent_model_bindings: dict[str, str] = Field(alias="agentModelBindings")


class BindAgentModelRequest(StudioModel):
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    route_id: str = Field(alias="routeId", pattern=r"^[a-z][a-z0-9-]*$")


class ModelConnectionTestResult(StudioModel):
    ok: bool
    latency_ms: int = Field(alias="latencyMs", ge=0)
    message: str


class GenerateImageRequest(StudioModel):
    prompt: str = Field(min_length=1, max_length=8_000)
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1024x1024"
    quality: Literal["standard", "high"] = "standard"
    count: int = Field(default=1, ge=1, le=4)


class GeneratedImage(StudioModel):
    url: str | None = None
    b64_json: str | None = Field(default=None, alias="b64Json")
    revised_prompt: str | None = Field(default=None, alias="revisedPrompt")


class GenerateImageResult(StudioModel):
    model: str
    images: tuple[GeneratedImage, ...]


class GenerateVideoRequest(StudioModel):
    prompt: str = Field(min_length=1, max_length=8_000)
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = Field(default="16:9", alias="aspectRatio")
    seconds: int = Field(default=5, ge=1, le=10)
    seed: int | None = Field(default=None, ge=0)


@dataclass(frozen=True, slots=True)
class GeneratedVideo:
    content: bytes
    media_type: str
    request_id: str | None
    inference_time_seconds: str | None


_MAX_GENERATED_VIDEO_BYTES = 128 * 1024 * 1024


class ModelConfigurationService:
    def __init__(
        self,
        catalogs: CapabilityCatalogService,
        credentials: McpCredentialService,
        *,
        environment: str = "local",
        server_routes: Iterable[CcSwitchClaudeConfig] = (),
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._catalogs = catalogs
        self._credentials = credentials
        self._environment = environment
        self._server_routes = {
            route.route_id: route for route in server_routes if route.route_id is not None
        }
        self._http_client = http_client

    async def list(self, tenant_id: str) -> ModelConfigurationList:
        record = await self._import_server_models(tenant_id)
        stored = {
            item.reference
            for item in await self._credentials.repository.list_for_user(
                tenant_id, _MODEL_CREDENTIAL_OWNER
            )
        }
        return ModelConfigurationList(
            revision=record.revision,
            models=tuple(
                ModelConfiguration(
                    routeId=route.route_id,
                    label=route.label,
                    modelType=route.model_type,
                    provider=route.provider,
                    model=route.models[0],
                    baseUrl=route.base_url,
                    apiFormat=route.api_format,
                    authScheme=route.auth_scheme,
                    capabilities=route.capabilities,
                    enabled=route.enabled,
                    credentialConfigured=(route.auth_scheme == "none" or route.route_id in stored),
                    deletable=True,
                    version=route.version,
                )
                for route in record.catalog.model_routes
            ),
            agentModelBindings=dict(record.catalog.agent_model_bindings),
        )

    async def configure(
        self,
        tenant_id: str,
        user_id: str,
        route_id: str,
        request: ConfigureModelRequest,
    ) -> ModelConfigurationList:
        record = await self._import_server_models(tenant_id)
        if record.revision != request.expected_revision:
            raise ConflictError("model catalog revision changed; reload before saving")
        self._validate_endpoint(request.base_url)
        current = next(
            (route for route in record.catalog.model_routes if route.route_id == route_id),
            None,
        )
        credential = await self._credentials.repository.get(
            tenant_id, _MODEL_CREDENTIAL_OWNER, route_id
        )
        if request.auth_scheme == "none" and request.api_key is not None:
            raise ConflictError("API keys cannot be stored for an unauthenticated model")
        if request.auth_scheme != "none" and request.api_key is None and credential is None:
            raise ConflictError("an API key is required when creating a model connection")
        capabilities = {
            "chat": ("streaming", "tool_use"),
            "vision": ("streaming", "tool_use", "vision"),
            "image_generation": ("image_generation",),
            "video_generation": ("video_generation",),
        }[request.model_type]
        route = ModelRouteCapability(
            routeId=route_id,
            label=request.label.strip(),
            modelType=request.model_type,
            provider=request.provider.strip(),
            models=(request.model.strip(),),
            baseUrl=request.base_url.rstrip("/"),
            apiFormat=request.api_format,
            authScheme=request.auth_scheme,
            capabilities=capabilities,
            credentialManaged=True,
            credentialReference=None,
            version=(current.version + 1 if current is not None else 1),
            enabled=request.enabled,
        )
        await self._catalogs.upsert(
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="modelRoute",
            resource_id=route_id,
            request=UpsertCatalogResourceRequest(
                expectedRevision=record.revision,
                resource=route,
            ),
        )
        if request.api_key is not None:
            await self._store_secret(tenant_id, user_id, route_id, request.api_key)
        elif request.auth_scheme == "none" and credential is not None:
            await self._credentials.repository.delete(tenant_id, _MODEL_CREDENTIAL_OWNER, route_id)
        return await self.list(tenant_id)

    async def disable(
        self,
        tenant_id: str,
        user_id: str,
        route_id: str,
        expected_revision: int,
    ) -> ModelConfigurationList:
        await self._catalogs.disable(
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type="modelRoute",
            resource_id=route_id,
            expected_revision=expected_revision,
        )
        return await self.list(tenant_id)

    async def delete(
        self,
        tenant_id: str,
        user_id: str,
        route_id: str,
        expected_revision: int,
    ) -> ModelConfigurationList:
        """Permanently remove a user-created route and its stored credential."""

        await self._catalogs.delete_model(
            tenant_id=tenant_id,
            user_id=user_id,
            resource_id=route_id,
            expected_revision=expected_revision,
        )
        await self._credentials.repository.delete(tenant_id, _MODEL_CREDENTIAL_OWNER, route_id)
        if self._credentials.audit is not None:
            await self._credentials.audit.record(
                tenant_id=tenant_id,
                user_id=user_id,
                action="studio.model_configuration.delete",
                resource_type="model_route",
                resource_id=route_id,
                details={},
            )
        return await self.list(tenant_id)

    async def bind_agent(
        self,
        tenant_id: str,
        user_id: str,
        agent_name: str,
        request: BindAgentModelRequest,
    ) -> ModelConfigurationList:
        record = await self._import_server_models(tenant_id)
        route = next(
            (item for item in record.catalog.model_routes if item.route_id == request.route_id),
            None,
        )
        if route is None or not route.enabled or route.model_type not in {"chat", "vision"}:
            raise ConflictError("Agent defaults require an enabled chat or vision model")
        bindings = dict(record.catalog.agent_model_bindings)
        bindings[agent_name] = request.route_id
        await self._catalogs.replace(
            tenant_id=tenant_id,
            user_id=user_id,
            request=ReplaceCapabilityCatalogRequest(
                expectedRevision=request.expected_revision,
                catalog=record.catalog.model_copy(update={"agent_model_bindings": bindings}),
            ),
        )
        return await self.list(tenant_id)

    async def resolve_runtime(
        self,
        tenant_id: str,
        agent_name: str,
        requested_route_id: str,
        *,
        apply_agent_binding: bool = True,
    ) -> CcSwitchClaudeConfig | None:
        record = await self._import_server_models(tenant_id)
        route_id = (
            record.catalog.agent_model_bindings.get(agent_name, requested_route_id)
            if apply_agent_binding
            else requested_route_id
        )
        route = next(
            (item for item in record.catalog.model_routes if item.route_id == route_id), None
        )
        if route is None or not route.enabled:
            return None
        if route.base_url is None or route.model_type not in {"chat", "vision"}:
            return None
        if route.auth_scheme == "none":
            return None
        secret = await self._secret(tenant_id, route_id)
        if secret is None:
            return None
        return CcSwitchClaudeConfig(
            route_id=route.route_id,
            base_url=self._runtime_sdk_base_url(route),
            model=route.models[0],
            provider=("anthropic" if route.auth_scheme == "x-api-key" else "new-api"),
            credential=secret,
            auth_scheme=route.auth_scheme,
            compatibility=ModelCompatibility.FULL,
            capabilities=frozenset(route.capabilities),
        )

    async def test(self, tenant_id: str, route_id: str) -> ModelConnectionTestResult:
        from time import monotonic

        route = await self._route(tenant_id, route_id)
        secret = await self._credential_for_route(tenant_id, route)
        started = monotonic()
        payload: dict[str, object]
        if route.model_type == "video_generation":
            try:
                response = await self._get(route, secret, "models")
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise ConflictError(
                    f"model provider rejected the test request (HTTP {error.response.status_code})"
                ) from None
            except httpx.HTTPError:
                raise ConflictError("model provider connection failed") from None
            return ModelConnectionTestResult(
                ok=True,
                latencyMs=int((monotonic() - started) * 1000),
                message="连接成功，视频服务已就绪。",
            )
        if route.model_type == "image_generation":
            payload = {
                "model": route.models[0],
                "prompt": "A small green circle on a white background",
                "size": "1024x1024",
                "n": 1,
            }
            path = "images/generations"
        elif route.api_format == "openai_compatible":
            payload = {
                "model": route.models[0],
                "messages": [{"role": "user", "content": "Reply OK"}],
                "max_tokens": 2,
            }
            path = "chat/completions"
        else:
            payload = {
                "model": route.models[0],
                "messages": [{"role": "user", "content": "Reply OK"}],
                "max_tokens": 2,
            }
            path = "messages"
        try:
            response = await self._post(route, secret, path, payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise ConflictError(
                f"model provider rejected the test request (HTTP {error.response.status_code})"
            ) from None
        except httpx.HTTPError:
            raise ConflictError("model provider connection failed") from None
        return ModelConnectionTestResult(
            ok=True,
            latencyMs=int((monotonic() - started) * 1000),
            message="连接成功，服务已返回有效响应。",
        )

    async def generate_image(
        self, tenant_id: str, route_id: str, request: GenerateImageRequest
    ) -> GenerateImageResult:
        route = await self._route(tenant_id, route_id)
        if route.model_type != "image_generation" or not route.enabled:
            raise ConflictError("the selected route is not an enabled image generation model")
        secret = await self._credential_for_route(tenant_id, route)
        try:
            response = await self._post(
                route,
                secret,
                "images/generations",
                {
                    "model": route.models[0],
                    "prompt": request.prompt,
                    "size": request.size,
                    "quality": request.quality,
                    "n": request.count,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise ConflictError(
                f"image provider rejected the request (HTTP {error.response.status_code})"
            ) from None
        except httpx.HTTPError:
            raise ConflictError("image provider connection failed") from None
        raw = cast(object, response.json())
        if not isinstance(raw, dict):
            raise ConflictError("image provider returned an invalid response")
        raw_values = cast(dict[object, object], raw)
        data = raw_values.get("data")
        if not isinstance(data, list):
            raise ConflictError("image provider returned an invalid response")
        images: list[GeneratedImage] = []
        for item in cast(list[object], data):
            if not isinstance(item, dict):
                continue
            values = cast(dict[str, object], item)
            raw_url = values.get("url")
            raw_b64 = values.get("b64_json")
            raw_revised_prompt = values.get("revised_prompt")
            images.append(
                GeneratedImage(
                    url=raw_url if isinstance(raw_url, str) else None,
                    b64Json=raw_b64 if isinstance(raw_b64, str) else None,
                    revisedPrompt=(
                        raw_revised_prompt if isinstance(raw_revised_prompt, str) else None
                    ),
                )
            )
        if not images:
            raise ConflictError("image provider returned no images")
        return GenerateImageResult(model=route.models[0], images=tuple(images))

    async def generate_video(
        self, tenant_id: str, route_id: str, request: GenerateVideoRequest
    ) -> GeneratedVideo:
        route = await self._route(tenant_id, route_id)
        if route.model_type != "video_generation" or not route.enabled:
            raise ConflictError("the selected route is not an enabled video generation model")
        secret = await self._credential_for_route(tenant_id, route)
        form: dict[str, str] = {
            "model": route.models[0],
            "prompt": request.prompt,
            "aspect_ratio": request.aspect_ratio,
            "seconds": str(request.seconds),
        }
        if request.seed is not None:
            form["seed"] = str(request.seed)
        try:
            response = await self._post_multipart(route, secret, "videos/sync", form)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise ConflictError(
                f"video provider rejected the request (HTTP {error.response.status_code})"
            ) from None
        except httpx.HTTPError:
            raise ConflictError("video provider connection failed") from None
        media_type = response.headers.get("content-type", "").partition(";")[0].strip()
        if (
            media_type != "video/mp4"
            or len(response.content) < 12
            or response.content[4:8] != b"ftyp"
        ):
            raise ConflictError("video provider returned an invalid MP4 response")
        if len(response.content) > _MAX_GENERATED_VIDEO_BYTES:
            raise ConflictError("video provider response exceeds the 128 MiB limit")
        return GeneratedVideo(
            content=response.content,
            media_type=media_type,
            request_id=response.headers.get("x-request-id"),
            inference_time_seconds=response.headers.get("x-inference-time-s"),
        )

    async def _route(self, tenant_id: str, route_id: str) -> ModelRouteCapability:
        record = await self._import_server_models(tenant_id)
        route = next(
            (item for item in record.catalog.model_routes if item.route_id == route_id), None
        )
        if route is None:
            raise NotFoundError(f"configured model not found: {route_id}")
        if route.base_url is None:
            raise NotFoundError(f"configured model not found: {route_id}")
        self._validate_endpoint(route.base_url)
        return route

    async def _store_secret(
        self, tenant_id: str, user_id: str, route_id: str, api_key: SecretStr
    ) -> None:
        now = datetime.now(UTC)
        await self._credentials.repository.upsert(
            StoredMcpCredential(
                tenant_id=tenant_id,
                owner_user_id=_MODEL_CREDENTIAL_OWNER,
                reference=route_id,
                revision=1,
                key_names=(_API_KEY,),
                ciphertext=self._credentials.cipher.encrypt(
                    tenant_id,
                    _MODEL_CREDENTIAL_OWNER,
                    route_id,
                    {_API_KEY: api_key},
                ),
                updated_by=user_id,
                updated_at=now,
            )
        )
        if self._credentials.audit is not None:
            await self._credentials.audit.record(
                tenant_id=tenant_id,
                user_id=user_id,
                action="studio.model_credential.configure",
                resource_type="model_credential",
                resource_id=route_id,
                details={"keys": [_API_KEY]},
            )

    async def _secret(self, tenant_id: str, route_id: str) -> SecretStr | None:
        stored = await self._credentials.repository.get(
            tenant_id, _MODEL_CREDENTIAL_OWNER, route_id
        )
        if stored is not None:
            return self._credentials.cipher.decrypt(stored).get(_API_KEY)
        return None

    async def _import_server_models(self, tenant_id: str) -> CapabilityCatalogRecord:
        """One-time import from deployment settings into the frontend control plane."""

        record = await self._catalogs.get(tenant_id)
        if not self._server_routes:
            return record
        stored = {
            item.reference
            for item in await self._credentials.repository.list_for_user(
                tenant_id, _MODEL_CREDENTIAL_OWNER
            )
        }
        changed = False
        imported_routes: list[ModelRouteCapability] = []
        for route in record.catalog.model_routes:
            server = self._server_routes.get(route.route_id)
            if server is None:
                imported_routes.append(route)
                continue
            if route.route_id not in stored:
                await self._store_secret(
                    tenant_id,
                    _MODEL_IMPORT_ACTOR,
                    route.route_id,
                    server.credential,
                )
            if route.base_url is None:
                route = route.model_copy(
                    update={
                        "models": (server.model,),
                        "capabilities": tuple(sorted(server.capabilities)),
                        "model_type": self._server_model_type(server),
                        "base_url": self._server_direct_base_url(server),
                        "api_format": "anthropic_compatible",
                        "auth_scheme": server.resolved_auth_scheme,
                        "version": route.version + 1,
                    }
                )
                changed = True
            imported_routes.append(route)
        if not changed:
            return record
        try:
            return await self._catalogs.replace(
                tenant_id=tenant_id,
                user_id=_MODEL_IMPORT_ACTOR,
                request=ReplaceCapabilityCatalogRequest(
                    expectedRevision=record.revision,
                    catalog=record.catalog.model_copy(
                        update={"model_routes": tuple(imported_routes)}
                    ),
                ),
            )
        except ConflictError:
            # Another API/worker process completed the same idempotent import.
            return await self._catalogs.get(tenant_id)

    @staticmethod
    def _server_model_type(
        route: CcSwitchClaudeConfig,
    ) -> Literal["chat", "vision", "image_generation", "video_generation"]:
        return "vision" if "vision" in route.capabilities else "chat"

    @staticmethod
    def _server_direct_base_url(
        route: CcSwitchClaudeConfig,
    ) -> str:
        base_url = route.base_url.rstrip("/")
        # Deployment settings are SDK base URLs; Anthropic-compatible SDKs
        # append /v1/messages themselves. The control-plane probe uses raw
        # HTTP, so expose the complete API base before appending /messages.
        if not base_url.endswith("/v1"):
            return f"{base_url}/v1"
        return base_url

    @staticmethod
    def _runtime_sdk_base_url(route: ModelRouteCapability) -> str:
        assert route.base_url is not None
        base_url = route.base_url.rstrip("/")
        # The model catalog stores the complete direct API base so connection
        # tests can call /messages. Claude Code expects the provider root and
        # appends /v1/messages itself. Passing the catalog URL through unchanged
        # therefore produces /v1/v1/messages and a misleading model-not-found
        # 404 for Anthropic-compatible routes.
        if route.api_format == "anthropic_compatible" and base_url.endswith("/v1"):
            return base_url[:-3]
        return base_url

    async def _require_secret(self, tenant_id: str, route_id: str) -> SecretStr:
        secret = await self._secret(tenant_id, route_id)
        if secret is None:
            raise ConflictError(f"credentials are not configured for model: {route_id}")
        return secret

    async def _credential_for_route(
        self, tenant_id: str, route: ModelRouteCapability
    ) -> SecretStr | None:
        if route.auth_scheme == "none":
            return None
        return await self._require_secret(tenant_id, route.route_id)

    @staticmethod
    def _headers(route: ModelRouteCapability, secret: SecretStr | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if route.api_format == "anthropic_compatible":
            headers["anthropic-version"] = "2023-06-01"
        if route.auth_scheme == "x-api-key":
            if secret is None:
                raise ConflictError(f"credentials are not configured for model: {route.route_id}")
            headers["x-api-key"] = secret.get_secret_value()
        elif route.auth_scheme == "bearer":
            if secret is None:
                raise ConflictError(f"credentials are not configured for model: {route.route_id}")
            headers["authorization"] = f"Bearer {secret.get_secret_value()}"
        return headers

    async def _post(
        self,
        route: ModelRouteCapability,
        secret: SecretStr | None,
        path: str,
        payload: dict[str, object],
    ) -> httpx.Response:
        assert route.base_url is not None
        headers = {"content-type": "application/json", **self._headers(route, secret)}
        client = self._http_client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        try:
            return await client.post(
                f"{route.base_url.rstrip('/')}/{path}",
                headers=headers,
                json=payload,
            )
        finally:
            if self._http_client is None:
                await client.aclose()

    async def _get(
        self,
        route: ModelRouteCapability,
        secret: SecretStr | None,
        path: str,
    ) -> httpx.Response:
        assert route.base_url is not None
        client = self._http_client or httpx.AsyncClient(timeout=15.0, follow_redirects=False)
        try:
            return await client.get(
                f"{route.base_url.rstrip('/')}/{path}",
                headers=self._headers(route, secret),
            )
        finally:
            if self._http_client is None:
                await client.aclose()

    async def _post_multipart(
        self,
        route: ModelRouteCapability,
        secret: SecretStr | None,
        path: str,
        form: dict[str, str],
    ) -> httpx.Response:
        assert route.base_url is not None
        client = self._http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(900.0, connect=15.0),
            follow_redirects=False,
        )
        try:
            return await client.post(
                f"{route.base_url.rstrip('/')}/{path}",
                headers=self._headers(route, secret),
                files={name: (None, value) for name, value in form.items()},
            )
        finally:
            if self._http_client is None:
                await client.aclose()

    def _validate_endpoint(self, value: str) -> None:
        normalized = value.rstrip("/")
        if normalized in {
            self._server_direct_base_url(route) for route in self._server_routes.values()
        }:
            return
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ConflictError("model Base URL must use HTTP or HTTPS")
        if parsed.hostname is None:
            raise ConflictError("model Base URL must include a hostname")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            if self._environment == "production" and parsed.scheme != "https":
                raise ConflictError("production public model connections require HTTPS") from None
            return
        if self._environment != "production":
            return
        if address.is_loopback or address.is_link_local or address.is_unspecified:
            raise ConflictError(
                "production model connections cannot target loopback or link-local addresses"
            )
        # Model catalog administration is permission-gated and is also the source
        # of truth for on-premise providers. RFC1918 endpoints therefore need to
        # remain configurable without a legacy deployment-environment exception.
        if address.is_private:
            return
        if parsed.scheme != "https":
            raise ConflictError("production public model connections require HTTPS")
