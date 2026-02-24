import logging
from typing import List

from models.schemas import BoundingBox, LadderBranch, LadderProgram, LadderRung

logger = logging.getLogger(__name__)

RUNG_Y_THRESHOLD = 30  # pixels – elements within this vertical distance are on the same rung

_OUTPUT_TYPES = {
    "Output_Coil",
    "Negated_Coil",
    "Set_Coil",
    "Reset_Coil",
    "TON_Timer",
    "TOF_Timer",
    "RTO_Timer",
    "TP_Timer",
    "CTU_Counter",
    "CTD_Counter",
    "CTUD_Counter",
    "RES_Reset",
    "ADD_Addition",
    "SUB_Subtraction",
    "MUL_Multiplication",
    "DIV_Division",
    "MOV_Move",
}

_RAIL_TYPES = {"Power_Rail_Left", "Power_Rail_Right"}
_BRANCH_START = "Branch_Start"
_BRANCH_END = "Branch_End"


def _box_center(box: BoundingBox):
    cx = (box.x1 + box.x2) / 2.0
    cy = (box.y1 + box.y2) / 2.0
    return cx, cy


def _cluster_by_y(detections: List[BoundingBox]) -> List[List[BoundingBox]]:
    """Group detections into rows using a simple Y-proximity threshold."""
    if not detections:
        return []

    sorted_dets = sorted(detections, key=lambda b: (b.y1 + b.y2) / 2.0)
    clusters: List[List[BoundingBox]] = []
    current_cluster: List[BoundingBox] = [sorted_dets[0]]
    current_cy = (sorted_dets[0].y1 + sorted_dets[0].y2) / 2.0

    for det in sorted_dets[1:]:
        cy = (det.y1 + det.y2) / 2.0
        if abs(cy - current_cy) <= RUNG_Y_THRESHOLD:
            current_cluster.append(det)
        else:
            clusters.append(current_cluster)
            current_cluster = [det]
            current_cy = cy

    clusters.append(current_cluster)
    return clusters


def _box_to_element(box: BoundingBox, element_index: int) -> dict:
    """Convert a BoundingBox to a minimal element dict for a LadderRung."""
    cx, cy = _box_center(box)
    return {
        "id": f"elem_{element_index}",
        "element_type": box.class_name if box.class_name else "Unknown",
        "address": "",
        "label": box.class_name if box.class_name else "Unknown",
        "position_x": cx,
        "position_y": cy,
        "confidence": box.confidence,
        "bounding_box": {
            "x1": box.x1,
            "y1": box.y1,
            "x2": box.x2,
            "y2": box.y2,
            "confidence": box.confidence,
            "class_name": box.class_name,
            "class_id": box.class_id,
        },
        "properties": {},
    }


def parse_ladder_program(
    detections: List[BoundingBox],
    image_width: int,
    image_height: int,
) -> LadderProgram:
    """
    Parse YOLO bounding boxes into a structured LadderProgram.

    Steps:
    1. Filter out power rail detections (or infer from image edges).
    2. Cluster remaining elements by Y-coordinate into rungs.
    3. Within each rung sort left-to-right by X.
    4. Detect parallel branches via Branch_Start / Branch_End elements.
    5. Separate output elements from input/logic elements.
    """
    if not detections:
        return LadderProgram()

    # Separate rails from logic elements
    rail_dets = [d for d in detections if d.class_name in _RAIL_TYPES]
    logic_dets = [d for d in detections if d.class_name not in _RAIL_TYPES]

    # Infer left power rail X boundary
    if rail_dets:
        left_rails = [d for d in rail_dets if d.class_name == "Power_Rail_Left"]
        right_rails = [d for d in rail_dets if d.class_name == "Power_Rail_Right"]
        left_x = max((d.x2 for d in left_rails), default=0.0)
        right_x = min((d.x1 for d in right_rails), default=float(image_width))
    else:
        left_x = image_width * 0.05
        right_x = image_width * 0.95

    # Filter elements within rail boundaries
    in_bounds = [
        d for d in logic_dets
        if _box_center(d)[0] >= left_x and _box_center(d)[0] <= right_x
    ]

    clusters = _cluster_by_y(in_bounds)
    rungs: List[LadderRung] = []
    elem_index = 0

    for rung_num, cluster in enumerate(clusters, start=1):
        # Sort left-to-right
        cluster_sorted = sorted(cluster, key=lambda b: (b.x1 + b.x2) / 2.0)

        series_elements: List[dict] = []
        parallel_branches: List[LadderBranch] = []
        outputs: List[dict] = []

        in_branch = False
        current_branch_elements: List[dict] = []

        for det in cluster_sorted:
            elem_dict = _box_to_element(det, elem_index)
            elem_index += 1
            etype = det.class_name

            if etype == _BRANCH_START:
                in_branch = True
                current_branch_elements = []
            elif etype == _BRANCH_END:
                if in_branch:
                    parallel_branches.append(LadderBranch(elements=current_branch_elements))
                    current_branch_elements = []
                    in_branch = False
            elif etype in _OUTPUT_TYPES:
                outputs.append(elem_dict)
            elif in_branch:
                current_branch_elements.append(elem_dict)
            else:
                series_elements.append(elem_dict)

        # If a branch was opened but never closed, flush it
        if in_branch and current_branch_elements:
            parallel_branches.append(LadderBranch(elements=current_branch_elements))

        rungs.append(
            LadderRung(
                rung_number=rung_num,
                series_elements=series_elements,
                parallel_branches=parallel_branches,
                outputs=outputs,
            )
        )

    return LadderProgram(rungs=rungs)
