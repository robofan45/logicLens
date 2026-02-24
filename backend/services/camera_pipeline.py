import logging
from typing import List

import cv2
import numpy as np

from models.schemas import BoundingBox
from services.yolo_service import yolo_service

logger = logging.getLogger(__name__)


def _deskew(image: np.ndarray) -> np.ndarray:
    """Correct minor rotation using Hough line detection."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)
    if lines is None:
        return image

    angles = []
    for line in lines[:20]:
        rho, theta = line[0]
        angle_deg = np.degrees(theta) - 90
        if -10 < angle_deg < 10:
            angles.append(angle_deg)

    if not angles:
        return image

    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.5:
        return image  # negligible skew

    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    deskewed = cv2.warpAffine(
        image, rotation_matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )
    return deskewed


class CameraPipeline:
    """
    Real-time preprocessing + detection pipeline for PLC ladder logic images.
    """

    def preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Apply denoising, adaptive thresholding, and deskew to a BGR frame.
        Returns a BGR image suitable for YOLO inference.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        denoised = cv2.fastNlMeansDenoising(gray, h=10)
        # Adaptive threshold for binarisation (returned as single-channel)
        binary = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=15,
            C=4,
        )
        # Convert back to BGR so downstream (YOLO) can handle 3-channel input
        bgr_binary = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        deskewed = _deskew(bgr_binary)
        return deskewed

    def detect_from_file(self, path: str) -> List[BoundingBox]:
        """Load an image from disk, preprocess, and run YOLO detection."""
        frame = cv2.imread(path)
        if frame is None:
            raise FileNotFoundError(f"Cannot read image from path: {path}")
        processed = self.preprocess_frame(frame)
        detections, _ = yolo_service.detect_with_fallback(processed)
        return detections

    def detect_from_bytes(self, image_bytes: bytes) -> List[BoundingBox]:
        """Decode image bytes, preprocess, and run YOLO detection."""
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Cannot decode image bytes.")
        processed = self.preprocess_frame(frame)
        detections, _ = yolo_service.detect_with_fallback(processed)
        return detections


camera_pipeline = CameraPipeline()
