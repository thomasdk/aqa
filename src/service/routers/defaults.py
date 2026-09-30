"""Default material and material-normalization endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.service.api_schemas import (
    DefaultMaterialResponse,
    MaterialLineNumberRequest,
    MaterialLineNumberResponse,
    MaterialTokenEstimateRequest,
    MaterialTokenEstimateResponse,
)
from src.service.discussion import add_line_numbers_to_material, material_type_uses_line_numbers
from src.service.token_estimator import TOKENIZER_NAME, TokenEstimatorUnavailable, estimate_tokens

from .dependencies import ContextDependency

router = APIRouter(tags=["defaults"])

DEFAULT_MATERIAL_FILENAME = "European Union (2020) The New Leipzig Charter. The Transform.md"
DEFAULT_MATERIAL_TYPE = "document"


@router.get("/api/defaults/material", response_model=DefaultMaterialResponse)
def get_default_material(context: ContextDependency) -> DefaultMaterialResponse:
    example_path = Path(context.settings.prompt_defaults_path) / DEFAULT_MATERIAL_FILENAME
    try:
        if example_path.exists():
            return DefaultMaterialResponse(
                material=example_path.read_text(encoding="utf-8"),
                material_type=DEFAULT_MATERIAL_TYPE,
            )
    except (OSError, UnicodeError):
        pass
    return DefaultMaterialResponse(material="", material_type=DEFAULT_MATERIAL_TYPE)


@router.post(
    "/api/material/with-line-numbers",
    response_model=MaterialLineNumberResponse,
)
def add_line_numbers(
    payload: MaterialLineNumberRequest,
) -> MaterialLineNumberResponse:
    return MaterialLineNumberResponse(material=add_line_numbers_to_material(payload.material))


@router.post("/api/material/token-estimate", response_model=MaterialTokenEstimateResponse)
def estimate_material_tokens(
    payload: MaterialTokenEstimateRequest,
) -> MaterialTokenEstimateResponse:
    material = payload.material
    if material and material_type_uses_line_numbers(payload.material_type):
        material = add_line_numbers_to_material(material)
    try:
        return MaterialTokenEstimateResponse(
            approximate_tokens=estimate_tokens(material),
            tokenizer=TOKENIZER_NAME,
        )
    except TokenEstimatorUnavailable as exc:
        raise HTTPException(status_code=503, detail="Token estimate unavailable") from exc
