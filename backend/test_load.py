"""
test_load.py – Model and service loading tests.

Run with:  pytest test_load.py -v
or:        python -m pytest test_load.py -v
"""

import os
import sys
import unittest

# Ensure backend package root is on the path
sys.path.insert(0, os.path.dirname(__file__))


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestConfigLoading(unittest.TestCase):
    def test_settings_load(self):
        from config import get_settings

        s = get_settings()
        self.assertIsNotNone(s)
        self.assertIsInstance(s.OPENAI_MODEL, str)
        self.assertIsInstance(s.YOLO_CONFIDENCE_THRESHOLD, float)
        self.assertIsInstance(s.SESSION_TTL_SECONDS, int)

    def test_settings_defaults(self):
        from config import Settings

        s = Settings()
        self.assertEqual(s.LLM_PROVIDER, "openai")
        self.assertEqual(s.OPENAI_MODEL, "gpt-4o")
        self.assertEqual(s.YOLO_CONFIDENCE_THRESHOLD, 0.15)
        self.assertEqual(s.SESSION_TTL_SECONDS, 3600)
        self.assertFalse(s.MOCK_LLM)

    def test_settings_lru_cache_singleton(self):
        from config import get_settings

        s1 = get_settings()
        s2 = get_settings()
        self.assertIs(s1, s2)

    def test_settings_env_override(self, monkeypatch=None):
        """Settings can be overridden via constructor kwargs."""
        from config import Settings

        s = Settings(MOCK_LLM=True, OPENAI_MODEL="gpt-3.5-turbo")
        self.assertTrue(s.MOCK_LLM)
        self.assertEqual(s.OPENAI_MODEL, "gpt-3.5-turbo")


# ---------------------------------------------------------------------------
# YOLO service loading
# ---------------------------------------------------------------------------

class TestYOLOServiceLoad(unittest.TestCase):
    def test_yolo_service_singleton_exists(self):
        from services.yolo_service import yolo_service

        self.assertIsNotNone(yolo_service)

    def test_yolo_service_has_detect_methods(self):
        from services.yolo_service import YOLOService

        svc = YOLOService()
        self.assertTrue(callable(getattr(svc, "detect", None)))
        self.assertTrue(callable(getattr(svc, "heuristic_detect", None)))
        self.assertTrue(callable(getattr(svc, "detect_with_fallback", None)))

    def test_yolo_service_missing_model_graceful(self):
        """YOLOService should instantiate even when no model file exists."""
        import services.yolo_service as yolo_mod
        from services.yolo_service import YOLOService

        orig_path = yolo_mod.settings.YOLO_MODEL_PATH
        orig_base = yolo_mod.settings.YOLO_BASE_MODEL
        yolo_mod.settings.YOLO_MODEL_PATH = "/nonexistent/path/best.pt"
        yolo_mod.settings.YOLO_BASE_MODEL = "/nonexistent/base.pt"
        try:
            svc = YOLOService()
            self.assertIsNotNone(svc)
            # Should gracefully fall back; model may be None
        finally:
            yolo_mod.settings.YOLO_MODEL_PATH = orig_path
            yolo_mod.settings.YOLO_BASE_MODEL = orig_base

    def test_plc_classes_count(self):
        from services.yolo_service import PLC_CLASSES, NUM_PLC_CLASSES

        self.assertEqual(len(PLC_CLASSES), NUM_PLC_CLASSES)
        for idx in range(NUM_PLC_CLASSES):
            self.assertIn(idx, PLC_CLASSES)
            self.assertIsInstance(PLC_CLASSES[idx], str)


# ---------------------------------------------------------------------------
# LLM service loading
# ---------------------------------------------------------------------------

class TestLLMServiceLoad(unittest.TestCase):
    def test_llm_service_singleton_exists(self):
        from services.llm_service import llm_service

        self.assertIsNotNone(llm_service)

    def test_llm_service_has_required_methods(self):
        from services.llm_service import LLMService

        svc = LLMService()
        for method in ("analyze_image", "trace_signal_flow", "analyze_faults",
                       "generate_correction", "translate_elements"):
            self.assertTrue(callable(getattr(svc, method, None)), f"Missing method: {method}")

    def test_llm_mock_mode_no_client_needed(self):
        """In MOCK_LLM=True mode the service should work without a real API key."""
        from config import Settings
        import services.llm_service as llm_mod

        orig = llm_mod.settings
        llm_mod.settings = Settings(MOCK_LLM=True, OPENAI_API_KEY="")
        try:
            from services.llm_service import LLMService
            svc = LLMService()
            result = svc.analyze_image("b64data", [], "generic")
            self.assertIn("parsed_elements", result)
            self.assertIsInstance(result["parsed_elements"], list)
            self.assertGreater(len(result["parsed_elements"]), 0)
        finally:
            llm_mod.settings = orig

    def test_llm_extract_json_roundtrip(self):
        import json
        from services.llm_service import LLMService

        svc = LLMService()
        payload = {"parsed_elements": [{"id": "e0"}], "total_rungs": 1}
        raw = json.dumps(payload)
        out = svc._extract_json(raw)
        self.assertEqual(out, payload)


# ---------------------------------------------------------------------------
# Session service loading
# ---------------------------------------------------------------------------

class TestSessionServiceLoad(unittest.TestCase):
    def test_session_service_singleton_exists(self):
        from services.session_service import session_service

        self.assertIsNotNone(session_service)

    def test_session_lifecycle(self):
        from services.session_service import SessionService

        svc = SessionService()
        sid = svc.create_session()
        self.assertIsNotNone(svc.get_session(sid))
        svc.update_session(sid, {"loaded": True})
        data = svc.get_session(sid)
        self.assertTrue(data.get("loaded"))
        svc.delete_session(sid)
        self.assertIsNone(svc.get_session(sid))


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

class TestSchemaLoad(unittest.TestCase):
    def test_all_enums_importable(self):
        from models.schemas import (
            ElementType,
            FaultCategory,
            FaultSeverity,
            PLCPlatform,
        )

        self.assertIn("GENERIC", PLCPlatform.__members__)
        self.assertIn("NO_CONTACT", ElementType.__members__)
        self.assertIn("CRITICAL", FaultSeverity.__members__)
        self.assertIn("SAFETY", FaultCategory.__members__)

    def test_bounding_box_creation(self):
        from models.schemas import BoundingBox

        bb = BoundingBox(x1=0.0, y1=0.0, x2=100.0, y2=50.0, confidence=0.9, class_name="NO_Contact")
        self.assertEqual(bb.x2, 100.0)
        self.assertEqual(bb.class_name, "NO_Contact")

    def test_parsed_element_creation(self):
        from models.schemas import ParsedElement

        elem = ParsedElement(id="e0", element_type="NO_Contact", address="I0.0", rung=1)
        self.assertEqual(elem.id, "e0")
        self.assertEqual(elem.rung, 1)

    def test_ladder_program_creation(self):
        from models.schemas import LadderProgram, LadderRung

        rung = LadderRung(rung_number=1)
        prog = LadderProgram(rungs=[rung])
        self.assertEqual(len(prog.rungs), 1)

    def test_simulator_state_defaults(self):
        from models.schemas import SimulatorState

        state = SimulatorState()
        self.assertEqual(state.scan_count, 0)
        self.assertEqual(state.inputs, {})
        self.assertEqual(state.outputs, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
