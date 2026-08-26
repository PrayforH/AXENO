"""Download public Agent Skills into a design-time, reviewable snapshot."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import httpx

from harness.studio.skill_import import MAX_SKILL_UPLOAD_BYTES

_GITHUB_HOST = "github.com"
_RAW_GITHUB_HOST = "raw.githubusercontent.com"
_CODELOAD_GITHUB_HOST = "codeload.github.com"
_MAX_REDIRECTS = 3
_MAX_SELECTED_FILES = 20_000
_MAX_SELECTED_UNPACKED_BYTES = 256 * 1024 * 1024
_SAFE_GITHUB_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


class OnlineSkillError(ValueError):
    """An online Skill source is unsupported, unreachable, or unsafe."""


@dataclass(frozen=True)
class OnlineSkillPayload:
    content: bytes
    filename: str
    source_url: str


@dataclass(frozen=True)
class _ResolvedSource:
    download_url: str
    filename: str
    tree_path: str | None = None


def _validated_url(value: str) -> tuple[str, str, tuple[str, ...]]:
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise OnlineSkillError("在线 Skill 仅支持无账号信息的 HTTPS GitHub 地址")
    try:
        port = parsed.port
    except ValueError as error:
        raise OnlineSkillError("在线 Skill 地址端口无效") from error
    if port not in {None, 443}:
        raise OnlineSkillError("在线 Skill 地址只允许 HTTPS 默认端口")
    path = unquote(parsed.path)
    parts = tuple(part for part in path.split("/") if part)
    if any(part in {".", ".."} or "\\" in part for part in parts):
        raise OnlineSkillError("在线 Skill 地址包含不安全路径")
    return host, path, parts


def _github_part(value: str, label: str) -> str:
    if not _SAFE_GITHUB_PART.fullmatch(value):
        raise OnlineSkillError(f"GitHub {label}格式无效")
    return value


def _resolve_source(value: str) -> _ResolvedSource:
    host, path, parts = _validated_url(value)
    if host == _RAW_GITHUB_HOST:
        if len(parts) < 5:
            raise OnlineSkillError("raw GitHub 地址必须指向具体 SKILL.md 或 ZIP")
        filename = PurePosixPath(path).name
        return _ResolvedSource(value.strip(), filename)
    if host == _CODELOAD_GITHUB_HOST:
        if not path.lower().endswith(".zip") and "/zip/" not in path.lower():
            raise OnlineSkillError("codeload 地址必须指向 ZIP")
        return _ResolvedSource(value.strip(), "skill.zip")
    if host != _GITHUB_HOST:
        raise OnlineSkillError(
            "当前仅支持 github.com、raw.githubusercontent.com 与 codeload.github.com"
        )
    if len(parts) < 2:
        raise OnlineSkillError("GitHub 地址必须包含 owner/repository")
    owner = _github_part(parts[0], "owner")
    repository = _github_part(parts[1].removesuffix(".git"), "repository")
    if len(parts) >= 5 and parts[2] in {"blob", "raw"}:
        ref = _github_part(parts[3], "分支或标签")
        file_path = "/".join(parts[4:])
        raw_url = urlunsplit(
            (
                "https",
                _RAW_GITHUB_HOST,
                f"/{quote(owner)}/{quote(repository)}/{quote(ref)}/{quote(file_path, safe='/')}",
                "",
                "",
            )
        )
        return _ResolvedSource(raw_url, PurePosixPath(file_path).name)
    if len(parts) >= 4 and parts[2] == "tree":
        ref = _github_part(parts[3], "分支或标签")
        tree_path = "/".join(parts[4:]).strip("/")
        archive_url = (
            f"https://{_CODELOAD_GITHUB_HOST}/{quote(owner)}/{quote(repository)}"
            f"/zip/refs/heads/{quote(ref)}"
        )
        filename = f"{PurePosixPath(tree_path).name or repository}.zip"
        return _ResolvedSource(archive_url, filename, tree_path)
    if len(parts) == 6 and parts[2:5] == ("archive", "refs", "heads"):
        ref = parts[5].removesuffix(".zip")
        _github_part(ref, "分支")
        archive_url = (
            f"https://{_CODELOAD_GITHUB_HOST}/{quote(owner)}/{quote(repository)}"
            f"/zip/refs/heads/{quote(ref)}"
        )
        return _ResolvedSource(archive_url, f"{repository}.zip")
    raise OnlineSkillError(
        "请粘贴 GitHub Skill 目录（/tree/…）、具体 SKILL.md（/blob/…）或 ZIP 地址"
    )


def _redirect_allowed(value: str) -> bool:
    try:
        host, _, _ = _validated_url(value)
    except OnlineSkillError:
        return False
    return host in {_GITHUB_HOST, _RAW_GITHUB_HOST, _CODELOAD_GITHUB_HOST} or host.endswith(
        ".githubusercontent.com"
    )


async def _download(client: httpx.AsyncClient, value: str) -> tuple[bytes, str]:
    current = value
    for _ in range(_MAX_REDIRECTS + 1):
        async with client.stream(
            "GET",
            current,
            headers={
                "Accept": "application/zip, text/markdown, text/plain;q=0.9",
                "User-Agent": "agent-studio-skill-installer/1.0",
            },
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise OnlineSkillError("在线 Skill 下载重定向缺少目标地址")
                redirected = urljoin(current, location)
                if not _redirect_allowed(redirected):
                    raise OnlineSkillError("在线 Skill 下载被重定向到非受信任地址")
                current = redirected
                continue
            if response.status_code == 404:
                raise OnlineSkillError("在线 Skill 地址不存在；请检查分支和目录")
            if response.status_code >= 400:
                raise OnlineSkillError(f"在线 Skill 下载失败（HTTP {response.status_code}）")
            raw_length = response.headers.get("content-length")
            if raw_length:
                try:
                    content_length = int(raw_length)
                except ValueError:
                    content_length = -1
                if content_length < 0 or content_length > MAX_SKILL_UPLOAD_BYTES:
                    raise OnlineSkillError("在线 Skill 下载内容不能超过 100 MiB")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_SKILL_UPLOAD_BYTES:
                    raise OnlineSkillError("在线 Skill 下载内容不能超过 100 MiB")
            return bytes(content), current
    raise OnlineSkillError("在线 Skill 下载重定向次数过多")


def _select_tree_archive(content: bytes, tree_path: str) -> bytes:
    try:
        source = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as error:
        raise OnlineSkillError("GitHub Skill 目录下载结果不是有效 ZIP") from error
    requested = PurePosixPath(tree_path) if tree_path else PurePosixPath()
    with source:
        files = [item for item in source.infolist() if not item.is_dir()]
        if not files:
            raise OnlineSkillError("GitHub Skill 目录为空")
        repository_root = PurePosixPath(files[0].filename).parts[0]
        prefix_path = PurePosixPath(repository_root) / requested
        prefix = prefix_path.as_posix().rstrip("/") + "/"
        selected = [item for item in files if item.filename.startswith(prefix)]
        exact_skill = f"{prefix}SKILL.md"
        if not any(item.filename == exact_skill for item in selected):
            raise OnlineSkillError("所选 GitHub 目录根部没有 SKILL.md")
        if len(selected) > _MAX_SELECTED_FILES:
            raise OnlineSkillError("所选 GitHub Skill 文件数量超过 20000")
        unpacked_size = sum(item.file_size for item in selected)
        if unpacked_size > _MAX_SELECTED_UNPACKED_BYTES:
            raise OnlineSkillError("所选 GitHub Skill 解压后超过 256 MiB")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for item in selected:
                relative = item.filename.removeprefix(prefix)
                if relative:
                    target.writestr(relative, source.read(item))
        payload = output.getvalue()
    if len(payload) > MAX_SKILL_UPLOAD_BYTES:
        raise OnlineSkillError("所选 GitHub Skill 打包后超过 100 MiB")
    return payload


async def fetch_online_skill(
    source_url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> OnlineSkillPayload:
    """Fetch a public GitHub Skill without executing any downloaded content."""

    resolved = _resolve_source(source_url)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        follow_redirects=False,
        trust_env=False,
    )
    try:
        content, final_url = await _download(client, resolved.download_url)
    except httpx.HTTPError as error:
        raise OnlineSkillError("在线 Skill 下载失败，请检查网络或稍后重试") from error
    finally:
        if owns_client:
            await client.aclose()
    if resolved.tree_path is not None:
        content = _select_tree_archive(content, resolved.tree_path)
    if not content:
        raise OnlineSkillError("在线 Skill 下载内容为空")
    return OnlineSkillPayload(
        content=content,
        filename=resolved.filename,
        source_url=final_url,
    )
