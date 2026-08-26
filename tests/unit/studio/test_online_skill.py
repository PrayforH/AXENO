from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from harness.studio.online_skill import OnlineSkillError, fetch_online_skill
from harness.studio.skill_import import import_skill


def _skill_markdown(name: str = "office-docs") -> bytes:
    return (
        f"---\nname: {name}\ndescription: Build Office documents.\n---\n"
        "Create the requested document and verify the output.\n"
    ).encode()


def _repository_archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("skills-main/skills/office/SKILL.md", _skill_markdown())
        archive.writestr("skills-main/skills/office/scripts/build.py", "print('ok')\n")
        archive.writestr("skills-main/skills/other/SKILL.md", _skill_markdown("other"))
    return output.getvalue()


@pytest.mark.asyncio
async def test_fetches_github_blob_as_raw_skill() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=_skill_markdown(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await fetch_online_skill(
            "https://github.com/acme/skills/blob/main/office/SKILL.md",
            http_client=client,
        )

    assert seen == ["https://raw.githubusercontent.com/acme/skills/main/office/SKILL.md"]
    assert payload.filename == "SKILL.md"
    assert import_skill(payload.content, filename=payload.filename).skill.name == "office-docs"


@pytest.mark.asyncio
async def test_fetches_only_selected_github_skill_directory() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ("https://codeload.github.com/openai/skills/zip/refs/heads/main")
        return httpx.Response(200, content=_repository_archive(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await fetch_online_skill(
            "https://github.com/openai/skills/tree/main/skills/office",
            http_client=client,
        )

    imported = import_skill(payload.content, filename=payload.filename)
    assert imported.skill.name == "office-docs"
    assert [file.path for file in imported.skill.files] == ["scripts/build.py"]
    assert imported.risk_level == "review"


@pytest.mark.asyncio
async def test_rejects_non_github_online_skill_source() -> None:
    with pytest.raises(OnlineSkillError, match="当前仅支持"):
        await fetch_online_skill("https://example.com/SKILL.md")
