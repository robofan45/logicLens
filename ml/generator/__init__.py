"""LogicLens synthetic ladder-diagram generator (dataset v2).

Pipeline: ``sampler`` (random but realistic LLT programs) -> ``layout`` (contract section 6
geometry) -> ``render`` (visual styles, tight symbol boxes from the actual ink) -> ``augment``
(photo/scan effects with exact box transforms) -> ``dataset`` (Ultralytics layout + metadata).
"""

__version__ = "2.0.0"
