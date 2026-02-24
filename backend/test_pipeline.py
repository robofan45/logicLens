"""
test_pipeline.py – End-to-end pipeline tests.

Run with:  pytest test_pipeline.py -v
or:        python -m pytest test_pipeline.py -v
"""

import base64
import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the backend package root is on the path when running directly
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np


# ---------------------------------------------------------------------------
# Helper: create a minimal JPEG byte string (1x1 white pixel)
# ---------------------------------------------------------------------------

def _make_jpeg_bytes() -> bytes:
    try:
        import cv2
        img = np.full((64, 64, 3), 255, dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", img)
        return buf.tobytes()
    except Exception:
        # Fallback: use Pillow
        from PIL import Image
        img = Image.new("RGB", (64, 64), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Image preprocessing
# ---------------------------------------------------------------------------

class TestImageService(unittest.TestCase):
    def test_preprocess_returns_expected_keys(self):
        from services.image_service import preprocess_image

        result = preprocess_image(_make_jpeg_bytes())
        self.assertIn("image_array", result)
        self.assertIn("base64_image", result)
        self.assertIn("width", result)
        self.assertIn("height", result)
        self.assertIn("blur_score", result)
        self.assertIn("is_blurry", result)

    def test_preprocess_base64_is_valid(self):
        from services.image_service import preprocess_image

        result = preprocess_image(_make_jpeg_bytes())
        decoded = base64.b64decode(result["base64_image"])
        self.assertGreater(len(decoded), 0)

    def test_preprocess_raises_on_invalid_bytes(self):
        from services.image_service import preprocess_image

        with self.assertRaises(ValueError):
            preprocess_image(b"not_an_image")

    def test_preprocess_resizes_large_image(self):
        import cv2
        from services.image_service import preprocess_image, MAX_DIMENSION

        large_img = np.full((2000, 3000, 3), 200, dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", large_img)
        result = preprocess_image(buf.tobytes())
        self.assertLessEqual(max(result["width"], result["height"]), MAX_DIMENSION)


# ---------------------------------------------------------------------------
# 2. YOLO service initialisation (mock)
# ---------------------------------------------------------------------------

class TestYOLOService(unittest.TestCase):
    def test_service_instantiates(self):
        from services.yolo_service import YOLOService

        svc = YOLOService()
        # Should not raise; model may or may not be loaded depending on environment
        self.assertIsNotNone(svc)

    def test_heuristic_detect_returns_list(self):
        import cv2
        from services.yolo_service import YOLOService

        svc = YOLOService()
        img = np.full((128, 128, 3), 255, dtype=np.uint8)
        # Draw a simple shape so connected components can find something
        cv2.rectangle(img, (20, 20), (50, 50), (0, 0, 0), 2)
        dets = svc.heuristic_detect(img)
        self.assertIsInstance(dets, list)

    def test_detect_with_fallback_returns_tuple(self):
        from services.yolo_service import YOLOService

        svc = YOLOService()
        img = np.full((64, 64, 3), 255, dtype=np.uint8)
        result = svc.detect_with_fallback(img)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        detections, used_heuristic = result
        self.assertIsInstance(detections, list)
        self.assertIsInstance(used_heuristic, bool)


# ---------------------------------------------------------------------------
# 3. LLM service (MOCK_LLM=True)
# ---------------------------------------------------------------------------

class TestLLMService(unittest.TestCase):
    def _get_mock_service(self):
        """Return an LLMService configured with MOCK_LLM=True."""
        from config import Settings
        mock_settings = Settings(MOCK_LLM=True)

        with patch("services.llm_service.settings", mock_settings):
            from services.llm_service import LLMService
            svc = LLMService()
            # Patch internal settings reference too
            svc.__class__  # touch class
            import services.llm_service as llm_mod
            original = llm_mod.settings
            llm_mod.settings = mock_settings
            yield svc
            llm_mod.settings = original

    def test_analyze_image_mock(self):
        from config import Settings
        import services.llm_service as llm_mod

        orig = llm_mod.settings
        llm_mod.settings = Settings(MOCK_LLM=True)
        try:
            from services.llm_service import LLMService
            svc = LLMService()
            result = svc.analyze_image("fake_b64", [], "generic")
            self.assertIn("parsed_elements", result)
            self.assertIsInstance(result["parsed_elements"], list)
        finally:
            llm_mod.settings = orig

    def test_trace_signal_flow_mock(self):
        from config import Settings
        import services.llm_service as llm_mod

        orig = llm_mod.settings
        llm_mod.settings = Settings(MOCK_LLM=True)
        try:
            from services.llm_service import LLMService
            svc = LLMService()
            result = svc.trace_signal_flow([{"id": "e0", "element_type": "NO_Contact"}])
            self.assertIn("execution_order", result)
            self.assertIn("signal_paths", result)
        finally:
            llm_mod.settings = orig

    def test_analyze_faults_mock(self):
        from config import Settings
        import services.llm_service as llm_mod

        orig = llm_mod.settings
        llm_mod.settings = Settings(MOCK_LLM=True)
        try:
            from services.llm_service import LLMService
            svc = LLMService()
            result = svc.analyze_faults([], {}, "")
            self.assertIn("faults", result)
        finally:
            llm_mod.settings = orig

    def test_extract_json_plain(self):
        from services.llm_service import LLMService
        svc = LLMService()
        raw = '{"key": "value", "num": 42}'
        out = svc._extract_json(raw)
        self.assertEqual(out, {"key": "value", "num": 42})

    def test_extract_json_with_fences(self):
        from services.llm_service import LLMService
        svc = LLMService()
        raw = "```json\n{\"a\": 1}\n```"
        out = svc._extract_json(raw)
        self.assertEqual(out, {"a": 1})

    def test_extract_json_embedded(self):
        from services.llm_service import LLMService
        svc = LLMService()
        raw = 'Some text before {"x": true} some text after'
        out = svc._extract_json(raw)
        self.assertEqual(out, {"x": True})

    def test_extract_json_invalid_returns_empty(self):
        from services.llm_service import LLMService
        svc = LLMService()
        out = svc._extract_json("this is not json at all")
        self.assertEqual(out, {})


# ---------------------------------------------------------------------------
# 4. Session service
# ---------------------------------------------------------------------------

class TestSessionService(unittest.TestCase):
    def setUp(self):
        from services.session_service import SessionService
        self.svc = SessionService()

    def test_create_returns_string(self):
        sid = self.svc.create_session()
        self.assertIsInstance(sid, str)
        self.assertGreater(len(sid), 0)

    def test_get_existing_session(self):
        sid = self.svc.create_session()
        data = self.svc.get_session(sid)
        self.assertIsNotNone(data)
        self.assertIsInstance(data, dict)

    def test_get_nonexistent_returns_none(self):
        data = self.svc.get_session("nonexistent-session-id")
        self.assertIsNone(data)

    def test_update_session(self):
        sid = self.svc.create_session()
        self.svc.update_session(sid, {"key": "value", "count": 42})
        data = self.svc.get_session(sid)
        self.assertEqual(data["key"], "value")
        self.assertEqual(data["count"], 42)

    def test_update_nonexistent_does_not_raise(self):
        # Should silently log a warning, not raise
        self.svc.update_session("no-such-session", {"x": 1})

    def test_count_sessions(self):
        initial = self.svc.count_sessions()
        self.svc.create_session()
        self.svc.create_session()
        self.assertEqual(self.svc.count_sessions(), initial + 2)

    def test_delete_session(self):
        sid = self.svc.create_session()
        self.svc.delete_session(sid)
        self.assertIsNone(self.svc.get_session(sid))


# ---------------------------------------------------------------------------
# 5. Rule-based fault engine
# ---------------------------------------------------------------------------

class TestFaultEngine(unittest.TestCase):
    def _make_elements(self, specs):
        """Build a minimal elements list from (element_type, address, rung) triples."""
        return [
            {"id": f"e{i}", "element_type": et, "address": addr, "label": addr, "rung": rung}
            for i, (et, addr, rung) in enumerate(specs)
        ]

    def _run_rules(self, elements):
        from routers.faults import _rule_based_faults
        return _rule_based_faults(elements)

    def test_rule1_duplicate_coil(self):
        elements = self._make_elements([
            ("Output_Coil", "Q0.0", 1),
            ("Output_Coil", "Q0.0", 2),
        ])
        faults = self._run_rules(elements)
        descs = [f.description for f in faults]
        self.assertTrue(any("Q0.0" in d and "multiple" in d for d in descs))

    def test_rule2_missing_estop(self):
        elements = self._make_elements([
            ("NO_Contact", "I0.0", 1),
            ("Output_Coil", "Q0.0", 1),
        ])
        faults = self._run_rules(elements)
        descs = [f.description for f in faults]
        self.assertTrue(any("E-stop" in d or "emergency" in d.lower() for d in descs))

    def test_rule2_no_estop_fault_when_present(self):
        elements = self._make_elements([
            ("NC_Contact", "E_Stop", 1),
            ("Output_Coil", "Q0.0", 1),
        ])
        faults = self._run_rules(elements)
        descs = [f.description for f in faults]
        # Should NOT flag missing E-stop
        self.assertFalse(any("E-stop" in d for d in descs))

    def test_rule3_unconditional_output(self):
        elements = self._make_elements([
            ("Output_Coil", "Q0.1", 5),
        ])
        faults = self._run_rules(elements)
        descs = [f.description for f in faults]
        self.assertTrue(any("always energised" in d or "no input" in d.lower() for d in descs))

    def test_rule4_incomplete_path(self):
        elements = self._make_elements([
            ("NO_Contact", "I0.2", 3),
        ])
        faults = self._run_rules(elements)
        descs = [f.description for f in faults]
        self.assertTrue(any("no output" in d.lower() for d in descs))

    def test_rule8_contradictory_contacts(self):
        elements = self._make_elements([
            ("NO_Contact", "I0.0", 1),
            ("NC_Contact", "I0.0", 1),
            ("Output_Coil", "Q0.0", 1),
        ])
        faults = self._run_rules(elements)
        descs = [f.description for f in faults]
        self.assertTrue(any("contradictory" in d.lower() or "NO and NC" in d for d in descs))


# ---------------------------------------------------------------------------
# 6. Ladder parser
# ---------------------------------------------------------------------------

class TestLadderParser(unittest.TestCase):
    def test_parse_empty_detections(self):
        from services.ladder_parser import parse_ladder_program
        program = parse_ladder_program([], 640, 480)
        self.assertEqual(len(program.rungs), 0)

    def test_parse_single_rung(self):
        from models.schemas import BoundingBox
        from services.ladder_parser import parse_ladder_program

        dets = [
            BoundingBox(x1=80, y1=55, x2=130, y2=85, class_name="NO_Contact", confidence=0.9),
            BoundingBox(x1=200, y1=55, x2=250, y2=85, class_name="NC_Contact", confidence=0.9),
            BoundingBox(x1=400, y1=55, x2=450, y2=85, class_name="Output_Coil", confidence=0.9),
        ]
        program = parse_ladder_program(dets, 640, 160)
        self.assertEqual(len(program.rungs), 1)
        rung = program.rungs[0]
        self.assertEqual(len(rung.series_elements), 2)
        self.assertEqual(len(rung.outputs), 1)

    def test_parse_multiple_rungs(self):
        from models.schemas import BoundingBox
        from services.ladder_parser import parse_ladder_program

        dets = [
            BoundingBox(x1=80, y1=55, x2=130, y2=85, class_name="NO_Contact", confidence=0.9),
            BoundingBox(x1=350, y1=55, x2=400, y2=85, class_name="Output_Coil", confidence=0.9),
            BoundingBox(x1=80, y1=155, x2=130, y2=185, class_name="NC_Contact", confidence=0.9),
            BoundingBox(x1=350, y1=155, x2=400, y2=185, class_name="Set_Coil", confidence=0.9),
        ]
        program = parse_ladder_program(dets, 640, 300)
        self.assertGreaterEqual(len(program.rungs), 2)


# ---------------------------------------------------------------------------
# 7. Ladder simulator
# ---------------------------------------------------------------------------

class TestLadderSimulator(unittest.TestCase):
    def _make_simple_program(self):
        from models.schemas import LadderProgram, LadderRung

        rung = LadderRung(
            rung_number=1,
            series_elements=[
                {"id": "c0", "element_type": "NO_Contact", "address": "I0.0", "properties": {}},
            ],
            outputs=[
                {"id": "q0", "element_type": "Output_Coil", "address": "Q0.0", "properties": {}},
            ],
        )
        return LadderProgram(rungs=[rung])

    def test_initial_state_all_false(self):
        from services.ladder_simulator import LadderSimulator

        sim = LadderSimulator(self._make_simple_program())
        state = sim.get_state()
        self.assertEqual(state.scan_count, 0)
        self.assertFalse(state.outputs.get("Q0.0", False))

    def test_scan_with_input_true_energises_output(self):
        from services.ladder_simulator import LadderSimulator

        sim = LadderSimulator(self._make_simple_program())
        sim.toggle_input("I0.0", True)
        sim.scan()
        state = sim.get_state()
        self.assertTrue(state.outputs.get("Q0.0", False))

    def test_scan_with_input_false_deenergises_output(self):
        from services.ladder_simulator import LadderSimulator

        sim = LadderSimulator(self._make_simple_program())
        sim.toggle_input("I0.0", True)
        sim.scan()
        sim.toggle_input("I0.0", False)
        sim.scan()
        state = sim.get_state()
        self.assertFalse(state.outputs.get("Q0.0", False))

    def test_scan_count_increments(self):
        from services.ladder_simulator import LadderSimulator

        sim = LadderSimulator(self._make_simple_program())
        for _ in range(3):
            sim.scan()
        self.assertEqual(sim.get_state().scan_count, 3)

    def test_toggle_flips_input(self):
        from services.ladder_simulator import LadderSimulator

        sim = LadderSimulator(self._make_simple_program())
        sim.toggle_input("I0.0")
        self.assertTrue(sim._inputs.get("I0.0", False))
        sim.toggle_input("I0.0")
        self.assertFalse(sim._inputs.get("I0.0", False))

    def test_reset_clears_state(self):
        from services.ladder_simulator import LadderSimulator

        sim = LadderSimulator(self._make_simple_program())
        sim.toggle_input("I0.0", True)
        sim.scan()
        sim.reset()
        state = sim.get_state()
        self.assertEqual(state.scan_count, 0)
        self.assertFalse(state.outputs.get("Q0.0", False))

    def test_nc_contact_logic(self):
        from models.schemas import LadderProgram, LadderRung
        from services.ladder_simulator import LadderSimulator

        rung = LadderRung(
            rung_number=1,
            series_elements=[
                {"id": "c0", "element_type": "NC_Contact", "address": "I0.1", "properties": {}},
            ],
            outputs=[
                {"id": "q0", "element_type": "Output_Coil", "address": "Q0.1", "properties": {}},
            ],
        )
        program = LadderProgram(rungs=[rung])
        sim = LadderSimulator(program)
        # NC contact: output energised when input is FALSE
        sim.toggle_input("I0.1", False)
        sim.scan()
        self.assertTrue(sim._outputs.get("Q0.1", False))
        # Now set input TRUE → output de-energised
        sim.toggle_input("I0.1", True)
        sim.scan()
        self.assertFalse(sim._outputs.get("Q0.1", False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
