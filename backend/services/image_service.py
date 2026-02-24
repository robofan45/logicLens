import base64
import io
import logging
from typing import Dict, Any

import cv2
import numpy as np
from PIL import Image

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_DIMENSION = 1280


def preprocess_image(file_bytes: bytes) -> Dict[str, Any]:
    """
    Preprocess raw image bytes into a dict with array, base64, dimensions, and blur score.
    """
    nparr = np.frombuffer(file_bytes, np.uint8)
    image_array = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image_array is None:
        # Fallback via Pillow for formats OpenCV may not handle
        try:
            pil_image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
            image_array = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        except Exception as exc:
            raise ValueError(f"Cannot decode image: {exc}") from exc

    height, width = image_array.shape[:2]

    # Resize if the largest dimension exceeds MAX_DIMENSION
    if max(height, width) > MAX_DIMENSION:
        scale = MAX_DIMENSION / max(height, width)
        new_width = int(width * scale)
        new_height = int(height * scale)
        image_array = cv2.resize(
            image_array, (new_width, new_height), interpolation=cv2.INTER_AREA
        )
        height, width = new_height, new_width

    # Compute Laplacian variance as sharpness metric
    gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    is_blurry = blur_score < settings.BLUR_THRESHOLD

    # Encode to base64 JPEG for LLM vision input
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
    success, buffer = cv2.imencode(".jpg", image_array, encode_params)
    if not success:
        raise ValueError("Failed to encode image to JPEG")
    base64_image = base64.b64encode(buffer.tobytes()).decode("utf-8")

    return {
        "image_array": image_array,
        "base64_image": base64_image,
        "width": width,
        "height": height,
        "blur_score": blur_score,
        "is_blurry": is_blurry,
    }
