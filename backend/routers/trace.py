import logging
import time

from fastapi import APIRouter, HTTPException

from models.schemas import SignalPath, TraceRequest, TraceResponse
from services.llm_service import llm_service
from services.session_service import session_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


@router.post("/trace", response_model=TraceResponse)
async def trace_signal_flow(body: TraceRequest) -> TraceResponse:
    """
    Trace signal flow through a previously parsed session's elements.
    """
    t0 = time.monotonic()

    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    elements = session_data.get("parsed_elements", [])
    if not elements:
        raise HTTPException(status_code=422, detail="No parsed elements found in session. Run /parse first.")

    result = llm_service.trace_signal_flow(elements)

    execution_order = result.get("execution_order", [])
    raw_paths = result.get("signal_paths", [])
    dependency_map = result.get("dependency_map", {})
    uncertainties = result.get("uncertainties", [])

    signal_paths = []
    for sp in raw_paths:
        try:
            signal_paths.append(SignalPath(**sp))
        except Exception as exc:
            logger.warning("Could not parse signal path: %s", exc)

    session_service.update_session(
        body.session_id,
        {
            "trace_result": result,
            "execution_order": execution_order,
        },
    )

    processing_time_ms = (time.monotonic() - t0) * 1000.0

    return TraceResponse(
        session_id=body.session_id,
        execution_order=execution_order,
        signal_paths=signal_paths,
        dependency_map=dependency_map,
        uncertainties=uncertainties,
        processing_time_ms=processing_time_ms,
    )
