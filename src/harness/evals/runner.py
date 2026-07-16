"""Deterministic live evaluation of published Harness Agent versions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from xml.etree import ElementTree

import httpx

from harness.evals.suite import EvalCase, EvalSuite

_TERMINAL_STATUSES = {"cancelled", "succeeded", "failed", "timed_out", "rejected"}


@dataclass(frozen=True)
class RecordedRun:
    run_id: str
    status: str
    duration_seconds: float
    events: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    run_id: str
    status: str
    duration_seconds: float
    passed: bool
    failures: tuple[str, ...]
    tools: tuple[str, ...]
    approval_requested: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "run_id": self.run_id,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "passed": self.passed,
            "failures": list(self.failures),
            "tools": list(self.tools),
            "approval_requested": self.approval_requested,
        }


@dataclass(frozen=True)
class EvalReport:
    agent: str
    agent_version: str
    cases: tuple[EvalCaseResult, ...]

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "agent_version": self.agent_version,
            "passed": self.passed,
            "passed_cases": sum(case.passed for case in self.cases),
            "total_cases": len(self.cases),
            "cases": [case.to_dict() for case in self.cases],
        }

    def to_junit_xml(self) -> str:
        failures = sum(not case.passed for case in self.cases)
        suite = ElementTree.Element(
            "testsuite",
            {
                "name": f"{self.agent}@{self.agent_version}",
                "tests": str(len(self.cases)),
                "failures": str(failures),
                "errors": "0",
                "time": f"{sum(case.duration_seconds for case in self.cases):.6f}",
            },
        )
        for result in self.cases:
            case = ElementTree.SubElement(
                suite,
                "testcase",
                {
                    "classname": self.agent,
                    "name": result.case_id,
                    "time": f"{result.duration_seconds:.6f}",
                },
            )
            properties = ElementTree.SubElement(case, "properties")
            ElementTree.SubElement(
                properties,
                "property",
                {"name": "run_id", "value": result.run_id},
            )
            ElementTree.SubElement(
                properties,
                "property",
                {"name": "status", "value": result.status},
            )
            if not result.passed:
                failure = ElementTree.SubElement(
                    case,
                    "failure",
                    {
                        "message": "; ".join(result.failures),
                        "type": "agent-evaluation-failure",
                    },
                )
                failure.text = "\n".join(result.failures)
        return ElementTree.tostring(suite, encoding="unicode")


class EvalClient(Protocol):
    async def create_session(self, agent_name: str, agent_version: str) -> str: ...

    async def upload_input(
        self, name: str, media_type: str, content: bytes
    ) -> str: ...

    async def create_run(
        self,
        session_id: str,
        prompt: str,
        idempotency_key: str,
        input_artifact_ids: tuple[str, ...] = (),
    ) -> str: ...

    async def wait_for_run(
        self,
        run_id: str,
        *,
        accepted_statuses: tuple[str, ...],
        timeout_seconds: float,
    ) -> RecordedRun: ...

    async def cancel_run(self, run_id: str) -> None: ...


def _event_payload(event: dict[str, object]) -> dict[str, object]:
    payload = event.get("payload")
    return cast(dict[str, object], payload) if isinstance(payload, dict) else {}


def evaluate_recorded_run(case: EvalCase, run: RecordedRun) -> EvalCaseResult:
    tools = tuple(
        str(_event_payload(event).get("name", ""))
        for event in run.events
        if event.get("type") == "tool.request"
        and _event_payload(event).get("name")
    )
    approval_requested = any(
        event.get("type") == "approval.requested" for event in run.events
    )
    output = "\n".join(
        str(_event_payload(event).get("text", ""))
        for event in run.events
        if event.get("type") in {"message.delta", "message.completed"}
        and _event_payload(event).get("text")
    )
    failures: list[str] = []
    if run.status not in case.expect.terminal_statuses:
        failures.append(f"unexpected status: {run.status}")
    for tool in case.expect.required_tools:
        if tool not in tools:
            failures.append(f"missing required tool: {tool}")
    for tool in case.expect.forbidden_tools:
        if tool in tools:
            failures.append(f"forbidden tool used: {tool}")
    for expected_text in case.expect.output_contains:
        if expected_text not in output:
            failures.append(f"output missing text: {expected_text}")
    if case.expect.approval_required and not approval_requested:
        failures.append("expected an approval request")
    if not case.expect.approval_required and approval_requested:
        failures.append("unexpected approval request")
    if run.duration_seconds > case.expect.max_duration_seconds:
        failures.append(
            f"duration exceeded {case.expect.max_duration_seconds:.1f}s: "
            f"{run.duration_seconds:.1f}s"
        )
    return EvalCaseResult(
        case_id=case.id,
        run_id=run.run_id,
        status=run.status,
        duration_seconds=run.duration_seconds,
        passed=not failures,
        failures=tuple(failures),
        tools=tools,
        approval_requested=approval_requested,
    )


class EvalRunner:
    def __init__(self, client: EvalClient) -> None:
        self._client = client

    async def run(
        self,
        suite: EvalSuite,
        *,
        agent_version: str,
        package_root: Path | None = None,
    ) -> EvalReport:
        results: list[EvalCaseResult] = []
        for case in suite.cases:
            loop = asyncio.get_running_loop()
            started = loop.time()
            run_id = ""
            try:
                session_id = await self._client.create_session(
                    suite.agent, agent_version
                )
                input_artifact_ids: list[str] = []
                for fixture in case.input_files:
                    if package_root is None:
                        raise ValueError(
                            f"evaluation case {case.id} requires a package root"
                        )
                    path = (package_root / fixture.path).resolve()
                    if not path.is_relative_to(package_root.resolve()) or not path.is_file():
                        raise ValueError(
                            f"evaluation input does not exist: {fixture.path}"
                        )
                    input_artifact_ids.append(
                        await self._client.upload_input(
                            path.name, fixture.media_type, path.read_bytes()
                        )
                    )
                idempotency_key = hashlib.sha256(
                    f"{suite.agent}:{agent_version}:{case.id}:{case.prompt}".encode()
                ).hexdigest()
                run_id = await self._client.create_run(
                    session_id,
                    case.prompt,
                    f"eval-{idempotency_key[:32]}",
                    tuple(input_artifact_ids),
                )
                run = await self._client.wait_for_run(
                    run_id,
                    accepted_statuses=case.expect.terminal_statuses,
                    timeout_seconds=case.expect.max_duration_seconds,
                )
                results.append(evaluate_recorded_run(case, run))
                if run.status not in _TERMINAL_STATUSES:
                    await self._client.cancel_run(run_id)
            except Exception as error:
                if run_id:
                    try:
                        await self._client.cancel_run(run_id)
                    except Exception:
                        pass
                message = str(error).strip() or type(error).__name__
                results.append(
                    EvalCaseResult(
                        case_id=case.id,
                        run_id=run_id,
                        status="error",
                        duration_seconds=loop.time() - started,
                        passed=False,
                        failures=(
                            f"evaluation infrastructure error "
                            f"({type(error).__name__}): {message}",
                        ),
                        tools=(),
                        approval_requested=False,
                    )
                )
        return EvalReport(
            agent=suite.agent,
            agent_version=agent_version,
            cases=tuple(results),
        )


class HttpHarnessEvalClient:
    """Small HTTP client for the public Harness Session/Run/Event contract."""

    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        user_id: str,
        api_token: str = "",
        client: httpx.AsyncClient | None = None,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {"X-Tenant-ID": tenant_id, "X-User-ID": user_id}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        self._client = client or httpx.AsyncClient(headers=headers, timeout=30)
        if client is not None:
            self._client.headers.update(headers)
        self._owns_client = client is None
        self._poll_interval = poll_interval_seconds

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def publish_agent(self, manifest_path: str) -> None:
        from harness.agent_package import pack_agent_package

        with tempfile.TemporaryDirectory(prefix="harness-eval-bundle-") as directory:
            archive, _ = pack_agent_package(
                manifest_path, output_directory=directory
            )
            response = await self._client.post(
                f"{self._base_url}/agents/bundles",
                content=archive.read_bytes(),
                headers={"Content-Type": "application/zip"},
            )
            response.raise_for_status()

    async def create_session(self, agent_name: str, agent_version: str) -> str:
        response = await self._client.post(
            f"{self._base_url}/sessions",
            json={"agent_name": agent_name, "agent_version": agent_version},
        )
        response.raise_for_status()
        return str(cast(dict[str, object], response.json())["session_id"])

    async def upload_input(
        self, name: str, media_type: str, content: bytes
    ) -> str:
        response = await self._client.post(
            f"{self._base_url}/input-artifacts",
            files={"file": (name, content, media_type)},
        )
        response.raise_for_status()
        return str(
            cast(dict[str, object], response.json())["input_artifact_id"]
        )

    async def create_run(
        self,
        session_id: str,
        prompt: str,
        idempotency_key: str,
        input_artifact_ids: tuple[str, ...] = (),
    ) -> str:
        response = await self._client.post(
            f"{self._base_url}/sessions/{session_id}/runs",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "prompt": prompt,
                "input_artifact_ids": list(input_artifact_ids),
            },
        )
        response.raise_for_status()
        return str(cast(dict[str, object], response.json())["run_id"])

    async def wait_for_run(
        self,
        run_id: str,
        *,
        accepted_statuses: tuple[str, ...],
        timeout_seconds: float,
    ) -> RecordedRun:
        loop = asyncio.get_running_loop()
        started = loop.time()
        status = "unknown"
        accepted = set(accepted_statuses)
        while loop.time() - started <= timeout_seconds:
            response = await self._client.get(f"{self._base_url}/runs/{run_id}")
            response.raise_for_status()
            status = str(cast(dict[str, object], response.json()).get("status", "unknown"))
            if status in accepted or status in _TERMINAL_STATUSES:
                break
            await asyncio.sleep(self._poll_interval)
        else:
            raise TimeoutError(
                f"Run {run_id} did not reach a terminal status within "
                f"{timeout_seconds:.1f}s"
            )
        events_response = await self._client.get(
            f"{self._base_url}/runs/{run_id}/events"
        )
        events_response.raise_for_status()
        events: list[dict[str, object]] = []
        for line in events_response.text.splitlines():
            if not line.startswith("data: "):
                continue
            value = json.loads(line[6:])
            if isinstance(value, dict):
                events.append(cast(dict[str, object], value))
        return RecordedRun(
            run_id=run_id,
            status=status,
            duration_seconds=loop.time() - started,
            events=tuple(events),
        )

    async def cancel_run(self, run_id: str) -> None:
        response = await self._client.post(
            f"{self._base_url}/runs/{run_id}/cancel"
        )
        response.raise_for_status()
