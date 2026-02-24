import logging
import os
from typing import List, Tuple

import numpy as np

from config import get_settings
from models.schemas import BoundingBox

logger = logging.getLogger(__name__)
settings = get_settings()

# Mapping of class index → class name aligned with ElementType enum values
PLC_CLASSES: dict = {
    0: "NO_Contact",
    1: "NC_Contact",
    2: "Positive_Transition",
    3: "Negative_Transition",
    4: "Output_Coil",
    5: "Negated_Coil",
    6: "Set_Coil",
    7: "Reset_Coil",
    8: "TON_Timer",
    9: "TOF_Timer",
    10: "RTO_Timer",
    11: "TP_Timer",
    12: "CTU_Counter",
    13: "CTD_Counter",
    14: "CTUD_Counter",
    15: "RES_Reset",
    16: "EQU_Equal",
    17: "NEQ_NotEqual",
    18: "GRT_GreaterThan",
    19: "LES_LessThan",
    20: "GEQ_GreaterEqual",
    21: "LEQ_LessEqual",
    22: "ADD_Addition",
    23: "SUB_Subtraction",
    24: "MUL_Multiplication",
    25: "DIV_Division",
    26: "MOV_Move",
    27: "OSR_OneShotRising",
    28: "OSF_OneShotFalling",
    29: "Wire_Horizontal",
    30: "Wire_Vertical",
    31: "Branch_Start",
    32: "Branch_End",
    33: "Power_Rail_Left",
    34: "Power_Rail_Right",
    35: "TON_Timer",       # duplicate alias
    36: "CTU_Counter",     # duplicate alias
    37: "NO_Contact",      # alternate style
    38: "NC_Contact",      # alternate style
    39: "Output_Coil",     # alternate style
    40: "Set_Coil",        # alternate style
    41: "Reset_Coil",      # alternate style
    42: "Wire_Horizontal", # alternate style
    43: "Unknown",
}

NUM_PLC_CLASSES = 44


def _iou(box_a: List[float], box_b: List[float]) -> float:
    """Compute IoU between two [x1, y1, x2, y2] boxes."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_area = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0


def _nms(boxes: List[BoundingBox], iou_threshold: float) -> List[BoundingBox]:
    """Simple greedy NMS on BoundingBox objects sorted by confidence."""
    if not boxes:
        return []
    sorted_boxes = sorted(boxes, key=lambda b: b.confidence, reverse=True)
    kept: List[BoundingBox] = []
    for candidate in sorted_boxes:
        suppressed = False
        for kept_box in kept:
            if (
                _iou(
                    [candidate.x1, candidate.y1, candidate.x2, candidate.y2],
                    [kept_box.x1, kept_box.y1, kept_box.x2, kept_box.y2],
                )
                > iou_threshold
            ):
                suppressed = True
                break
        if not suppressed:
            kept.append(candidate)
    return kept


class YOLOService:
    def __init__(self) -> None:
        self._model = None
        self._model_loaded = False
        self._is_plc_model = False
        self._load_model()

    def _load_model(self) -> None:
        try:
            from ultralytics import YOLO  # type: ignore

            model_path = settings.YOLO_MODEL_PATH
            if os.path.exists(model_path):
                logger.info("Loading PLC YOLO model from %s", model_path)
                self._model = YOLO(model_path)
                # Determine if the loaded model is a PLC model by checking number of classes
                num_classes = len(self._model.names) if hasattr(self._model, "names") else 0
                self._is_plc_model = num_classes == NUM_PLC_CLASSES
                if not self._is_plc_model:
                    logger.warning(
                        "Model has %d classes (expected %d for PLC); heuristic fallback will be used.",
                        num_classes,
                        NUM_PLC_CLASSES,
                    )
            else:
                logger.warning(
                    "PLC model not found at %s. Attempting base model %s.",
                    model_path,
                    settings.YOLO_BASE_MODEL,
                )
                self._model = YOLO(settings.YOLO_BASE_MODEL)
                num_classes = len(self._model.names) if hasattr(self._model, "names") else 0
                self._is_plc_model = num_classes == NUM_PLC_CLASSES

            self._model_loaded = True
        except Exception as exc:
            logger.error("Failed to load YOLO model: %s. Heuristic mode only.", exc)
            self._model = None
            self._model_loaded = False

    def detect(self, image_array: np.ndarray) -> List[BoundingBox]:
        """Run YOLO inference and return BoundingBox list."""
        if not self._model_loaded or self._model is None:
            return []

        try:
            tta_augment = settings.YOLO_ENABLE_TTA and self._is_plc_model
            results = self._model.predict(
                source=image_array,
                conf=settings.YOLO_CONFIDENCE_THRESHOLD,
                iou=settings.YOLO_IOU_THRESHOLD,
                imgsz=settings.YOLO_IMG_SIZE,
                max_det=settings.YOLO_MAX_DETECTIONS,
                augment=tta_augment,
                verbose=False,
            )

            if not results or len(results) == 0:
                return []

            result = results[0]
            if result.boxes is None or len(result.boxes) == 0:
                return []

            # If model is not a PLC model, return empty to trigger heuristic
            if not self._is_plc_model:
                logger.info("Non-PLC model detected; returning empty to trigger heuristic.")
                return []

            detections: List[BoundingBox] = []
            for box in result.boxes:
                coords = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                cls_name = PLC_CLASSES.get(cls_id, "Unknown")
                detections.append(
                    BoundingBox(
                        x1=coords[0],
                        y1=coords[1],
                        x2=coords[2],
                        y2=coords[3],
                        confidence=conf,
                        class_name=cls_name,
                        class_id=cls_id,
                    )
                )

            return _nms(detections, settings.YOLO_IOU_THRESHOLD)

        except Exception as exc:
            logger.error("YOLO inference failed: %s", exc)
            return []

    def heuristic_detect(self, image_array: np.ndarray) -> List[BoundingBox]:
        """
        Fallback detection using connected component analysis on thresholded image.
        Returns boxes with class_name='Unknown'.
        """
        try:
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
            denoised = cv2.fastNlMeansDenoising(gray, h=10)
            binary = cv2.adaptiveThreshold(
                denoised,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                blockSize=15,
                C=4,
            )
            # Morphological closing to connect nearby strokes
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

            num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
            total_area = image_array.shape[0] * image_array.shape[1]
            min_area = settings.YOLO_HEURISTIC_MIN_AREA
            max_area = settings.YOLO_HEURISTIC_MAX_AREA_RATIO * total_area

            candidates: List[BoundingBox] = []
            for i in range(1, num_labels):  # skip background label 0
                x = int(stats[i, cv2.CC_STAT_LEFT])
                y = int(stats[i, cv2.CC_STAT_TOP])
                w = int(stats[i, cv2.CC_STAT_WIDTH])
                h = int(stats[i, cv2.CC_STAT_HEIGHT])
                area = int(stats[i, cv2.CC_STAT_AREA])
                if area < min_area or area > max_area:
                    continue
                candidates.append(
                    BoundingBox(
                        x1=float(x),
                        y1=float(y),
                        x2=float(x + w),
                        y2=float(y + h),
                        confidence=0.5,
                        class_name="Unknown",
                        class_id=-1,
                    )
                )

            after_nms = _nms(candidates, settings.YOLO_HEURISTIC_OVERLAP_IOU)
            return after_nms[: settings.YOLO_HEURISTIC_MAX_BOXES]

        except Exception as exc:
            logger.error("Heuristic detection failed: %s", exc)
            return []

    def detect_with_fallback(
        self, image_array: np.ndarray
    ) -> Tuple[List[BoundingBox], bool]:
        """
        Try YOLO detection; if empty, fall back to heuristic.
        Returns (detections, used_heuristic).
        """
        detections = self.detect(image_array)
        if detections:
            return detections, False
        logger.info("YOLO returned no detections; switching to heuristic.")
        return self.heuristic_detect(image_array), True


# Import cv2 here to avoid top-level crash when package is missing
try:
    import cv2  # type: ignore  # noqa: F401
except ImportError:
    logger.error("opencv-python-headless is not installed. Image processing disabled.")

yolo_service = YOLOService()
