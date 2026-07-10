import pytest

from harness.core.errors import InvalidRunTransitionError
from harness.core.models import RunStatus
from harness.core.state_machine import transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.QUEUED, RunStatus.PROVISIONING),
        (RunStatus.PROVISIONING, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.WAITING_APPROVAL),
        (RunStatus.WAITING_APPROVAL, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.CANCELLING),
        (RunStatus.CANCELLING, RunStatus.CANCELLED),
        (RunStatus.RUNNING, RunStatus.SUCCEEDED),
        (RunStatus.RUNNING, RunStatus.FAILED),
    ],
)
def test_allows_defined_run_transitions(current: RunStatus, target: RunStatus) -> None:
    assert transition(current, target) is target


def test_rejects_skipping_provisioning() -> None:
    with pytest.raises(InvalidRunTransitionError, match="queued -> running"):
        transition(RunStatus.QUEUED, RunStatus.RUNNING)


@pytest.mark.parametrize("terminal", list(RunStatus.terminal_statuses()))
def test_terminal_statuses_are_immutable(terminal: RunStatus) -> None:
    with pytest.raises(InvalidRunTransitionError):
        transition(terminal, RunStatus.RUNNING)
