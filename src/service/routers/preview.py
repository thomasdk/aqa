"""Prompt-preview endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.prompts.preview import (
    PREVIEW_SCENARIOS,
    _build_material_context_for_preview,
    build_preview_rendered,
    build_preview_user_prompt,
)
from src.service.api_schemas import PreviewResult, PromptSource, TemplateInfo
from src.service.token_estimator import TOKENIZER_NAME, TokenEstimatorUnavailable, estimate_tokens

from .dependencies import ContextDependency

router = APIRouter(prefix="/api/preview", tags=["preview"])


@router.get("/templates", response_model=list[TemplateInfo])
def list_preview_templates(context: ContextDependency) -> list[TemplateInfo]:
    return [
        TemplateInfo(
            id=template.id,
            label=template.label,
        )
        for template in context.prompts.list_templates()
    ]


@router.get("/{template_id}", response_model=PreviewResult)
def render_preview(
    template_id: str,
    context: ContextDependency,
    multi_agent: bool = False,
    session_type: str = "",
    scenario: str = "first_round",
) -> PreviewResult:
    template = context.prompts.get_template(template_id)
    if template is None:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{template_id}' nicht gefunden",
        )

    selected_session_type = session_type or context.discussion.get_default_session_type()
    try:
        material_context = _build_material_context_for_preview(
            selected_session_type,
            service=context.discussion,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if scenario not in PREVIEW_SCENARIOS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown preview scenario '{scenario}'",
        )
    system_prompt, segments = build_preview_rendered(
        service=context.discussion,
        template=template,
        material_context=material_context,
        multi_agent=multi_agent,
        total_agents=3 if multi_agent else 1,
    )
    user_prompt = build_preview_user_prompt(
        material_context,
        scenario=scenario,
        multi_agent=multi_agent,
    )
    try:
        estimated_tokens = estimate_tokens(f"{system_prompt}\n\n{user_prompt}")
    except TokenEstimatorUnavailable:
        # Do not turn an unavailable estimator into a misleading zero-token
        # result.  The client can show an explicit unavailable state instead.
        estimated_tokens = None
    session_definition = context.discussion.session_type_repo.get(material_context.session_type)
    session_label = (
        session_definition.label
        if session_definition is not None
        else material_context.session_label
    )
    return PreviewResult(
        template_id=template_id,
        label=template.label,
        mode="multi_agent" if multi_agent else "single_agent",
        char_count=len(system_prompt) + len(user_prompt),
        estimated_tokens=estimated_tokens,
        tokenizer_name=TOKENIZER_NAME,
        prompt_sources=[
            PromptSource(key=key, content=segments[key])
            for key in ("context", "globals", "role", "task", "output_format")
            if segments.get(key)
        ],
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        scenario=scenario,
        session_type=material_context.session_type,
        session_label=session_label,
    )
