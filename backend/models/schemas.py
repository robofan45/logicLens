from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class PLCPlatform(str, Enum):
    SIEMENS_S7 = "siemens_s7"
    ROCKWELL = "rockwell"
    SCHNEIDER = "schneider"
    MITSUBISHI = "mitsubishi"
    OMRON = "omron"
    ABB = "abb"
    GENERIC = "generic"


class ElementType(str, Enum):
    NO_CONTACT = "NO_Contact"
    NC_CONTACT = "NC_Contact"
    POSITIVE_TRANSITION = "Positive_Transition"
    NEGATIVE_TRANSITION = "Negative_Transition"
    OUTPUT_COIL = "Output_Coil"
    NEGATED_COIL = "Negated_Coil"
    SET_COIL = "Set_Coil"
    RESET_COIL = "Reset_Coil"
    TON_TIMER = "TON_Timer"
    TOF_TIMER = "TOF_Timer"
    RTO_TIMER = "RTO_Timer"
    TP_TIMER = "TP_Timer"
    CTU_COUNTER = "CTU_Counter"
    CTD_COUNTER = "CTD_Counter"
    CTUD_COUNTER = "CTUD_Counter"
    RES_RESET = "RES_Reset"
    EQU_EQUAL = "EQU_Equal"
    NEQ_NOT_EQUAL = "NEQ_NotEqual"
    GRT_GREATER = "GRT_GreaterThan"
    LES_LESS = "LES_LessThan"
    GEQ_GREATER_EQUAL = "GEQ_GreaterEqual"
    LEQ_LESS_EQUAL = "LEQ_LessEqual"
    ADD = "ADD_Addition"
    SUB = "SUB_Subtraction"
    MUL = "MUL_Multiplication"
    DIV = "DIV_Division"
    MOV = "MOV_Move"
    OSR = "OSR_OneShotRising"
    OSF = "OSF_OneShotFalling"
    WIRE_H = "Wire_Horizontal"
    WIRE_V = "Wire_Vertical"
    BRANCH_START = "Branch_Start"
    BRANCH_END = "Branch_End"
    POWER_RAIL_LEFT = "Power_Rail_Left"
    POWER_RAIL_RIGHT = "Power_Rail_Right"
    UNKNOWN = "Unknown"


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = 0.0
    class_name: str = ""
    class_id: int = -1


class ParsedElement(BaseModel):
    id: str
    element_type: str
    address: str = ""
    label: str = ""
    rung: int = 0
    position_x: float = 0.0
    position_y: float = 0.0
    bounding_box: Optional[BoundingBox] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class ParseRequest(BaseModel):
    session_id: Optional[str] = None
    plc_platform: PLCPlatform = PLCPlatform.GENERIC


class ParseResponse(BaseModel):
    session_id: str
    parsed_elements: List[ParsedElement]
    yolo_detections: List[BoundingBox]
    total_rungs: int
    uncertainties: List[str] = []
    image_width: int = 0
    image_height: int = 0
    blur_score: float = 0.0
    processing_time_ms: float = 0.0


class SignalPath(BaseModel):
    rung: int
    path_elements: List[str]
    is_energized: bool
    conditions: List[str] = []


class TraceRequest(BaseModel):
    session_id: str


class TraceResponse(BaseModel):
    session_id: str
    execution_order: List[str]
    signal_paths: List[SignalPath]
    dependency_map: Dict[str, List[str]]
    uncertainties: List[str] = []
    processing_time_ms: float = 0.0


class FaultSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FaultCategory(str, Enum):
    SAFETY = "safety"
    LOGIC = "logic"
    WIRING = "wiring"
    PROGRAMMING = "programming"
    STANDARDS = "standards"


class Fault(BaseModel):
    fault_id: str
    severity: FaultSeverity
    category: FaultCategory
    description: str
    affected_elements: List[str] = []
    recommendation: str = ""
    standard_reference: str = ""


class FaultsRequest(BaseModel):
    session_id: str
    user_context: str = ""


class FaultsResponse(BaseModel):
    session_id: str
    faults: List[Fault]
    overall_risk_score: float
    standards_checked: List[str]
    processing_time_ms: float = 0.0


class CorrectedRung(BaseModel):
    rung_number: int
    original_description: str
    corrected_description: str
    changes_made: List[str] = []


class CorrectionRequest(BaseModel):
    session_id: str
    user_instructions: str = ""


class CorrectionResponse(BaseModel):
    session_id: str
    corrected_rungs: List[CorrectedRung]
    summary: str
    structured_text: str
    uncertainties: List[str] = []
    processing_time_ms: float = 0.0


class TranslationRequest(BaseModel):
    session_id: str
    source_platform: PLCPlatform = PLCPlatform.GENERIC
    target_platform: PLCPlatform = PLCPlatform.GENERIC


class TranslationResponse(BaseModel):
    session_id: str
    translated_elements: List[ParsedElement]
    mapping_notes: List[str]
    warnings: List[str]
    processing_time_ms: float = 0.0


# Simulator schemas
class LadderContact(BaseModel):
    address: str
    contact_type: str  # NO, NC, OSR, OSF
    label: str = ""


class LadderCoil(BaseModel):
    address: str
    coil_type: str  # OUTPUT, SET, RESET, NEGATED
    label: str = ""


class LadderBranch(BaseModel):
    elements: List[Dict[str, Any]]


class LadderRung(BaseModel):
    rung_number: int
    series_elements: List[Dict[str, Any]] = []
    parallel_branches: List[LadderBranch] = []
    outputs: List[Dict[str, Any]] = []
    comment: str = ""


class LadderProgram(BaseModel):
    program_name: str = "PLC_Program"
    rungs: List[LadderRung] = []
    symbol_table: Dict[str, str] = {}


class StructureRequest(BaseModel):
    session_id: str


class SimulateScanRequest(BaseModel):
    session_id: str
    scan_count: int = 1


class ToggleInputRequest(BaseModel):
    session_id: str
    address: str
    value: Optional[bool] = None


class ResetSimulatorRequest(BaseModel):
    session_id: str


class ExportRequest(BaseModel):
    session_id: str


class IOState(BaseModel):
    address: str
    value: bool = False
    label: str = ""


class SimulatorState(BaseModel):
    inputs: Dict[str, bool] = {}
    outputs: Dict[str, bool] = {}
    timers: Dict[str, Dict[str, Any]] = {}
    counters: Dict[str, Dict[str, Any]] = {}
    scan_count: int = 0


class ScanResponse(BaseModel):
    session_id: str
    state: SimulatorState
    rung_results: List[Dict[str, Any]] = []
    scan_time_ms: float = 0.0


class HealthResponse(BaseModel):
    status: str
    active_sessions: int
    version: str = "1.0.0"
