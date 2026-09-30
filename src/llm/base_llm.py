"""Abstract interface for language-model adapters."""

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import Any


class BaseLLM(ABC):
    """Contract implemented by every language-model adapter."""

    def __init__(
        self,
        model_name: str,
        timeout: int = 60,
        retries: int = 0,
        retry_delay: float = 2.0,
        **kwargs,
    ) -> None:
        self.model_name = model_name
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.config = kwargs

    @abstractmethod
    def generate(
        self, prompt: str, temperature: float | None = None, max_tokens: int = 2048, **kwargs
    ) -> str:
        """Generate a complete response without streaming.

        ``temperature=None`` lets the provider apply its own default.
        """
        pass

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int = 2048,
        on_usage: Callable[[dict[str, int]], None] | None = None,
        cancel_event: threading.Event | None = None,
        **kwargs,
    ) -> Iterator[str]:
        """Yield a generated response incrementally.

        ``on_usage`` receives valid final provider usage when available.
        ``cancel_event`` requests prompt closure of an in-flight stream.
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """Return adapter-specific metadata for the selected model."""
        pass

    def health_check(self) -> bool:
        """Return backend reachability; local adapters may override this method."""

        return True
