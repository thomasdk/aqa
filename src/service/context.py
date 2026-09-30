"""Application context data and construction for the FastAPI application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config.settings import Settings
from src.config.user_data import bootstrap_user_data, conversations_dir
from src.llm.llm_manager import LLMManager
from src.prompts import PromptRepository
from src.service.discussion import DiscussionService


@dataclass(frozen=True)
class AppContext:
    """Dependencies shared by every application entry point."""

    settings: Settings
    llm_manager: LLMManager
    prompts: PromptRepository
    discussion: DiscussionService


def build_app_context() -> AppContext:
    """Build one context for the application that owns this factory."""

    bootstrap_user_data()
    settings = Settings.load()
    llm_manager = LLMManager(settings)
    prompts = PromptRepository(base_path=Path(settings.prompt_library_path))
    discussion = DiscussionService(
        settings=settings,
        llm_manager=llm_manager,
        prompt_repo=prompts,
        storage_dir=conversations_dir(),
    )
    return AppContext(
        settings=settings,
        llm_manager=llm_manager,
        prompts=prompts,
        discussion=discussion,
    )


__all__ = ["AppContext", "build_app_context"]
