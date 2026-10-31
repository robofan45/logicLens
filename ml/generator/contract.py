"""Bridge to ``contract/``: the detector class table and the reference LLT parser.

Nothing is copied from contract/: classes.json is read at import time and the reference parser
(contract/python/logiclens_ladder.py) is imported from its own folder, so a contract change is
picked up immediately (or breaks the tests). Set LOGICLENS_CONTRACT_DIR to use another checkout.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

ML_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = ML_DIR.parent
CONTRACT_DIR = Path(os.environ.get("LOGICLENS_CONTRACT_DIR", str(REPO_DIR / "contract"))).resolve()
CLASSES_PATH = CONTRACT_DIR / "classes.json"

_PARSER_DIR = str(CONTRACT_DIR / "python")
if _PARSER_DIR not in sys.path:
    sys.path.insert(0, _PARSER_DIR)

import logiclens_ladder as llt  # noqa: E402  - the reference parser, imported (not vendored)


@dataclass(frozen=True)
class ClassInfo:
    id: int
    name: str
    mnemonic: Optional[str]
    structural: Optional[str]


def load_classes(path: Path = CLASSES_PATH) -> List[ClassInfo]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    classes = [ClassInfo(int(c["id"]), str(c["name"]), c.get("mnemonic"), c.get("structural"))
               for c in data["classes"]]
    if [c.id for c in classes] != list(range(int(data["nc"]))):
        raise ValueError(f"{path}: class ids must be 0..nc-1 in order")
    return classes


CLASSES: List[ClassInfo] = load_classes()
NC: int = len(CLASSES)
NAMES: List[str] = [c.name for c in CLASSES]
ID_BY_NAME: Dict[str, int] = {c.name: c.id for c in CLASSES}
ID_BY_MNEMONIC: Dict[str, int] = {c.mnemonic: c.id for c in CLASSES if c.mnemonic}
MNEMONIC_BY_ID: Dict[int, str] = {v: k for k, v in ID_BY_MNEMONIC.items()}
SYMBOL_IDS: List[int] = sorted(ID_BY_MNEMONIC.values())
_BY_STRUCT = {c.structural: c.id for c in CLASSES if c.structural and c.structural != "deprecated"}
DEPRECATED_IDS = frozenset(c.id for c in CLASSES if c.structural == "deprecated")
BRANCH_START: int = _BY_STRUCT["branch_left"]
BRANCH_END: int = _BY_STRUCT["branch_right"]
RAIL_LEFT: int = _BY_STRUCT["rail_left"]
RAIL_RIGHT: int = _BY_STRUCT["rail_right"]
STRUCTURAL_IDS = frozenset((BRANCH_START, BRANCH_END, RAIL_LEFT, RAIL_RIGHT))
EMITTED_IDS = frozenset(SYMBOL_IDS) | STRUCTURAL_IDS

# Instructions of the LLT grammar with no detector class: the sampler never emits them, because a
# rendered instruction without a label would teach the detector to ignore it.
UNLABELLED_MNEMONICS = frozenset(m for m in llt.SPEC if m not in ID_BY_MNEMONIC)


def class_id(mnemonic: str) -> int:
    return ID_BY_MNEMONIC[mnemonic]


def parse(text: str):
    """Parse LLT with the reference parser (never raises)."""
    return llt.parse_program(text)


def canonical(text: str) -> str:
    """parse -> print_program (with comments)."""
    return llt.print_program(llt.parse_program(text).rungs)
