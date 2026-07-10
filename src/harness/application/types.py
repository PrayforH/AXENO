"""Injected application service primitives."""

from collections.abc import Callable
from datetime import datetime

Clock = Callable[[], datetime]
IdGenerator = Callable[[str], str]

