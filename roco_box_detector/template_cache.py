"""Template reading and caching. Loads all templates once at startup."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from image_utils import imread_chinese, preprocess_image, make_gaussian_mask


@dataclass
class TemplateItem:
    path: str
    label: str
    image_color: np.ndarray
    image_gray: np.ndarray
    image_canny: Optional[np.ndarray] = None
    mask: Optional[np.ndarray] = None  # Gaussian weight mask (pattern only)


@dataclass
class TemplateGroup:
    label: str
    threshold: float
    scale_min: float
    scale_max: float
    scale_steps: int
    use_grayscale: bool
    use_canny: bool
    items: List[TemplateItem] = field(default_factory=list)


class TemplateCache:
    """Loads and caches all templates at startup. Templates are read once and reused across frames."""

    def __init__(self, config: dict):
        self.anchor_group: Optional[TemplateGroup] = None
        self.pattern_groups: Dict[str, TemplateGroup] = {}
        self.pattern_groups_2: Dict[str, TemplateGroup] = {}
        self._load_all(config)

    def _load_all(self, config: dict) -> None:
        self.anchor_group = self._load_group(
            config["anchor"]["templates"],
            config["anchor"]["label"],
            config["anchor"]["threshold"],
            config["anchor"]["scale_min"],
            config["anchor"]["scale_max"],
            config["anchor"]["scale_steps"],
            config["anchor"]["use_grayscale"],
            config["anchor"]["use_canny"],
            with_mask=False,
        )

        for name, pcfg in config.get("patterns", {}).items():
            group = self._load_group(
                pcfg["templates"],
                name,
                pcfg["threshold"],
                pcfg["scale_min"],
                pcfg["scale_max"],
                pcfg["scale_steps"],
                pcfg["use_grayscale"],
                pcfg["use_canny"],
                with_mask=True,
            )
            self.pattern_groups[name] = group

        for name, pcfg in config.get("patterns_2", {}).items():
            group = self._load_group(
                pcfg["templates"],
                name,
                pcfg["threshold"],
                pcfg["scale_min"],
                pcfg["scale_max"],
                pcfg["scale_steps"],
                pcfg["use_grayscale"],
                pcfg["use_canny"],
                with_mask=True,
            )
            self.pattern_groups_2[name] = group

    def _load_group(
        self,
        paths: List[str],
        label: str,
        threshold: float,
        scale_min: float,
        scale_max: float,
        scale_steps: int,
        use_grayscale: bool,
        use_canny: bool,
        with_mask: bool = False,
    ) -> TemplateGroup:
        group = TemplateGroup(
            label=label,
            threshold=threshold,
            scale_min=scale_min,
            scale_max=scale_max,
            scale_steps=scale_steps,
            use_grayscale=use_grayscale,
            use_canny=use_canny,
        )
        for p in paths:
            item = self._load_item(p, label, use_grayscale, use_canny, with_mask)
            if item is not None:
                group.items.append(item)
            else:
                print(f"[WARN] Failed to load template: {p}")
        return group

    def _load_item(
        self, path: str, label: str, use_grayscale: bool, use_canny: bool,
        with_mask: bool = False,
    ) -> Optional[TemplateItem]:
        img = imread_chinese(path)
        if img is None:
            return None
        gray = preprocess_image(img, use_grayscale=True, use_canny=False)
        canny = preprocess_image(img, use_grayscale=False, use_canny=True) if use_canny else None
        mask = make_gaussian_mask(img.shape[1], img.shape[0]) if with_mask else None
        return TemplateItem(
            path=path,
            label=label,
            image_color=img,
            image_gray=gray,
            image_canny=canny,
            mask=mask,
        )

    def get_anchor_templates(self) -> Optional[TemplateGroup]:
        return self.anchor_group

    def get_pattern_groups(self) -> Dict[str, TemplateGroup]:
        return self.pattern_groups

    def get_pattern_groups_2(self) -> Dict[str, TemplateGroup]:
        return self.pattern_groups_2

    @property
    def anchor_count(self) -> int:
        if self.anchor_group is None:
            return 0
        return len(self.anchor_group.items)

    @property
    def pattern_count(self) -> int:
        return sum(len(g.items) for g in self.pattern_groups.values())

    @property
    def pattern_count_2(self) -> int:
        return sum(len(g.items) for g in self.pattern_groups_2.values())

    def reload(self, config: dict) -> None:
        """Reload all templates and groups from a new config dict."""
        self.anchor_group = None
        self.pattern_groups.clear()
        self.pattern_groups_2.clear()
        self._load_all(config)
        cnt2 = self.pattern_count_2
        print(f"[Cache] Reloaded: {self.anchor_count} anchor templates, "
              f"{self.pattern_count} pattern templates across "
              f"{len(self.pattern_groups)} groups"
              + (f", {cnt2} roi2 templates across "
                 f"{len(self.pattern_groups_2)} groups" if cnt2 else ""))
