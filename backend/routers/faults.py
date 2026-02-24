import logging
import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from models.schemas import (
    Fault,
    FaultCategory,
    FaultSeverity,
    FaultsRequest,
    FaultsResponse,
)
from services.llm_service import llm_service
from services.session_service import session_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

STANDARDS_CHECKED = ["IEC 61131-3", "NFPA 79", "IEC 62061"]


# ---------------------------------------------------------------------------
# Rule-based fallback fault engine (8 rules)
# ---------------------------------------------------------------------------

def _rule_based_faults(elements: List[Dict[str, Any]]) -> List[Fault]:
    faults: List[Fault] = []

    coil_addresses: Dict[str, List[str]] = {}
    no_contacts: Dict[str, List[str]] = {}
    nc_contacts: Dict[str, List[str]] = {}
    timer_ids: set = set()
    counter_ids: set = set()
    reset_ids: set = set()

    estop_keywords = {"estop", "e_stop", "emergency", "emc", "emg"}

    for elem in elements:
        etype = elem.get("element_type", "")
        addr = elem.get("address", "") or ""
        elem_id = elem.get("id", "")
        label_lower = (elem.get("label", "") or "").lower()

        if etype in ("Output_Coil", "Negated_Coil", "Set_Coil", "Reset_Coil"):
            coil_addresses.setdefault(addr, []).append(elem_id)
        if etype == "NO_Contact":
            no_contacts.setdefault(addr, []).append(elem_id)
        if etype == "NC_Contact":
            nc_contacts.setdefault(addr, []).append(elem_id)
        if etype in ("TON_Timer", "TOF_Timer", "RTO_Timer", "TP_Timer"):
            timer_ids.add(addr)
        if etype in ("CTU_Counter", "CTD_Counter", "CTUD_Counter"):
            counter_ids.add(addr)
        if etype == "RES_Reset":
            reset_ids.add(addr)

    # Rule 1 – Duplicate coil addresses
    for addr, ids in coil_addresses.items():
        if len(ids) > 1:
            faults.append(
                Fault(
                    fault_id=str(uuid.uuid4()),
                    severity=FaultSeverity.HIGH,
                    category=FaultCategory.PROGRAMMING,
                    description=f"Coil address '{addr}' is driven by multiple rungs ({len(ids)} occurrences).",
                    affected_elements=ids,
                    recommendation="Consolidate coil writes or use SET/RESET pairs.",
                    standard_reference="IEC 61131-3 §6.6.2",
                )
            )

    # Rule 2 – Missing E-stop / safety interlock
    has_estop = any(
        any(kw in (elem.get("label", "") or "").lower() for kw in estop_keywords)
        or any(kw in (elem.get("address", "") or "").lower() for kw in estop_keywords)
        for elem in elements
    )
    if not has_estop and elements:
        faults.append(
            Fault(
                fault_id=str(uuid.uuid4()),
                severity=FaultSeverity.CRITICAL,
                category=FaultCategory.SAFETY,
                description="No emergency-stop (E-stop) interlock detected in the program.",
                affected_elements=[],
                recommendation=(
                    "Add a normally-closed E-stop contact in series on all motor/actuator rungs."
                ),
                standard_reference="NFPA 79 §9.2.2 / IEC 62061 §6.7",
            )
        )

    # Rule 3 – Unconditional output (coil on a rung with no contacts)
    rungs: Dict[int, Dict[str, List[str]]] = {}
    for elem in elements:
        rung = elem.get("rung", 0)
        etype = elem.get("element_type", "")
        if rung not in rungs:
            rungs[rung] = {"contacts": [], "coils": []}
        if etype in ("NO_Contact", "NC_Contact", "OSR_OneShotRising", "OSF_OneShotFalling"):
            rungs[rung]["contacts"].append(elem.get("id", ""))
        if etype in ("Output_Coil", "Negated_Coil", "Set_Coil", "Reset_Coil"):
            rungs[rung]["coils"].append(elem.get("id", ""))

    for rung_num, rung_data in rungs.items():
        if rung_data["coils"] and not rung_data["contacts"]:
            faults.append(
                Fault(
                    fault_id=str(uuid.uuid4()),
                    severity=FaultSeverity.HIGH,
                    category=FaultCategory.LOGIC,
                    description=f"Rung {rung_num} has output coil(s) with no input conditions – always energised.",
                    affected_elements=rung_data["coils"],
                    recommendation="Add control contacts before the output coil.",
                    standard_reference="IEC 61131-3 §6.6.2",
                )
            )

    # Rule 4 – Incomplete signal paths (rungs with only contacts, no outputs)
    for rung_num, rung_data in rungs.items():
        if rung_data["contacts"] and not rung_data["coils"]:
            faults.append(
                Fault(
                    fault_id=str(uuid.uuid4()),
                    severity=FaultSeverity.MEDIUM,
                    category=FaultCategory.WIRING,
                    description=f"Rung {rung_num} has input contacts but no output element.",
                    affected_elements=rung_data["contacts"],
                    recommendation="Add an output coil or function block to complete the signal path.",
                    standard_reference="IEC 61131-3 §6.6",
                )
            )

    # Rule 5 – Timer/counter without reset
    unreset = (timer_ids | counter_ids) - reset_ids
    for addr in unreset:
        is_timer = addr in timer_ids
        faults.append(
            Fault(
                fault_id=str(uuid.uuid4()),
                severity=FaultSeverity.MEDIUM,
                category=FaultCategory.PROGRAMMING,
                description=(
                    f"{'Timer' if is_timer else 'Counter'} '{addr}' has no associated RES/Reset instruction."
                ),
                affected_elements=[addr],
                recommendation=f"Add a RES instruction to reset '{addr}' on the appropriate condition.",
                standard_reference="IEC 61131-3 §3.3.1",
            )
        )

    # Rule 6 – Missing seal-in circuit (motor coil driven by start only, no parallel coil contact)
    for coil_addr, coil_ids in coil_addresses.items():
        for elem_id in coil_ids:
            # Check if coil address appears as a NO contact on the same rung
            coil_elem = next((e for e in elements if e.get("id") == elem_id), None)
            if coil_elem is None:
                continue
            rung_num = coil_elem.get("rung", -1)
            same_rung_no = [
                e for e in elements
                if e.get("rung") == rung_num
                and e.get("element_type") == "NO_Contact"
                and e.get("address") == coil_addr
            ]
            if not same_rung_no:
                faults.append(
                    Fault(
                        fault_id=str(uuid.uuid4()),
                        severity=FaultSeverity.LOW,
                        category=FaultCategory.LOGIC,
                        description=(
                            f"Output '{coil_addr}' on rung {rung_num} has no seal-in (latching) contact."
                        ),
                        affected_elements=[elem_id],
                        recommendation=(
                            f"Add a NO contact for '{coil_addr}' in parallel with the start contact."
                        ),
                        standard_reference="IEC 61131-3 §6.6.2",
                    )
                )

    # Rule 7 – Single-element rungs
    for rung_num, rung_data in rungs.items():
        total_on_rung = len(rung_data["contacts"]) + len(rung_data["coils"])
        if total_on_rung == 1:
            faults.append(
                Fault(
                    fault_id=str(uuid.uuid4()),
                    severity=FaultSeverity.INFO,
                    category=FaultCategory.STANDARDS,
                    description=f"Rung {rung_num} contains only one element; logic may be incomplete.",
                    affected_elements=rung_data["contacts"] + rung_data["coils"],
                    recommendation="Verify rung logic is intentionally minimal.",
                    standard_reference="IEC 61131-3 §6.6",
                )
            )

    # Rule 8 – Contradictory contacts (same address as NO and NC in same rung)
    for rung_num in rungs:
        rung_no: Dict[str, str] = {}
        rung_nc: Dict[str, str] = {}
        for elem in elements:
            if elem.get("rung") != rung_num:
                continue
            addr = elem.get("address", "")
            if not addr:
                continue
            if elem.get("element_type") == "NO_Contact":
                rung_no[addr] = elem.get("id", "")
            if elem.get("element_type") == "NC_Contact":
                rung_nc[addr] = elem.get("id", "")
        for addr in set(rung_no) & set(rung_nc):
            faults.append(
                Fault(
                    fault_id=str(uuid.uuid4()),
                    severity=FaultSeverity.HIGH,
                    category=FaultCategory.LOGIC,
                    description=(
                        f"Rung {rung_num}: address '{addr}' appears as both NO and NC contact – "
                        "contradictory logic; rung will never be energised."
                    ),
                    affected_elements=[rung_no[addr], rung_nc[addr]],
                    recommendation=f"Remove the redundant contact for '{addr}'.",
                    standard_reference="IEC 61131-3 §6.6.2",
                )
            )

    return faults


def _risk_score(faults: List[Fault]) -> float:
    severity_weights = {
        FaultSeverity.CRITICAL: 30.0,
        FaultSeverity.HIGH: 15.0,
        FaultSeverity.MEDIUM: 7.0,
        FaultSeverity.LOW: 3.0,
        FaultSeverity.INFO: 1.0,
    }
    score = sum(severity_weights.get(f.severity, 0) for f in faults)
    return min(score, 100.0)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

@router.post("/faults", response_model=FaultsResponse)
async def analyze_faults(body: FaultsRequest) -> FaultsResponse:
    """
    Analyze ladder logic elements for faults, safety violations, and
    IEC 61131-3 non-conformances. Falls back to rule engine if LLM is unavailable.
    """
    t0 = time.monotonic()

    session_data = session_service.get_session(body.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found or expired.")

    elements = session_data.get("parsed_elements", [])
    trace_result = session_data.get("trace_result", {})

    llm_result = llm_service.analyze_faults(elements, trace_result, body.user_context)

    raw_faults = llm_result.get("faults", [])
    risk_score = llm_result.get("overall_risk_score", 0.0)
    standards = llm_result.get("standards_checked", STANDARDS_CHECKED)

    faults: List[Fault] = []
    for rf in raw_faults:
        try:
            faults.append(Fault(**rf))
        except Exception as exc:
            logger.warning("Could not parse LLM fault: %s", exc)

    # If LLM returned no faults (failure or empty), use rule-based engine
    if not faults:
        logger.info("LLM returned no faults; using rule-based fallback engine.")
        faults = _rule_based_faults(elements)
        risk_score = _risk_score(faults)
        standards = STANDARDS_CHECKED

    session_service.update_session(
        body.session_id,
        {
            "faults": [f.model_dump() for f in faults],
            "risk_score": risk_score,
        },
    )

    processing_time_ms = (time.monotonic() - t0) * 1000.0

    return FaultsResponse(
        session_id=body.session_id,
        faults=faults,
        overall_risk_score=risk_score,
        standards_checked=standards,
        processing_time_ms=processing_time_ms,
    )
