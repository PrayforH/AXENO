"""Export an editable Studio Draft as a portable NexAU Agent archive."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import yaml

from harness.studio.models import AgentDraft, DraftPythonTool


@dataclass(frozen=True)
class NexauAgentArchive:
    content: bytes
    filename: str


_NEXAU_BUILTINS = {
    "Read": ("read_file", "nexau.archs.tool.builtin.file_tools:read_file"),
    "Write": ("write_file", "nexau.archs.tool.builtin.file_tools:write_file"),
    "Glob": ("list_directory", "nexau.archs.tool.builtin.file_tools:list_directory"),
    "Bash": ("run_shell_command", "nexau.archs.tool.builtin.shell_tools:run_shell_command"),
}


def _skill_markdown(name: str, description: str, instructions: str) -> str:
    frontmatter = yaml.safe_dump(
        {"name": name, "description": description},
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{instructions.strip()}\n"


def _python_module(tool: DraftPythonTool) -> str:
    return (
        f"{tool.code.rstrip()}\n\n"
        "_NEXAU_STUDIO_RUN = run\n\n"
        f"def {tool.name}(**arguments):\n"
        "    return _NEXAU_STUDIO_RUN(arguments)\n"
    )


def _write(archive: ZipFile, path: str, content: str | bytes) -> None:
    payload = content.encode("utf-8") if isinstance(content, str) else content
    info = ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, payload)


def export_nexau_agent(draft: AgentDraft) -> NexauAgentArchive:
    spec = draft.spec
    tools: list[dict[str, object]] = []
    for builtin in spec.builtin_tools:
        mapped = _NEXAU_BUILTINS.get(builtin)
        if mapped is not None:
            name, binding = mapped
            tools.append({"name": name, "binding": binding})
    for tool in spec.python_tools:
        tools.append(
            {
                "name": tool.name,
                "yaml_path": f"tools/{tool.name}.tool.yaml",
                "binding": f"custom_tools.{tool.name}:{tool.name}",
            }
        )

    config: dict[str, object] = {
        "type": "agent",
        "name": spec.name,
        "description": spec.description,
        "system_prompt": "./systemprompt.md",
        "llm_config": {"model": spec.model.model},
        "tools": tools,
        "skills": [f"./skills/{skill.name}" for skill in spec.skills],
    }
    if spec.limits.max_turns is not None:
        config["max_iterations"] = spec.limits.max_turns
    if spec.limits.max_model_tokens is not None:
        config["max_context_tokens"] = spec.limits.max_model_tokens
    extensions = {
        "source": "Agent Studio",
        "version": spec.version,
        "unmapped_builtin_tools": [
            builtin for builtin in spec.builtin_tools if builtin not in _NEXAU_BUILTINS
        ],
        "mcp_servers": list(spec.mcp_servers),
        "knowledge_references": list(spec.knowledge_references),
        "subagents": [
            {
                "alias": item.alias,
                "ref": item.ref,
                "description": item.responsibility,
                "background": item.background,
            }
            for item in spec.subagents
        ],
    }
    if any(
        extensions[key]
        for key in (
            "unmapped_builtin_tools",
            "mcp_servers",
            "knowledge_references",
            "subagents",
        )
    ):
        config["harness_extensions"] = extensions

    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        _write(
            archive,
            "agent.yaml",
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        )
        _write(archive, "systemprompt.md", spec.system_prompt.rstrip() + "\n")
        for skill in spec.skills:
            root = f"skills/{skill.name}"
            _write(
                archive,
                f"{root}/SKILL.md",
                _skill_markdown(skill.name, skill.description, skill.instructions),
            )
            for file in skill.files:
                payload = (
                    file.content.encode("utf-8")
                    if file.content is not None
                    else base64.b64decode(file.content_base64 or "", validate=True)
                )
                _write(archive, f"{root}/{file.path}", payload)
        for tool in spec.python_tools:
            _write(
                archive,
                f"tools/{tool.name}.tool.yaml",
                yaml.safe_dump(
                    {
                        "type": "tool",
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    },
                    sort_keys=False,
                    allow_unicode=True,
                ),
            )
            _write(archive, f"custom_tools/{tool.name}.py", _python_module(tool))

    return NexauAgentArchive(
        content=output.getvalue(),
        filename=f"{spec.name}-{spec.version}-nexau.zip",
    )
