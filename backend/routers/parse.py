import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address

from models.schemas import BoundingBox, ParsedElement, ParseResponse, PLCPlatform
from services.image_service import preprocess_image
from services.llm_service import llm_service
from services.session_service import session_service
from services.yolo_service import yolo_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analyze", tags=["analyze"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/parse", response_model=ParseResponse)
@limiter.limit("10/minute")
async def parse_ladder(
    request: Request,
    file: UploadFile = File(...),
    plc_platform: str = Form("generic"),
    session_id: Optional[str] = Form(None),
) -> ParseResponse:
    """
    Upload a PLC ladder logic image, run YOLO detection + LLM analysis,
    store results in a session and return the parsed elements.
    """
    t0 = time.monotonic()

    file_bytes = await file.read()

    # 1. Preprocess image
    img_info = preprocess_image(file_bytes)
    image_array = img_info["image_array"]
    base64_image = img_info["base64_image"]
    width: int = img_info["width"]
    height: int = img_info["height"]
    blur_score: float = img_info["blur_score"]

    # 2. YOLO detection with fallback
    yolo_dets, used_heuristic = yolo_service.detect_with_fallback(image_array)

    # 3. LLM image analysis
    try:
        platform_str = PLCPlatform(plc_platform).value
    except ValueError:
        platform_str = PLCPlatform.GENERIC.value

    llm_result = llm_service.analyze_image(base64_image, yolo_dets, platform_str)

    raw_elements = llm_result.get("parsed_elements", [])
    total_rungs: int = llm_result.get("total_rungs", 0)
    uncertainties = llm_result.get("uncertainties", [])

    if used_heuristic:
        uncertainties.append(
            "YOLO model returned no detections; heuristic bounding boxes were used."
        )

    # Convert raw dicts to ParsedElement objects
    parsed_elements = []
    for i, elem in enumerate(raw_elements):
        try:
            parsed_elements.append(ParsedElement(**elem))
        except Exception as exc:
            logger.warning("Failed to parse element %d: %s", i, exc)
            parsed_elements.append(
                ParsedElement(
                    id=elem.get("id", f"elem_{i}"),
                    element_type=elem.get("element_type", "Unknown"),
                )
            )

    # 4. Create or update session
    if session_id is None:
        session_id = session_service.create_session()
    else:
        if session_service.get_session(session_id) is None:
            session_id = session_service.create_session()

    session_service.update_session(
        session_id,
        {
            "parsed_elements": [e.model_dump() for e in parsed_elements],
            "yolo_detections": [d.model_dump() for d in yolo_dets],
            "total_rungs": total_rungs,
            "image_width": width,
            "image_height": height,
            "plc_platform": platform_str,
        },
    )

    processing_time_ms = (time.monotonic() - t0) * 1000.0

    return ParseResponse(
        session_id=session_id,
        parsed_elements=parsed_elements,
        yolo_detections=yolo_dets,
        total_rungs=total_rungs if total_rungs else len(set(e.rung for e in parsed_elements)),
        uncertainties=uncertainties,
        image_width=width,
        image_height=height,
        blur_score=blur_score,
        processing_time_ms=processing_time_ms,
    )
