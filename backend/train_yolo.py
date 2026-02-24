"""
train_yolo.py – Train a YOLO model on a PLC ladder logic dataset.

Usage:
    python train_yolo.py [--epochs 50] [--batch 16] [--imgsz 640]
"""

import argparse
import logging
import os
import shutil

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DATASET_YAML = "plc_dataset/dataset.yaml"
OUTPUT_DIR = "models/yolo"
BEST_PT_DEST = os.path.join(OUTPUT_DIR, "best.pt")


def train(epochs: int = 50, batch: int = 16, imgsz: int = 640, base_model: str = "yolo11n.pt") -> None:
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        logger.error("ultralytics is not installed. Run: pip install ultralytics")
        return

    if not os.path.exists(DATASET_YAML):
        logger.error("Dataset YAML not found at '%s'. Run generate_plc_dataset.py first.", DATASET_YAML)
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    logger.info("Loading base model: %s", base_model)
    model = YOLO(base_model)

    logger.info(
        "Starting training: epochs=%d  batch=%d  imgsz=%d  data=%s",
        epochs,
        batch,
        imgsz,
        DATASET_YAML,
    )
    results = model.train(
        data=DATASET_YAML,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        patience=10,
        name="yolo11n_plc",
        exist_ok=True,
    )

    # Locate best.pt from training output
    run_dir = results.save_dir if hasattr(results, "save_dir") else "runs/detect/yolo11n_plc"
    best_pt_src = os.path.join(str(run_dir), "weights", "best.pt")

    if os.path.exists(best_pt_src):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        shutil.copy2(best_pt_src, BEST_PT_DEST)
        logger.info("Best model saved to %s", BEST_PT_DEST)
    else:
        logger.warning("best.pt not found at expected location: %s", best_pt_src)

    logger.info("Training complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train YOLO on PLC ladder logic dataset.")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--base-model", type=str, default="yolo11n.pt")
    args = parser.parse_args()
    train(epochs=args.epochs, batch=args.batch, imgsz=args.imgsz, base_model=args.base_model)
