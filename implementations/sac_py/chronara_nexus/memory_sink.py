"""Memory sink interface for observation storage."""

from typing import Protocol, List


class MemorySink(Protocol):
    """Protocol for memory storage backends."""

    def append(self, observation: dict) -> None:
        """Append observation to memory."""
        ...

    def get_all(self) -> List[dict]:
        """Retrieve all observations."""
        ...

    def clear(self) -> None:
        """Clear all observations."""
        ...


class InMemorySink:
    """In-memory implementation of MemorySink."""

    def __init__(self):
        self._storage: List[dict] = []

    def append(self, observation: dict) -> None:
        self._storage.append(observation)

    def get_all(self) -> List[dict]:
        return self._storage.copy()

    def clear(self) -> None:
        self._storage.clear()
