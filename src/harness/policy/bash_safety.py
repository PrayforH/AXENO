"""Conservative classification for low-risk Bash inside an isolated sandbox."""

from __future__ import annotations

import ast
import re
import shlex
from collections.abc import Collection
from pathlib import PurePosixPath

_LOW_RISK_COMMANDS = frozenset(
    {
        "[",
        "basename",
        "cat",
        "cmp",
        "comm",
        "cp",
        "cut",
        "date",
        "diff",
        "dirname",
        "du",
        "echo",
        "false",
        "file",
        "find",
        "grep",
        "head",
        "id",
        "jq",
        "ls",
        "md5sum",
        "mkdir",
        "ps",
        "pwd",
        "python",
        "python3",
        "readlink",
        "realpath",
        "rg",
        "sha1sum",
        "sha256sum",
        "shasum",
        "stat",
        "tail",
        "test",
        "true",
        "uname",
        "wc",
        "whoami",
    }
)
_COMMAND_SEPARATORS = frozenset({";", "&&", "||", "|"})
_REJECTED_SHELL_TOKENS = frozenset(
    {"&", "(", ")", "<", ">", "<<", ">>", "<<<", "<>", "&>"}
)
_NULL_REDIRECTION = re.compile(r"(?:(?<=\s)|^)[012]?>\s*/dev/null(?=\s|;|$)")
_UNSAFE_FIND_ACTIONS = frozenset(
    {"-delete", "-exec", "-execdir", "-fls", "-fprint", "-fprintf", "-ok", "-okdir"}
)
_SANDBOX_WIDE_METADATA_COMMANDS = frozenset(
    {"du", "file", "find", "ls", "readlink", "realpath", "stat"}
)
_QUOTED_PYTHON_HEREDOC = re.compile(
    r"\A\s*(?:/usr/bin/)?(?:python|python3)\s+-\s+"
    r"<<(?P<quote>['\"])(?P<delimiter>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)\s*\n"
    r"(?P<body>.*)\n(?P=delimiter)\s*\Z",
    re.DOTALL,
)
_LITERAL_FILE_HEREDOC = re.compile(
    r"\A\s*cat\s*>\s*(?P<path>'[^']+'|\"[^\"]+\"|[^\s]+)\s*"
    r"<<\s*(?P<quote>['\"])(?P<delimiter>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)\s*\n"
    r"(?P<body>.*?)\n(?P=delimiter)(?:\s*\n(?P<tail>.*))?\s*\Z",
    re.DOTALL,
)
_PROTECTED_WORKSPACE_ROOTS = frozenset(
    {".claude", ".git", ".harness-runtime", "inputs"}
)
_SAFE_PYTHON_MODULES = frozenset(
    {"csv", "hashlib", "json", "math", "pathlib", "re", "statistics"}
)
_SAFE_PYTHON_CALLS = frozenset(
    {
        "Path",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "float",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "print",
        "range",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }
)
_SAFE_PYTHON_METHODS = frozenset(
    {
        "as_posix",
        "decode",
        "endswith",
        "exists",
        "find",
        "get",
        "glob",
        "group",
        "groups",
        "hexdigest",
        "is_dir",
        "is_file",
        "items",
        "iterdir",
        "join",
        "keys",
        "lower",
        "match",
        "read_bytes",
        "read_text",
        "relative_to",
        "rglob",
        "search",
        "split",
        "splitlines",
        "startswith",
        "stat",
        "strip",
        "upper",
        "values",
    }
)
_REJECTED_PYTHON_NODES = (
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.FunctionDef,
    ast.Global,
    ast.Lambda,
    ast.Nonlocal,
    ast.Raise,
    ast.While,
    ast.With,
)


def _tokenize(command: str) -> list[str] | None:
    command = _NULL_REDIRECTION.sub("", command)
    if not command.strip() or any(value in command for value in ("\x00", "\n", "\r", "`", "$")):
        return None
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars=";&|()<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _command_name(value: str) -> str | None:
    if "/" not in value:
        return value
    pure = PurePosixPath(value)
    if pure.parent not in {PurePosixPath("/bin"), PurePosixPath("/usr/bin")}:
        return None
    return pure.name


def _path_stays_in_workspace(
    value: str,
    *,
    workspace: PurePosixPath,
    remote_workspace: PurePosixPath | None,
) -> bool:
    candidate = value.split("=", 1)[1] if "=" in value else value
    if candidate.startswith("-"):
        return True
    pure = PurePosixPath(candidate)
    if ".." in pure.parts:
        return False
    if not pure.is_absolute():
        return True
    roots = (workspace, PurePosixPath("/workspace"), remote_workspace)
    return any(
        root is not None and (pure == root or pure.is_relative_to(root))
        for root in roots
    )


def _read_only_python_heredoc_is_low_risk(
    command: str,
    *,
    workspace: PurePosixPath,
    remote_workspace: PurePosixPath | None,
) -> bool:
    match = _QUOTED_PYTHON_HEREDOC.fullmatch(command)
    if match is None:
        return False
    try:
        tree = ast.parse(match.group("body"), mode="exec")
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, _REJECTED_PYTHON_NODES):
            return False
        if isinstance(node, ast.Import):
            if any(alias.name.split(".", 1)[0] not in _SAFE_PYTHON_MODULES for alias in node.names):
                return False
        elif isinstance(node, ast.ImportFrom):
            if (
                node.level != 0
                or node.module is None
                or node.module.split(".", 1)[0] not in _SAFE_PYTHON_MODULES
                or any(alias.name == "*" for alias in node.names)
            ):
                return False
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in {"parent", "parents"}:
                return False
        elif isinstance(node, ast.Name) and node.id.startswith("_"):
            return False
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in _SAFE_PYTHON_CALLS:
                    return False
                if node.func.id == "Path":
                    if (
                        len(node.args) != 1
                        or node.keywords
                        or not isinstance(node.args[0], ast.Constant)
                        or not isinstance(node.args[0].value, str)
                        or not _path_stays_in_workspace(
                            node.args[0].value,
                            workspace=workspace,
                            remote_workspace=remote_workspace,
                        )
                    ):
                        return False
            elif isinstance(node.func, ast.Attribute):
                if node.func.attr not in _SAFE_PYTHON_METHODS:
                    return False
            else:
                return False
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if (
                not isinstance(node.right, ast.Constant)
                or not isinstance(node.right.value, str)
                or node.right.value.startswith("/")
                or ".." in PurePosixPath(node.right.value).parts
            ):
                return False
    return True


def _literal_workspace_heredoc(
    command: str,
    *,
    workspace: PurePosixPath,
    remote_workspace: PurePosixPath | None,
) -> str | None:
    match = _LITERAL_FILE_HEREDOC.fullmatch(command)
    if match is None or len(match.group("body").encode()) > 1024 * 1024:
        return None
    raw_path = match.group("path").strip("'\"")
    if not _path_stays_in_workspace(
        raw_path,
        workspace=workspace,
        remote_workspace=remote_workspace,
    ):
        return None
    target = PurePosixPath(raw_path)
    if target.is_absolute():
        roots = tuple(
            root
            for root in (workspace, PurePosixPath("/workspace"), remote_workspace)
            if root is not None and target.is_relative_to(root)
        )
        if not roots:
            return None
        target = target.relative_to(max(roots, key=lambda root: len(root.parts)))
    if not target.parts or target.parts[0] in _PROTECTED_WORKSPACE_ROOTS:
        return None
    return (match.group("tail") or "").strip()


def sandboxed_bash_is_low_risk(
    command: str,
    *,
    workspace: str,
    remote_workspace: str | None = None,
    generated_python_files: Collection[str] = (),
) -> bool:
    """Return true for bounded inspection or trusted workspace transformation commands."""

    workspace_path = PurePosixPath(workspace)
    remote_path = PurePosixPath(remote_workspace) if remote_workspace else None
    heredoc_tail = _literal_workspace_heredoc(
        command,
        workspace=workspace_path,
        remote_workspace=remote_path,
    )
    if heredoc_tail is not None:
        return not heredoc_tail or sandboxed_bash_is_low_risk(
            heredoc_tail,
            workspace=workspace,
            remote_workspace=remote_workspace,
            generated_python_files=generated_python_files,
        )
    if _read_only_python_heredoc_is_low_risk(
        command,
        workspace=workspace_path,
        remote_workspace=remote_path,
    ):
        return True
    tokens = _tokenize(command)
    if not tokens:
        return False
    expecting_command = True
    active_command = ""
    argument_index = 0
    for token in tokens:
        if token in _REJECTED_SHELL_TOKENS:
            return False
        if token in _COMMAND_SEPARATORS:
            if expecting_command:
                return False
            expecting_command = True
            active_command = ""
            argument_index = 0
            continue
        if expecting_command:
            name = _command_name(token)
            if name not in _LOW_RISK_COMMANDS:
                return False
            active_command = name
            expecting_command = False
            argument_index = 0
            continue
        lowered = token.lower()
        path = PurePosixPath(token)
        if active_command == "mkdir" and token.startswith("-") and token != "-p":
            return False
        if active_command == "cp" and token.startswith("-"):
            return False
        if active_command in {"python", "python3"} and argument_index == 0:
            if token.startswith("-"):
                return False
            script = PurePosixPath(token)
            trusted_roots = (
                (".claude", "skills"),
                (".harness-runtime", "bundle-tools"),
            )
            trusted_generated = token in generated_python_files or (
                not script.is_absolute()
                and script.as_posix().removeprefix("./") in generated_python_files
            )
            if not trusted_generated and (
                script.is_absolute()
                or not any(script.parts[: len(root)] == root for root in trusted_roots)
            ):
                return False
        if active_command == "rg" and (
            lowered == "--pre" or lowered.startswith("--pre=")
        ):
            return False
        if active_command == "find" and lowered in _UNSAFE_FIND_ACTIONS:
            return False
        if active_command in _SANDBOX_WIDE_METADATA_COMMANDS and path.is_absolute():
            # Metadata-only inspection may traverse the isolated runtime. It
            # cannot read file bodies, and destructive find actions remain
            # rejected above.
            argument_index += 1
            continue
        if active_command == "head" or active_command == "tail":
            if lowered == "--pid" or lowered.startswith("--pid="):
                return False
        if active_command == "echo":
            # Redirection, expansion, substitutions and newlines are rejected
            # during tokenization, so the remaining arguments are inert text.
            continue
        sandbox_detection_output = PurePosixPath("/tmp/detection_output")
        cp_sandbox_source = (
            active_command == "cp"
            and path.is_absolute()
            and (
                path == sandbox_detection_output
                or path.is_relative_to(sandbox_detection_output)
            )
        )
        if not cp_sandbox_source and not _path_stays_in_workspace(
            token,
            workspace=workspace_path,
            remote_workspace=remote_path,
        ):
            return False
        argument_index += 1
    return not expecting_command
