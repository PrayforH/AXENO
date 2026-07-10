"""Domain errors."""


class HarnessDomainError(Exception):
    """Base error for domain rule violations."""


class InvalidRunTransitionError(HarnessDomainError):
    """Raised when a Run state transition is not part of the state machine."""
