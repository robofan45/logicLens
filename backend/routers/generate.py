import logging
import time

from fastapi import APIRouter, HTTPException

from models.schemas import (
    CorrectedRung,
    CorrectionRequest,
    CorrectionResponse,
    ParsedElement,
    TranslationRequest,
    TranslationResponse,
)
from services.llm_service import llm_service
from services.session_service import session_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])


@router.post("/correction", response_model=CorrectionResponse)
async def generate_correction(body: CorrectionRequest) -> CorrectionResponse:
    """
    Generate corrected ladder logic rungs based on identified faults.
    """
    t0 = time.monotonic()

    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    elements = session_data.get("parsed_elements", [])
    trace_result = session_data.get("trace_result", {})
    faults = session_data.get("faults", [])

    result = llm_service.generate_correction(elements, trace_result, faults, body.user_instructions)

    raw_rungs = result.get("corrected_rungs", [])
    summary = result.get("summary", "")
    structured_text = result.get("structured_text", "")
    uncertainties = result.get("uncertainties", [])

    corrected_rungs = []
    for rr in raw_rungs:
        try:
            corrected_rungs.append(CorrectedRung(**rr))
        except Exception as exc:
            logger.warning("Could not parse corrected rung: %s", exc)

    session_service.update_session(
        body.session_id,
        {"corrected_rungs": [r.model_dump() for r in corrected_rungs]},
    )

    processing_time_ms = (time.monotonic() - t0) * 1000.0

    return CorrectionResponse(
        session_id=body.session_id,
        corrected_rungs=corrected_rungs,
        summary=summary,
        structured_text=structured_text,
        uncertainties=uncertainties,
        processing_time_ms=processing_time_ms,
    )


@router.post("/translation", response_model=TranslationResponse)
async def generate_translation(body: TranslationRequest) -> TranslationResponse:
    """
    Translate ladder logic elements from one PLC platform to another.
    """
    t0 = time.monotonic()

    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    elements = session_data.get("parsed_elements", [])

    result = llm_service.translate_elements(
        elements,
        body.source_platform.value,
        body.target_platform.value,
    )

    raw_translated = result.get("translated_elements", [])
    mapping_notes = result.get("mapping_notes", [])
    warnings = result.get("warnings", [])

    translated_elements = []
    for elem in raw_translated:
        try:
            translated_elements.append(ParsedElement(**elem))
        except Exception as exc:
            logger.warning("Could not parse translated element: %s", exc)

    processing_time_ms = (time.monotonic() - t0) * 1000.0

    return TranslationResponse(
        session_id=body.session_id,
        translated_elements=translated_elements,
        mapping_notes=mapping_notes,
        warnings=warnings,
        processing_time_ms=processing_time_ms,
    )
