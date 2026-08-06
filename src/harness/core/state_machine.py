"""Run state transition rules."""

from harness.core.errors import InvalidRunTransitionError
from harness.core.models import RunStatus

_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset(
        {
            RunStatus.PROVISIONING,
            RunStatus.CANCELLING,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }
    ),
    RunStatus.PROVISIONING: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLING, RunStatus.FAILED, RunStatus.TIMED_OUT}
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.CANCELLING,
            RunStatus.REJECTED,
            RunStatus.FAILED,
            RunStatus.TIMED_OUT,
        }
    ),
    RunStatus.CANCELLING: frozenset({RunStatus.CANCELLED, RunStatus.FAILED}),
}


def transition(current: RunStatus, target: RunStatus) -> RunStatus:
    """Validate and return a requested Run status transition."""

    if current.is_terminal or target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidRunTransitionError(
            f"invalid run transition: {current.value} -> {target.value}"
        )
    return target
