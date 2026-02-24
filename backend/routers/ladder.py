import json
import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from models.schemas import (
    ExportRequest,
    LadderProgram,
    ResetSimulatorRequest,
    ScanResponse,
    SimulateScanRequest,
    SimulatorState,
    StructureRequest,
    ToggleInputRequest,
)
from services.ladder_parser import parse_ladder_program
from services.ladder_simulator import LadderSimulator
from services.session_service import session_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ladder"])

# In-process simulator registry keyed by session_id
_simulators: Dict[str, LadderSimulator] = {}


def _get_or_create_simulator(session_id: str, session_data: dict) -> LadderSimulator:
    if session_id not in _simulators:
        yolo_dets_raw = session_data.get("yolo_detections", [])
        image_width = session_data.get("image_width", 1280)
        image_height = session_data.get("image_height", 960)

        # Reconstruct BoundingBox-like dicts into a LadderProgram
        from models.schemas import BoundingBox

        yolo_dets = []
        for d in yolo_dets_raw:
            try:
                yolo_dets.append(BoundingBox(**d))
            except Exception:
                pass

        program = parse_ladder_program(yolo_dets, image_width, image_height)
        _simulators[session_id] = LadderSimulator(program)
        logger.debug("Created simulator for session %s with %d rungs.", session_id, len(program.rungs))

    return _simulators[session_id]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/analyze/structure", response_model=Dict[str, Any])
async def get_structure(body: StructureRequest) -> Dict[str, Any]:
    """Return the parsed LadderProgram structure for a session."""
    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    from models.schemas import BoundingBox

    yolo_dets_raw = session_data.get("yolo_detections", [])
    image_width = session_data.get("image_width", 1280)
    image_height = session_data.get("image_height", 960)

    yolo_dets = []
    for d in yolo_dets_raw:
        try:
            yolo_dets.append(BoundingBox(**d))
        except Exception:
            pass

    program = parse_ladder_program(yolo_dets, image_width, image_height)
    return program.model_dump()


@router.post("/api/simulate/scan", response_model=ScanResponse)
async def simulate_scan(body: SimulateScanRequest) -> ScanResponse:
    """Run one or more PLC scan cycles and return the updated simulator state."""
    t0 = time.monotonic()

    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    sim = _get_or_create_simulator(body.session_id, session_data)

    rung_results: List[Dict[str, Any]] = []
    for _ in range(max(1, body.scan_count)):
        scan_result = sim.scan()
        rung_results = scan_result.get("rung_results", [])

    scan_time_ms = (time.monotonic() - t0) * 1000.0

    return ScanResponse(
        session_id=body.session_id,
        state=sim.get_state(),
        rung_results=rung_results,
        scan_time_ms=scan_time_ms,
    )


@router.post("/api/simulate/toggle", response_model=SimulatorState)
async def toggle_input(body: ToggleInputRequest) -> SimulatorState:
    """Toggle or set a simulator input bit."""
    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    sim = _get_or_create_simulator(body.session_id, session_data)
    sim.toggle_input(body.address, body.value)
    return sim.get_state()


@router.post("/api/simulate/reset", response_model=SimulatorState)
async def reset_simulator(body: ResetSimulatorRequest) -> SimulatorState:
    """Reset simulator state to initial values."""
    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    sim = _get_or_create_simulator(body.session_id, session_data)
    sim.reset()
    return sim.get_state()


@router.post("/api/export/json")
async def export_json(body: ExportRequest) -> JSONResponse:
    """Export the full session data as JSON."""
    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    return JSONResponse(
        content={
            "session_id": body.session_id,
            "parsed_elements": session_data.get("parsed_elements", []),
            "yolo_detections": session_data.get("yolo_detections", []),
            "trace_result": session_data.get("trace_result", {}),
            "faults": session_data.get("faults", []),
            "corrected_rungs": session_data.get("corrected_rungs", []),
        }
    )


@router.post("/api/export/st")
async def export_structured_text(body: ExportRequest) -> JSONResponse:
    """
    Export the ladder program as IEC 61131-3 Structured Text (ST).
    Generates ST code from the parsed elements stored in the session.
    """
    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    elements = session_data.get("parsed_elements", [])
    program_name = "PLC_Program"

    lines = [
        f"PROGRAM {program_name}",
        "VAR",
    ]

    # Collect unique addresses for variable declarations
    addresses = set()
    for elem in elements:
        addr = elem.get("address", "")
        if addr:
            addresses.add((addr, elem.get("label", addr), elem.get("element_type", "")))

    for addr, label, etype in sorted(addresses):
        var_comment = f" (* {label} *)" if label and label != addr else ""
        if etype in ("TON_Timer", "TOF_Timer", "RTO_Timer", "TP_Timer"):
            lines.append(f"    {addr} : TON;{var_comment}")
        elif etype in ("CTU_Counter", "CTD_Counter", "CTUD_Counter"):
            lines.append(f"    {addr} : CTU;{var_comment}")
        elif addr.upper().startswith("I") or addr.upper().startswith("%I"):
            lines.append(f"    {addr} : BOOL;{var_comment}  (* Input *)")
        elif addr.upper().startswith("Q") or addr.upper().startswith("%Q"):
            lines.append(f"    {addr} : BOOL;{var_comment}  (* Output *)")
        else:
            lines.append(f"    {addr} : BOOL;{var_comment}")

    lines.append("END_VAR")
    lines.append("")

    # Group elements by rung
    rungs: Dict[int, List[dict]] = {}
    for elem in elements:
        rung_num = elem.get("rung", 0)
        rungs.setdefault(rung_num, []).append(elem)

    for rung_num in sorted(rungs):
        rung_elems = rungs[rung_num]
        contacts = [
            e for e in rung_elems
            if e.get("element_type") in ("NO_Contact", "NC_Contact", "OSR_OneShotRising", "OSF_OneShotFalling")
        ]
        outputs = [
            e for e in rung_elems
            if e.get("element_type") in ("Output_Coil", "Negated_Coil", "Set_Coil", "Reset_Coil")
        ]

        if not outputs:
            continue

        # Build condition string
        conditions = []
        for c in contacts:
            addr = c.get("address", "")
            etype = c.get("element_type", "")
            if not addr:
                continue
            if etype == "NC_Contact":
                conditions.append(f"NOT {addr}")
            else:
                conditions.append(addr)

        condition_str = " AND ".join(conditions) if conditions else "TRUE"
        lines.append(f"(* Rung {rung_num} *)")

        for out in outputs:
            addr = out.get("address", "")
            etype = out.get("element_type", "")
            if not addr:
                continue
            if etype == "Output_Coil":
                lines.append(f"IF {condition_str} THEN")
                lines.append(f"    {addr} := TRUE;")
                lines.append("ELSE")
                lines.append(f"    {addr} := FALSE;")
                lines.append("END_IF;")
            elif etype == "Negated_Coil":
                lines.append(f"IF {condition_str} THEN")
                lines.append(f"    {addr} := FALSE;")
                lines.append("ELSE")
                lines.append(f"    {addr} := TRUE;")
                lines.append("END_IF;")
            elif etype == "Set_Coil":
                lines.append(f"IF {condition_str} THEN")
                lines.append(f"    {addr} := TRUE;")
                lines.append("END_IF;")
            elif etype == "Reset_Coil":
                lines.append(f"IF {condition_str} THEN")
                lines.append(f"    {addr} := FALSE;")
                lines.append("END_IF;")

        lines.append("")

    lines.append(f"END_PROGRAM")
    st_code = "\n".join(lines)

    return JSONResponse(
        content={
            "session_id": body.session_id,
            "structured_text": st_code,
            "program_name": program_name,
        }
    )
