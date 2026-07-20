from datetime import UTC, datetime

from harness.agui.activity import activity_projection, build_run_activity
from harness.core.events import RunEvent

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def event(
    event_type: str,
    payload: dict[str, object] | None = None,
    sequence: int = 1,
    *,
    trace_id: str | None = "0123456789abcdef0123456789abcdef",
) -> RunEvent:
    return RunEvent(
        event_id=f"event-{sequence}",
        run_id="run-1",
        session_id="session-1",
        tenant_id="tenant-a",
        sequence=sequence,
        type=event_type,
        timestamp=NOW,
        payload=payload or {},
        trace_id=trace_id,
    )


def test_run_queued_creates_one_stable_activity_snapshot() -> None:
    projected = activity_projection(event("run.queued"))

    assert len(projected) == 1
    dumped = projected[0].model_dump(by_alias=True)
    assert dumped["type"] == "ACTIVITY_SNAPSHOT"
    assert dumped["messageId"] == "activity-run-1"
    assert dumped["activityType"] == "harness.run.v1"
    assert dumped["content"] == {
        "run_id": "run-1",
        "trace_id": "0123456789abcdef0123456789abcdef",
        "status": "queued",
        "started_at": "2026-07-13T00:00:00Z",
        "items": [
            {
                "id": "event-1",
                "event_type": "run.queued",
                "kind": "run",
                "status": "queued",
                "title": "任务已加入队列",
                "summary": None,
                "timestamp": "2026-07-13T00:00:00Z",
                "sequence": 1,
                "metadata": {},
            }
        ],
        "metrics": {},
    }


def test_model_and_result_append_safe_activity_deltas() -> None:
    model = activity_projection(
        event(
            "model.route.selected",
            {
                "provider": "new-api",
                "model": "shdata-glm",
                "used_fallback": False,
                "credential": "never-show",
            },
            2,
        )
    )[0].model_dump(by_alias=True)
    result = activity_projection(
        event(
            "runtime.result",
            {
                "num_turns": 2,
                "total_cost_usd": 0.02,
                "stop_reason": "end_turn",
                "session_id": "private-session",
            },
            3,
        )
    )[0].model_dump(by_alias=True)

    assert model["type"] == "ACTIVITY_DELTA"
    assert model["messageId"] == "activity-run-1"
    assert model["patch"][0]["path"] == "/items/-"
    assert model["patch"][0]["value"]["metadata"] == {
        "provider": "new-api",
        "model": "shdata-glm",
        "used_fallback": False,
    }
    assert result["patch"][1] == {
        "op": "replace",
        "path": "/status",
        "value": "succeeded",
    }
    metric_values = {item["path"]: item["value"] for item in result["patch"][2:]}
    assert metric_values == {
        "/metrics/turns": 2,
        "/metrics/cost_usd": 0.02,
        "/metrics/stop_reason": "end_turn",
    }
    assert "never-show" not in repr(model)
    assert "private-session" not in repr(result)


def test_content_rejection_projects_an_actionable_failure() -> None:
    projected = activity_projection(
        event(
            "run.failed",
            {
                "error_code": "provider_content_rejected",
                "message": "模型服务拒绝了本轮上下文，请重新运行。",
            },
        )
    )[0].model_dump(by_alias=True)

    item = projected["patch"][0]["value"]
    assert item["title"] == "模型服务拒绝了本轮上下文"
    assert item["summary"] == "模型服务拒绝了本轮上下文，请重新运行。"
    assert item["metadata"] == {"error_code": "provider_content_rejected"}


def test_stale_mcp_directory_projects_an_actionable_agent_upgrade() -> None:
    projected = activity_projection(
        event(
            "run.failed",
            {
                "error_code": "runtime_error",
                "error_type": "ToolResolutionError",
                "message": (
                    "published MCP tools are no longer available; "
                    "recheck and publish the Agent: mcp__knowledge__removed"
                ),
            },
        )
    )[0].model_dump(by_alias=True)

    item = projected["patch"][0]["value"]
    assert item["title"] == "Agent 工具配置需要更新"
    assert item["summary"] == (
        "当前版本绑定的 MCP 工具已变化，请切换到最新版本，"
        "或在 Studio 中重新检查并发布。"
    )
    assert item["metadata"] == {
        "error_code": "runtime_error",
        "error_type": "ToolResolutionError",
        "diagnostic": (
            "published MCP tools are no longer available; "
            "recheck and publish the Agent: mcp__knowledge__removed"
        ),
    }


def test_projects_visible_progress_text_but_suppresses_hidden_thinking_noise() -> None:
    commentary = activity_projection(
        event(
            "message.delta",
            {"text": "我先读取配置，再验证运行结果。", "message_id": "assistant-1"},
        )
    )[0].model_dump(by_alias=True)

    assert commentary["patch"][0]["value"]["kind"] == "analysis"
    assert commentary["patch"][0]["value"]["summary"] == (
        "我先读取配置，再验证运行结果。"
    )
    assert commentary["patch"][0]["value"]["metadata"] == {
        "message_id": "assistant-1"
    }
    assert (
        activity_projection(
            event("runtime.system", {"subtype": "thinking_tokens"})
        )
        == []
    )


def test_historical_provider_diagnostic_is_sanitized_in_activity_replay() -> None:
    projected = activity_projection(
        event("message.delta", {"text": "API Error: 400 Content Exists Risk"})
    )[0].model_dump(by_alias=True)

    summary = projected["patch"][0]["value"]["summary"]
    assert summary == (
        "模型服务拒绝了本轮上下文，可能由输入或外部检索内容触发。"
        "请重新运行，或缩小主题与时间范围。"
    )
    assert "Content Exists Risk" not in repr(projected)


def test_tool_activity_keeps_redacted_arguments_and_compact_result_facts() -> None:
    request = activity_projection(
        event(
            "tool.request",
            {
                "tool_call_id": "tool-1",
                "name": "Grep",
                "arguments": {
                    "pattern": "publishedVersion",
                    "path": "web/harness-console",
                    "api_key": "never-show",
                },
            },
            2,
        )
    )[0].model_dump(by_alias=True)
    result = activity_projection(
        event(
            "tool.result",
            {
                "tool_call_id": "tool-1",
                "content": "first match\nsecond match\nthird match",
                "is_error": False,
            },
            3,
        )
    )[0].model_dump(by_alias=True)

    assert request["patch"][0]["value"]["metadata"] == {
        "name": "Grep",
        "tool_call_id": "tool-1",
        "arguments": {
            "pattern": "publishedVersion",
            "path": "web/harness-console",
            "api_key": "[REDACTED]",
        },
    }
    assert result["patch"][0]["value"]["metadata"] == {
        "tool_call_id": "tool-1",
        "result_summary": "返回 3 行 · 36 字符",
    }
    assert "never-show" not in repr(request)
    assert "first match" not in repr(result)


def test_policy_denied_tool_result_explains_the_permission_mismatch() -> None:
    structured = activity_projection(
        event(
            "tool.result",
            {
                "tool_call_id": "tool-policy",
                "is_error": True,
                "error": {
                    "code": "policy_denied",
                    "message": "no policy rule matched",
                },
            },
        )
    )[0].model_dump(by_alias=True)
    sdk_result = activity_projection(
        event(
            "tool.result",
            {
                "tool_call_id": "tool-policy",
                "is_error": True,
                "content": "no policy rule matched",
            },
        )
    )[0].model_dump(by_alias=True)

    for projected in (structured, sdk_result):
        assert projected["patch"][0]["value"]["metadata"]["result_summary"] == (
            "权限 Profile 未放行此工具"
        )


def test_subagent_activity_keeps_parent_and_summary() -> None:
    projected = activity_projection(
        event(
            "subagent.completed",
            {
                "task_id": "task-1",
                "parent_tool_use_id": "tool-1",
                "summary": "Found two issues",
                "status": "completed",
                "alias": "fact-checker",
                "agent_name": "helper",
                "agent_version": "1.0.0",
                "policy_profile": "read-only",
                "depth": 1,
                "duration_ms": 40,
                "usage": {"total_tokens": 9, "tool_uses": 2},
                "secret": "never-show",
            },
            4,
        )
    )[0].model_dump(by_alias=True)

    item = projected["patch"][0]["value"]
    assert item["kind"] == "subagent"
    assert item["summary"] == "Found two issues"
    assert item["metadata"] == {
        "task_id": "task-1",
        "parent_tool_use_id": "tool-1",
        "alias": "fact-checker",
        "agent_name": "helper",
        "agent_version": "1.0.0",
        "policy_profile": "read-only",
        "depth": 1,
        "duration_ms": 40,
        "usage": {"total_tokens": 9, "tool_uses": 2},
    }
    assert "never-show" not in repr(projected)


def test_build_run_activity_folds_each_turn_for_history_replay() -> None:
    activity = build_run_activity(
        [
            event("run.queued", sequence=1),
            event("run.running", sequence=2),
            event(
                "tool.request",
                {"tool_call_id": "tool-1", "name": "Read"},
                sequence=3,
            ),
            event(
                "runtime.result",
                {"num_turns": 2, "total_cost_usd": 0.01},
                sequence=4,
            ),
            event("run.succeeded", sequence=5),
        ]
    )

    assert activity is not None
    assert activity["run_id"] == "run-1"
    assert activity["trace_id"] == "0123456789abcdef0123456789abcdef"
    assert activity["status"] == "succeeded"
    assert activity["metrics"] == {"turns": 2, "cost_usd": 0.01}
    assert [item["event_type"] for item in activity["items"]] == [
        "run.queued",
        "run.running",
        "tool.request",
        "runtime.result",
        "run.succeeded",
    ]
