"""Sequence frame data and sharpness calculation."""

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


@dataclass
class SequenceFrame:
    index: int
    timestamp: float
    roi_image: np.ndarray
    sub_roi_image: np.ndarray
    anchor_box: Tuple[int, int, int, int]
    sub_roi_box: Tuple[int, int, int, int]
    sharpness: float = 0.0
    avg_similarity: float = 0.0
    sub_roi_image_2: Optional[np.ndarray] = None
    sub_roi_box_2: Optional[Tuple[int, int, int, int]] = None

    def __hash__(self):
        return hash((self.index, self.timestamp))


# ── sharpness ────────────────────────────────────────────────────────

def calculate_sharpness(image: np.ndarray) -> float:
    """Laplacian variance — higher = sharper."""
    if image is None or image.size == 0:
        return 0.0
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())
