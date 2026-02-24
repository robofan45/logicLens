import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from models.schemas import BoundingBox, ParsedElement, PLCPlatform

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Mock data helpers
# ---------------------------------------------------------------------------

def _mock_parsed_elements() -> List[Dict[str, Any]]:
    return [
        {
            "id": "elem_0",
            "element_type": "NO_Contact",
            "address": "I0.0",
            "label": "Start_PB",
            "rung": 1,
            "position_x": 80.0,
            "position_y": 60.0,
            "confidence": 0.95,
            "properties": {},
        },
        {
            "id": "elem_1",
            "element_type": "NC_Contact",
            "address": "I0.1",
            "label": "Stop_PB",
            "rung": 1,
            "position_x": 200.0,
            "position_y": 60.0,
            "confidence": 0.92,
            "properties": {},
        },
        {
            "id": "elem_2",
            "element_type": "Output_Coil",
            "address": "Q0.0",
            "label": "Motor_Run",
            "rung": 1,
            "position_x": 380.0,
            "position_y": 60.0,
            "confidence": 0.97,
            "properties": {},
        },
        {
            "id": "elem_3",
            "element_type": "NO_Contact",
            "address": "Q0.0",
            "label": "Motor_Run_Seal",
            "rung": 1,
            "position_x": 80.0,
            "position_y": 120.0,
            "confidence": 0.90,
            "properties": {},
        },
        {
            "id": "elem_4",
            "element_type": "TON_Timer",
            "address": "T1",
            "label": "Run_Timer",
            "rung": 2,
            "position_x": 200.0,
            "position_y": 180.0,
            "confidence": 0.88,
            "properties": {"preset": 5000},
        },
    ]


def _mock_trace_result() -> Dict[str, Any]:
    return {
        "execution_order": ["elem_0", "elem_1", "elem_2", "elem_3", "elem_4"],
        "signal_paths": [
            {
                "rung": 1,
                "path_elements": ["elem_0", "elem_1", "elem_2"],
                "is_energized": True,
                "conditions": ["I0.0 is ON", "I0.1 is NC (closed)"],
            },
            {
                "rung": 2,
                "path_elements": ["elem_4"],
                "is_energized": False,
                "conditions": ["T1 not yet preset"],
            },
        ],
        "dependency_map": {
            "Q0.0": ["I0.0", "I0.1"],
            "T1": ["Q0.0"],
        },
        "uncertainties": [],
    }


def _mock_faults_result() -> Dict[str, Any]:
    return {
        "faults": [
            {
                "fault_id": str(uuid.uuid4()),
                "severity": "medium",
                "category": "safety",
                "description": "No E-stop interlock detected in any rung.",
                "affected_elements": [],
                "recommendation": "Add a NC E-stop contact in series on all motor control rungs.",
                "standard_reference": "IEC 61131-3 §8.1",
            }
        ],
        "overall_risk_score": 42.0,
        "standards_checked": ["IEC 61131-3", "NFPA 79"],
    }


def _mock_correction_result() -> Dict[str, Any]:
    return {
        "corrected_rungs": [
            {
                "rung_number": 1,
                "original_description": "Start/Stop motor circuit without E-stop.",
                "corrected_description": "Start/Stop motor circuit with E-stop interlock added.",
                "changes_made": ["Added NC E-stop contact E0.0 in series."],
            }
        ],
        "summary": "Added E-stop interlock to rung 1 for safety compliance.",
        "structured_text": (
            "IF Start_PB AND NOT Stop_PB AND NOT E_Stop THEN\n"
            "    Motor_Run := TRUE;\nEND_IF;"
        ),
        "uncertainties": [],
    }


def _mock_translation_result(
    elements: List[Dict[str, Any]], target_platform: str
) -> Dict[str, Any]:
    translated = []
    for elem in elements:
        t = dict(elem)
        t["id"] = "t_" + t.get("id", str(uuid.uuid4()))
        translated.append(t)
    return {
        "translated_elements": translated,
        "mapping_notes": [f"Translated to {target_platform} conventions."],
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# LLM Service
# ---------------------------------------------------------------------------

class LLMService:
    def __init__(self) -> None:
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        if settings.MOCK_LLM:
            logger.info("MOCK_LLM=True; skipping real LLM client initialization.")
            return
        try:
            import openai  # type: ignore

            if settings.LLM_PROVIDER == "azure":
                self._client = openai.AzureOpenAI(
                    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                    api_key=settings.AZURE_OPENAI_API_KEY,
                    api_version=settings.AZURE_OPENAI_API_VERSION,
                )
                logger.info("Azure OpenAI client initialized.")
            else:
                kwargs: Dict[str, Any] = {"api_key": settings.OPENAI_API_KEY}
                if settings.OPENAI_BASE_URL:
                    kwargs["base_url"] = settings.OPENAI_BASE_URL
                self._client = openai.OpenAI(**kwargs)
                logger.info("OpenAI client initialized.")
        except Exception as exc:
            logger.error("Failed to initialize LLM client: %s", exc)
            self._client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_image(
        self,
        base64_image: str,
        yolo_detections: List[BoundingBox],
        plc_platform: str = "generic",
    ) -> Dict[str, Any]:
        if settings.MOCK_LLM:
            return {
                "parsed_elements": _mock_parsed_elements(),
                "total_rungs": 2,
                "uncertainties": ["Mock data – replace with real inference."],
            }

        detection_summary = self._format_detections(yolo_detections)
        system_prompt = (
            "You are an expert PLC engineer specializing in ladder logic analysis. "
            "Analyze the provided ladder logic diagram image and extract all elements. "
            "Return ONLY valid JSON with no additional text."
        )
        user_prompt = (
            f"Analyze this PLC ladder logic diagram (platform: {plc_platform}).\n"
            f"YOLO pre-detection found: {detection_summary}\n\n"
            "Return a JSON object with these exact keys:\n"
            "{\n"
            '  "parsed_elements": [ { "id": "elem_0", "element_type": "NO_Contact|NC_Contact|Output_Coil|...", '
            '"address": "I0.0", "label": "Tag_Name", "rung": 1, "position_x": 0.0, "position_y": 0.0, '
            '"confidence": 0.9, "properties": {} } ],\n'
            '  "total_rungs": 1,\n'
            '  "uncertainties": []\n'
            "}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ]

        for max_tokens in [4096, 2048, 1024, 512, 256]:
            try:
                raw = self._call_llm(messages, max_tokens)
                parsed = self._extract_json(raw)
                if parsed:
                    return parsed
            except Exception as exc:
                logger.warning("analyze_image attempt with max_tokens=%d failed: %s", max_tokens, exc)

        logger.error("All analyze_image attempts exhausted; returning empty result.")
        return {"parsed_elements": [], "total_rungs": 0, "uncertainties": ["LLM analysis failed."]}

    def trace_signal_flow(self, elements: List[Dict[str, Any]]) -> Dict[str, Any]:
        if settings.MOCK_LLM:
            return _mock_trace_result()

        system_prompt = (
            "You are a PLC ladder logic specialist. Trace signal flow through the provided "
            "parsed elements. Return ONLY valid JSON."
        )
        elements_json = json.dumps(elements, indent=2)
        user_prompt = (
            f"Trace signal flow for these ladder logic elements:\n{elements_json}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "execution_order": ["elem_id", ...],\n'
            '  "signal_paths": [{"rung": 1, "path_elements": [...], "is_energized": true, "conditions": [...]}],\n'
            '  "dependency_map": {"output_addr": ["input_addr", ...]},\n'
            '  "uncertainties": []\n'
            "}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            raw = self._call_llm(messages, 2048)
            result = self._extract_json(raw)
            if result:
                return result
        except Exception as exc:
            logger.error("trace_signal_flow failed: %s", exc)

        return {
            "execution_order": [e.get("id", "") for e in elements],
            "signal_paths": [],
            "dependency_map": {},
            "uncertainties": ["Signal trace unavailable."],
        }

    def analyze_faults(
        self,
        elements: List[Dict[str, Any]],
        trace_result: Dict[str, Any],
        user_context: str = "",
    ) -> Dict[str, Any]:
        if settings.MOCK_LLM:
            return _mock_faults_result()

        system_prompt = (
            "You are a PLC safety engineer. Analyze the ladder logic for faults, "
            "safety violations, and IEC 61131-3 non-conformances. Return ONLY valid JSON."
        )
        payload = json.dumps({"elements": elements, "trace": trace_result, "context": user_context})
        user_prompt = (
            f"Analyze these PLC elements for faults:\n{payload}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "faults": [{"fault_id":"...", "severity":"critical|high|medium|low|info", '
            '"category":"safety|logic|wiring|programming|standards", "description":"...", '
            '"affected_elements":[], "recommendation":"...", "standard_reference":"..."}],\n'
            '  "overall_risk_score": 0.0,\n'
            '  "standards_checked": ["IEC 61131-3"]\n'
            "}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            raw = self._call_llm(messages, 2048)
            result = self._extract_json(raw)
            if result:
                return result
        except Exception as exc:
            logger.error("analyze_faults failed: %s", exc)

        return {"faults": [], "overall_risk_score": 0.0, "standards_checked": []}

    def generate_correction(
        self,
        elements: List[Dict[str, Any]],
        trace_result: Dict[str, Any],
        faults: List[Dict[str, Any]],
        user_instructions: str = "",
    ) -> Dict[str, Any]:
        if settings.MOCK_LLM:
            return _mock_correction_result()

        system_prompt = (
            "You are a PLC programming expert. Generate corrected ladder logic rungs "
            "addressing the identified faults. Return ONLY valid JSON."
        )
        payload = json.dumps(
            {
                "elements": elements,
                "faults": faults,
                "instructions": user_instructions,
            }
        )
        user_prompt = (
            f"Generate corrections for this PLC program:\n{payload}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "corrected_rungs": [{"rung_number":1, "original_description":"...", '
            '"corrected_description":"...", "changes_made":[]}],\n'
            '  "summary": "...",\n'
            '  "structured_text": "IEC 61131-3 ST code here",\n'
            '  "uncertainties": []\n'
            "}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            raw = self._call_llm(messages, 2048)
            result = self._extract_json(raw)
            if result:
                return result
        except Exception as exc:
            logger.error("generate_correction failed: %s", exc)

        return {
            "corrected_rungs": [],
            "summary": "Correction generation failed.",
            "structured_text": "",
            "uncertainties": ["LLM correction unavailable."],
        }

    def translate_elements(
        self,
        elements: List[Dict[str, Any]],
        source_platform: str,
        target_platform: str,
    ) -> Dict[str, Any]:
        if settings.MOCK_LLM:
            return _mock_translation_result(elements, target_platform)

        system_prompt = (
            "You are a PLC cross-platform migration expert. Translate ladder logic elements "
            "between PLC platforms. Return ONLY valid JSON."
        )
        payload = json.dumps(
            {
                "elements": elements,
                "source": source_platform,
                "target": target_platform,
            }
        )
        user_prompt = (
            f"Translate these PLC elements from {source_platform} to {target_platform}:\n{payload}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "translated_elements": [...],\n'
            '  "mapping_notes": ["..."],\n'
            '  "warnings": []\n'
            "}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            raw = self._call_llm(messages, 2048)
            result = self._extract_json(raw)
            if result:
                return result
        except Exception as exc:
            logger.error("translate_elements failed: %s", exc)

        return {"translated_elements": elements, "mapping_notes": [], "warnings": ["Translation failed."]}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_llm(self, messages: List[Dict[str, Any]], max_tokens: int) -> str:
        if self._client is None:
            raise RuntimeError("LLM client is not initialized.")

        if settings.LLM_PROVIDER == "azure":
            model = settings.AZURE_OPENAI_DEPLOYMENT
        else:
            model = settings.OPENAI_MODEL

        response = self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """Extract a JSON object from LLM response text."""
        if not text:
            return {}

        # Strip markdown fences
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            # Remove first and last fence lines
            inner = "\n".join(lines[1:] if lines[0].startswith("```") else lines)
            if inner.endswith("```"):
                inner = inner[: inner.rfind("```")]
            stripped = inner.strip()

        # Direct parse
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # Find first { and last }
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("Failed to extract JSON from LLM response.")
        return {}

    @staticmethod
    def _format_detections(detections: List[BoundingBox]) -> str:
        if not detections:
            return "none"
        parts = [
            f"{d.class_name}@({d.x1:.0f},{d.y1:.0f})-({d.x2:.0f},{d.y2:.0f}) conf={d.confidence:.2f}"
            for d in detections[:20]  # limit summary length
        ]
        suffix = f" ...and {len(detections) - 20} more" if len(detections) > 20 else ""
        return "; ".join(parts) + suffix


llm_service = LLMService()
