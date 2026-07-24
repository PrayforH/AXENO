from io import BytesIO
from zipfile import ZipFile

import pytest

from harness.studio.skill_import import (
    MAX_SKILL_UPLOAD_BYTES,
    SkillImportError,
    import_skill,
)


def skill_zip(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def binary_skill_zip(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def test_imports_a_declarative_skill_as_low_risk() -> None:
    imported = import_skill(
        skill_zip(
            {
                "research/SKILL.md": (
                    "---\n"
                    "name: source-research\n"
                    "description: Research with cited sources.\n"
                    "---\n\n"
                    "# Workflow\n\nFind, compare, and cite primary sources.\n"
                ),
                "research/references/checklist.md": "Check dates and original sources.\n",
            }
        ),
        filename="research.zip",
    )

    assert imported.skill.name == "source-research"
    assert imported.risk_level == "low"
    assert imported.skill.files[0].path == "references/checklist.md"
    assert imported.findings == ()
    assert len(imported.source_content_hash) == 64


def test_imports_scripts_but_marks_them_for_review() -> None:
    imported = import_skill(
        skill_zip(
            {
                "ppt/SKILL.md": (
                    "---\nname: ppt-builder\ndescription: Build slides.\n---\n\n"
                    "Run the renderer and publish the deck.\n"
                ),
                "ppt/scripts/render.py": "print('render')\n",
                "ppt/requirements.txt": "python-pptx==1.0.2\n",
            }
        ),
        filename="ppt.zip",
    )

    assert imported.risk_level == "review"
    assert imported.findings == (
        "包含可执行脚本：scripts/render.py",
        "包含依赖声明：requirements.txt",
    )
    assert any("权限门" in warning for warning in imported.warnings)


def test_preserves_binary_assets_for_large_skill_packages() -> None:
    imported = import_skill(
        binary_skill_zip(
            {
                "ppt/SKILL.md": (
                    b"---\nname: ppt-builder\ndescription: Build slides.\n---\n\n"
                    b"Use the packaged visual assets.\n"
                ),
                "ppt/assets/template.png": b"\x89PNG\r\n\x1a\n\x00\xff",
            }
        ),
        filename="ppt.zip",
    )

    asset = imported.skill.files[0]
    assert MAX_SKILL_UPLOAD_BYTES == 100 * 1024 * 1024
    assert asset.path == "assets/template.png"
    assert asset.content is None
    assert asset.content_base64 is not None
    assert imported.warnings == ("已保留 1 个二进制 asset",)


def test_rejects_path_traversal_and_secret_files() -> None:
    with pytest.raises(SkillImportError, match="不安全路径"):
        import_skill(
            skill_zip(
                {
                    "safe/SKILL.md": (
                        "---\nname: safe-skill\ndescription: Safe.\n---\n\nDo work.\n"
                    ),
                    "../escape.txt": "escape",
                }
            ),
            filename="unsafe.zip",
        )

    with pytest.raises(SkillImportError, match="凭据类文件"):
        import_skill(
            skill_zip(
                {
                    "safe/SKILL.md": (
                        "---\nname: safe-skill\ndescription: Safe.\n---\n\nDo work.\n"
                    ),
                    "safe/.env": "TOKEN=secret",
                }
            ),
            filename="secret.zip",
        )


def test_imports_a_single_markdown_skill_and_normalizes_name() -> None:
    imported = import_skill(
        (
            b"---\nname: PPT Master\ndescription: Build a presentation.\n---\n\n"
            b"Create the requested deck.\n"
        ),
        filename="SKILL.md",
    )

    assert imported.skill.name == "ppt-master"
    assert imported.warnings == ("Skill 名称已规范化为 ppt-master",)
