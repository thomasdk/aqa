"""Factory and cache for explicitly selected OpenAI-compatible LLM hosts."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlparse

import requests
from loguru import logger

from src.config.settings import LOCAL_AI_HOST_KIND, Settings

from .base_llm import BaseLLM
from .openai_compatible_llm import OpenAICompatibleLLM


class LLMManager:
    """Create adapters only for the host and model selected by an agent.

    There is deliberately no application-wide fallback host or eagerly opened
    connection. A host entry carries its own credentials and a managed Local
    AI entry is the only host kind that enables Gemma thinking.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._llm_instances: dict[str, BaseLLM] = {}
        self._model_list_cache: dict[str, list[str] | None] = {}
        self._managed_local_ai_cache_keys: set[str] = set()
        self._managed_request_started: Callable[[], None] | None = None
        self._managed_request_finished: Callable[[], None] | None = None

    def set_managed_local_ai_request_callbacks(
        self,
        request_started: Callable[[], None] | None,
        request_finished: Callable[[], None] | None,
    ) -> None:
        """Attach lifecycle observation only to application-managed Local AI adapters."""
        self._managed_request_started = request_started
        self._managed_request_finished = request_finished
        for key in self._managed_local_ai_cache_keys:
            instance = self._llm_instances.get(key)
            setter = getattr(instance, "set_request_activity_callbacks", None)
            if callable(setter):
                setter(request_started, request_finished)

    @staticmethod
    def _models_url(host: str) -> str:
        """Build the OpenAI-compatible model endpoint for a configured host."""
        parsed = urlparse(host)
        path = parsed.path or ""
        if "/chat/completions" in path:
            base_path = path.split("/chat/completions", 1)[0].rstrip("/")
            return f"{parsed.scheme}://{parsed.netloc}{base_path}/models"

        base = host.rstrip("/")
        return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"

    @staticmethod
    def _request_headers(api_key: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _list_available_model_ids(
        host: str,
        api_key: str | None = None,
        timeout: int = 5,
    ) -> list[str] | None:
        """Fetch model IDs advertised by an OpenAI-compatible host."""
        try:
            resp = requests.get(
                LLMManager._models_url(host),
                headers=LLMManager._request_headers(api_key),
                timeout=timeout,
                allow_redirects=False,
            )
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            ids = [model.get("id") for model in models if model.get("id")]
            return ids or None
        except Exception:
            logger.debug("Could not load model list from the configured host.")
            return None

    @staticmethod
    def check_connection(
        host: str,
        api_key: str | None = None,
        timeout: int = 5,
    ) -> None:
        """Check host reachability without parsing or returning its model list."""
        response = requests.get(
            LLMManager._models_url(host),
            headers=LLMManager._request_headers(api_key),
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        try:
            response.raise_for_status()
        finally:
            response.close()

    @staticmethod
    def _normalized_cache_host(host: str) -> str:
        """Normalize equivalent OpenAI base and chat-completions URLs."""
        clean = host.rstrip("/")
        if clean.endswith("/v1/chat/completions"):
            return clean[: -len("/v1/chat/completions")]
        if clean.endswith("/v1"):
            return clean[: -len("/v1")]
        return clean

    def _model_list_cache_key(self, host: str, api_key: str | None) -> str:
        return f"{self._normalized_cache_host(host)}|{api_key or ''}"

    def _available_model_ids(self, host: str, api_key: str | None) -> list[str] | None:
        cache_key = self._model_list_cache_key(host, api_key)
        if cache_key not in self._model_list_cache:
            self._model_list_cache[cache_key] = self._list_available_model_ids(
                host,
                api_key=api_key,
                timeout=self.settings.llm_health_timeout,
            )
        return self._model_list_cache[cache_key]

    def _ensure_model_available(self, host: str, model_name: str, api_key: str | None) -> None:
        """Validate a selected model when the host advertises a model list."""
        available = self._available_model_ids(host, api_key)
        if not available:
            logger.warning(
                "Could not validate the model name against /v1/models; continuing without validation"
            )
            return
        if model_name in available:
            return
        preview = ", ".join(available[:8])
        if len(available) > 8:
            preview += ", ..."
        raise ValueError(
            f"Modell '{model_name}' ist auf Host {host} nicht verfügbar. "
            f"Verfügbare Modelle: {preview}"
        )

    def invalidate_model_list(self, host: str | None = None) -> None:
        """Forget stale `/v1/models` responses after a server restart."""
        if host is None:
            self._model_list_cache.clear()
            return
        normalized = self._normalized_cache_host(host)
        self._model_list_cache = {
            key: value
            for key, value in self._model_list_cache.items()
            if not key.startswith(f"{normalized}|")
        }

    def _lookup_host_api_key(
        self, host: str, host_configuration_id: str | None = None
    ) -> str | None:
        """Return the secret stored with an explicitly configured host identity."""
        normalized = host.rstrip("/")
        entries = (
            [
                (
                    host_configuration_id,
                    self.settings.known_llm_hosts.get(host_configuration_id),
                )
            ]
            if host_configuration_id
            else self.settings.known_llm_hosts.items()
        )
        for _, config in entries:
            if not isinstance(config, dict) or config.get("url", "").rstrip("/") != normalized:
                continue
            key = config.get("api_key", "")
            return key if key else None
        return None

    def _is_managed_local_ai_host(self, host: str, host_configuration_id: str | None) -> bool:
        """Whether this request resolves to the application-managed Local AI host."""
        config = (
            self.settings.known_llm_hosts.get(host_configuration_id)
            if host_configuration_id
            else None
        )
        return (
            isinstance(config, dict)
            and config.get("kind") == LOCAL_AI_HOST_KIND
            and config.get("url", "").rstrip("/") == host.rstrip("/")
        )

    def _resolve_request_config(
        self,
        *,
        host: str | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
        host_configuration_id: str | None = None,
    ) -> tuple[str, str, str | None]:
        """Validate an explicit agent host/model and resolve its stored key."""
        resolved_host = host.strip() if isinstance(host, str) else ""
        resolved_model = model_name.strip() if isinstance(model_name, str) else ""
        if not resolved_host:
            raise ValueError("Agentenhost muss explizit gesetzt sein")
        if not resolved_model:
            raise ValueError("Agentenmodell muss explizit gesetzt sein")
        if host_configuration_id:
            config = self.settings.known_llm_hosts.get(host_configuration_id)
            models = config.get("models", []) if isinstance(config, dict) else []
            preferred = config.get("model") if isinstance(config, dict) else None
            selectable = {str(value).strip() for value in models if str(value).strip()}
            if isinstance(preferred, str) and preferred.strip():
                selectable.add(preferred.strip())
            if (
                not isinstance(config, dict)
                or str(config.get("url", "")).rstrip("/") != resolved_host.rstrip("/")
                or resolved_model not in selectable
            ):
                raise ValueError("Selected host configuration is no longer current")
        resolved_api_key = (
            api_key
            if api_key is not None
            else self._lookup_host_api_key(resolved_host, host_configuration_id)
        )
        # External-host catalogues are discovery aids, not exhaustive
        # allowlists. Deployments, aliases, and provider presets may be valid
        # request model IDs without appearing in `/models`. Managed Local AI
        # retains the stricter runtime/catalog boundary.
        if self._is_managed_local_ai_host(resolved_host, host_configuration_id):
            self._ensure_model_available(resolved_host, resolved_model, resolved_api_key)
        return resolved_host, resolved_model, resolved_api_key

    def _cache_key(
        self,
        host: str,
        model_name: str,
        api_key: str | None,
        host_configuration_id: str | None,
    ) -> str:
        return (
            f"{host_configuration_id or ''}|{self._normalized_cache_host(host)}|"
            f"{model_name}|{api_key or ''}"
        )

    def _create_llm_instance(
        self,
        *,
        host: str,
        model_name: str,
        api_key: str | None,
        host_configuration_id: str | None = None,
    ) -> BaseLLM:
        managed_local_ai = self._is_managed_local_ai_host(host, host_configuration_id)
        logger.info("Initializing OpenAI-compatible LLM %s @ %s", model_name, host)
        return OpenAICompatibleLLM(
            model_name=model_name,
            host=host,
            api_key=api_key or "",
            timeout=self.settings.llm_timeout,
            connect_timeout=self.settings.llm_connect_timeout,
            # Preserve the managed Integrated AI read policy. User-configured
            # External AI hosts have no application read deadline because slow
            # local servers may remain silent during prompt processing.
            stream_timeout=600 if managed_local_ai else None,
            health_timeout=self.settings.llm_health_timeout,
            health_retries=self.settings.llm_health_retries,
            retries=self.settings.llm_max_retries,
            retry_delay=self.settings.llm_retry_delay,
            enable_thinking=managed_local_ai,
            request_started=self._managed_request_started if managed_local_ai else None,
            request_finished=self._managed_request_finished if managed_local_ai else None,
        )

    def get_llm(
        self,
        host: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        host_configuration_id: str | None = None,
    ) -> BaseLLM:
        """Return a cached adapter for an explicitly selected host and model."""
        resolved_host, resolved_model, resolved_api_key = self._resolve_request_config(
            host=host,
            api_key=api_key,
            model_name=model_name,
            host_configuration_id=host_configuration_id,
        )
        cache_key = self._cache_key(
            resolved_host, resolved_model, resolved_api_key, host_configuration_id
        )
        if cache_key not in self._llm_instances:
            self._llm_instances[cache_key] = self._create_llm_instance(
                host=resolved_host,
                model_name=resolved_model,
                api_key=resolved_api_key,
                host_configuration_id=host_configuration_id,
            )
            if self._is_managed_local_ai_host(resolved_host, host_configuration_id):
                self._managed_local_ai_cache_keys.add(cache_key)
        return self._llm_instances[cache_key]
