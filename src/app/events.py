from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AppEvent:
    kind: str
    message: str
    payload: Any = None


EventHandler = Callable[[AppEvent], None]

