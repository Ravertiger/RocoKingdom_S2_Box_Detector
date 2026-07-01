"""Debug visualization: draw boxes, save debug images, throttled logging."""

import cv2
import numpy as np
import os
import time
from datetime import datetime
from typing import Optional, Tuple

from image_utils import resolve_path


class DebugDrawer:
    """Handles drawing detection boxes and saving debug frames."""

    def __init__(self, config: dict):
        self.config = config
        self.debug = config.get("debug", {})
        self.enabled = self.debug.get("enabled", True)
        self.output_dir = resolve_path(
            self.debug.get("debug_output_dir", "debug_output"))
        self.save_interval = self.debug.get("save_every_n_seconds", 3)
        self._last_save_time = 0.0
        os.makedirs(self.output_dir, exist_ok=True)

    def draw_boxes(
        self,
        frame: np.ndarray,
        anchor_box: Optional[Tuple[int, int, int, int]] = None,
        sub_roi_box: Optional[Tuple[int, int, int, int]] = None,
        sub_roi_box_2: Optional[Tuple[int, int, int, int]] = None,
        icon_roi_box: Optional[Tuple[int, int, int, int]] = None,
        anchor_score: float = 0.0,
    ) -> np.ndarray:
        """Draw detection boxes on a debug copy of the frame."""
        if not self.enabled or frame is None:
            return frame

        debug = frame.copy()

        if self.debug.get("draw_anchor_box") and anchor_box is not None:
            x, y, w, h = anchor_box
            cv2.rectangle(debug, (x, y), (x + w, y + h), (255, 0, 0), 2)
            cv2.putText(debug, f"anchor {anchor_score:.2f}", (x, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)

        if self.debug.get("draw_sub_roi_box") and sub_roi_box is not None:
            x, y, w, h = sub_roi_box
            cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 255, 255), 2)
            cv2.putText(debug, "ROI1", (x, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

        if self.debug.get("draw_sub_roi_box") and sub_roi_box_2 is not None:
            x, y, w, h = sub_roi_box_2
            cv2.rectangle(debug, (x, y), (x + w, y + h), (0, 200, 255), 2)
            cv2.putText(debug, "ROI2", (x, y - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)

        if icon_roi_box is not None:
            x, y, w, h = icon_roi_box
            cv2.rectangle(debug, (x, y), (x + w, y + h), (255, 0, 255), 1)
            cv2.putText(debug, "ICON ROI", (x, max(12, y - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 0, 255), 1)

        # Calibration overlay: real-time coordinates for quick ratio tuning.
        lines = [
            f"A  {self._fmt_box(anchor_box)}  s={anchor_score:.2f}",
            f"R1 {self._fmt_box(sub_roi_box)}",
            f"R2 {self._fmt_box(sub_roi_box_2)}",
            f"IC {self._fmt_box(icon_roi_box)}",
        ]
        panel_h = 18 * len(lines) + 8
        panel_w = 390
        y0 = max(0, debug.shape[0] - panel_h - 6)
        cv2.rectangle(debug, (6, y0),
                      (min(debug.shape[1] - 6, 6 + panel_w), y0 + panel_h),
                      (0, 0, 0), -1)
        for i, line in enumerate(lines):
            y = y0 + 18 + i * 18
            cv2.putText(debug, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (220, 220, 220), 1)

        return debug

    @staticmethod
    def _fmt_box(box: Optional[Tuple[int, int, int, int]]) -> str:
        if box is None:
            return "-"
        x, y, w, h = box
        return f"x={x} y={y} w={w} h={h}"

    def maybe_save(self, frame: np.ndarray, tag: str = "") -> None:
        """Save debug frame, throttled by save_interval."""
        if not self.enabled or not self.debug.get("save_debug_frames"):
            return
        now = time.time()
        if now - self._last_save_time < self.save_interval:
            return
        self._last_save_time = now
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"debug_{ts}{'_' + tag if tag else ''}.png"
        path = os.path.join(self.output_dir, name)
        _, buf = cv2.imencode('.png', frame)
        buf.tofile(path)


class ThrottledLogger:
    """Logs messages at most once every N calls."""

    def __init__(self, every_n: int = 10):
        self.every_n = every_n
        self._counter = 0

    def log(self, msg: str, force: bool = False) -> None:
        if force:
            print(msg)
            return
        self._counter += 1
        if self._counter % self.every_n == 0:
            print(msg)

    def reset(self):
        self._counter = 0
