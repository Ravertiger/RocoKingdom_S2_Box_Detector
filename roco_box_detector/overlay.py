"""PyQt5 frameless overlay windows: status bar and result history panel."""

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout,
    QPushButton, QScrollArea, QSizeGrip,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPoint
from PyQt5.QtGui import QFont, QColor


class OverlaySignals(QObject):
    update_text = pyqtSignal(str)
    update_style = pyqtSignal(str)
    start_match_timer = pyqtSignal()
    stop_match_timer = pyqtSignal()
    start_debounce = pyqtSignal()      # thread-safe debounce trigger
    close_app = pyqtSignal()
    open_settings = pyqtSignal()
    toggle_debug_save = pyqtSignal(bool)
    toggle_preview = pyqtSignal(bool)
    toggle_debug_overlay = pyqtSignal(bool)
    request_re_select = pyqtSignal()


class Overlay(QWidget):
    """Frameless, topmost overlay with customizable duration, position, size, and colors."""

    def __init__(self, config: dict):
        super().__init__()
        self.signals = OverlaySignals()
        ov = config.get("overlay", {})

        self._width = ov.get("width", 680)
        self._height = ov.get("height", 64)
        self._position = ov.get("position", "top")
        self._normal_text = ov.get("normal_text", "● 运行中")
        self._matched_prefix = ov.get("matched_prefix", "识别到：")
        self._match_show_seconds = ov.get("match_show_seconds", 3.0)
        self._sampling_text = ov.get("sampling_text", "正在采样识别...")

        self._bg_color = ov.get("bg_color", "rgba(0, 0, 0, 180)")
        self._text_color = ov.get("text_color", "#ffffff")
        self._matched_text_color = ov.get("matched_text_color", "#00ff88")

        self._debug_saving = config.get("debug", {}).get("save_debug_frames", False)
        self._preview_showing = config.get("debug", {}).get("show_preview_window", False)

        # Timer created in main thread; all start/stop via signal slots
        self._reset_timer = QTimer()
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._on_timer_fire)

        # Debounce timer for rapid-fire show_match calls — only last one wins
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._apply_debounced)
        self._pending_text = ""
        self._pending_style = ""

        self._init_ui()

        # Force-topmost timer for fullscreen games
        self._topmost_timer = QTimer()
        self._topmost_timer.setInterval(2000)
        self._topmost_timer.timeout.connect(self._force_topmost)
        self._topmost_timer.start()

        # Wire signals → slots (all slot execution on main thread)
        self.signals.update_text.connect(self._label.setText)
        self.signals.update_style.connect(self._label.setStyleSheet)
        self.signals.start_match_timer.connect(self._start_timer_slot)
        self.signals.stop_match_timer.connect(self._reset_timer.stop)
        self.signals.start_debounce.connect(self._start_debounce_slot)
        self.signals.close_app.connect(self._on_close)

    def _make_stylesheet(self) -> str:
        return (
            f"RocoDetectorOverlay {{"
            f"  background-color: {self._bg_color};"
            f"  border-radius: 8px;"
            f"}}"
            f"QLabel {{"
            f"  color: {self._text_color};"
            f"  font-size: 16px;"
            f"}}"
            f"QPushButton {{"
            f"  color: #888;"
            f"  background: transparent;"
            f"  border: none;"
            f"  font-size: 14px;"
            f"  padding: 0 6px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  color: #fff;"
            f"}}"
        )

    def _init_ui(self):
        self.setWindowTitle("Roco Detector")
        self.setObjectName("RocoDetectorOverlay")
        self.setFixedSize(self._width, self._height)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet(self._make_stylesheet())

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 0, 8, 0)

        self._label = QLabel(self._normal_text)
        self._label.setFont(QFont("Microsoft YaHei", 11))
        self._label.setObjectName("statusLabel")
        layout.addWidget(self._label)
        layout.addStretch()

        self._debug_btn = QPushButton("⬤" if self._debug_saving else "○")
        self._debug_btn.setFixedSize(28, 24)
        self._debug_btn.setToolTip("调试截图保存开关")
        self._debug_btn.clicked.connect(self._toggle_debug_save)
        self._update_debug_btn_style()
        layout.addWidget(self._debug_btn)

        # Preview window toggle
        self._preview_btn = QPushButton("🔍" if self._preview_showing else "◌")
        self._preview_btn.setFixedSize(26, 24)
        self._preview_btn.setToolTip("预览窗口开关")
        self._preview_btn.clicked.connect(self._toggle_preview)
        self._update_preview_btn_style()
        layout.addWidget(self._preview_btn)

        # Debug box overlay toggle
        self._debug_overlay_enabled = False
        self._debug_overlay_btn = QPushButton("▣")
        self._debug_overlay_btn.setFixedSize(26, 24)
        self._debug_overlay_btn.setToolTip("画面覆盖框开关")
        self._debug_overlay_btn.clicked.connect(self._toggle_debug_overlay)
        self._update_debug_overlay_btn_style()
        layout.addWidget(self._debug_overlay_btn)

        # Manual ROI re-select
        reselect_btn = QPushButton("↻")
        reselect_btn.setFixedSize(24, 24)
        reselect_btn.setToolTip("重新框选游戏区域")
        reselect_btn.clicked.connect(lambda: self.signals.request_re_select.emit())
        reselect_btn.setStyleSheet(
            "QPushButton { color: #888; background: transparent; border: none; "
            "font-size: 13px; padding: 0 2px; }"
            "QPushButton:hover { color: #fff; }"
        )
        layout.addWidget(reselect_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(24, 24)
        settings_btn.setToolTip("设置面板")
        settings_btn.clicked.connect(lambda: self.signals.open_settings.emit())
        layout.addWidget(settings_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self._on_close)
        layout.addWidget(close_btn)

        self.setLayout(layout)
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.geometry()
        if self._position == "top":
            x = (geom.width() - self._width) // 2
            y = 10
        elif self._position == "bottom":
            x = (geom.width() - self._width) // 2
            y = geom.height() - self._height - 40
        else:
            x = (geom.width() - self._width) // 2
            y = (geom.height() - self._height) // 2
        self.move(x, y)

    # ── public API (thread-safe — only emits signals) ──────────────────

    def show_match(self, label: str, score: float, votes=None) -> None:
        """Called from any thread. If votes is None/empty, no vote info is displayed."""
        vote_part = f"  票数 {votes}" if votes else ""
        text = f"{self._matched_prefix}{label} {score:.2f}{vote_part}"
        style = f"QLabel {{ color: {self._matched_text_color}; font-size: 16px; }}"
        self._pending_text = text
        self._pending_style = style
        self.signals.stop_match_timer.emit()
        self.signals.start_debounce.emit()

    def clear_match_state(self) -> None:
        """Reset all display state."""
        self._debounce_timer.stop()
        self._pending_text = ""
        self._pending_style = ""
        self.signals.stop_match_timer.emit()
        self._apply_normal_style()

    def show_sampling(self) -> None:
        """Show sampling-in-progress text immediately (cancels pending debounce)."""
        self._pending_text = ""
        self.signals.stop_match_timer.emit()
        self._debounce_timer.stop()      # safe — only called from main thread via callback
        self.signals.update_text.emit(self._sampling_text)
        self.signals.update_style.emit(
            f"QLabel {{ color: {self._text_color}; font-size: 16px; }}"
        )

    def show_no_match(self) -> None:
        """Show 'not matched' feedback immediately (cancels pending debounce)."""
        self._pending_text = ""
        self.signals.stop_match_timer.emit()
        self._debounce_timer.stop()      # safe — only called from main thread via callback
        self.signals.update_text.emit("未识别到目标标志")
        self.signals.update_style.emit(
            f"QLabel {{ color: {self._text_color}; font-size: 16px; }}"
        )
        self.signals.start_match_timer.emit()

    def _start_debounce_slot(self):
        """Starts the actual debounce QTimer on the main thread."""
        self._debounce_timer.start(300)

    def _apply_debounced(self):
        """Called 300ms after the last show_match — actually commit the display."""
        if self._pending_text:
            self.signals.update_text.emit(self._pending_text)
            self.signals.update_style.emit(self._pending_style)
            self.signals.start_match_timer.emit()
            self._pending_text = ""

    def reset_to_normal(self) -> None:
        """Explicitly reset (used when settings change, etc.)."""
        self.signals.stop_match_timer.emit()
        self._apply_normal_style()

    def _apply_normal_style(self):
        self.signals.update_text.emit(self._normal_text)
        self.signals.update_style.emit(
            f"QLabel {{ color: {self._text_color}; font-size: 16px; }}"
        )

    # ── timer slot (runs on main thread) ───────────────────────────────

    def _start_timer_slot(self):
        """Start (or restart) the single-shot reset timer. Runs on main thread."""
        self._reset_timer.start(int(self._match_show_seconds * 1000))

    def _on_timer_fire(self):
        """Timer expired — no match seen for match_show_seconds."""
        self._apply_normal_style()

    # ── internal ───────────────────────────────────────────────────────

    def _toggle_debug_save(self):
        self._debug_saving = not self._debug_saving
        self._update_debug_btn_style()
        self.signals.toggle_debug_save.emit(self._debug_saving)

    def _toggle_preview(self):
        self._preview_showing = not self._preview_showing
        self._update_preview_btn_style()
        self.signals.toggle_preview.emit(self._preview_showing)

    def _update_preview_btn_style(self):
        if self._preview_showing:
            self._preview_btn.setText("🔍")
            self._preview_btn.setStyleSheet(
                "QPushButton { color: #66aaff; background: transparent; border: none; "
                "font-size: 12px; padding: 0 2px; }"
                "QPushButton:hover { color: #88ccff; }"
            )
        else:
            self._preview_btn.setText("◌")
            self._preview_btn.setStyleSheet(
                "QPushButton { color: #666; background: transparent; border: none; "
                "font-size: 14px; padding: 0 2px; }"
                "QPushButton:hover { color: #aaa; }"
            )

    def _toggle_debug_overlay(self):
        self._debug_overlay_enabled = not self._debug_overlay_enabled
        self._update_debug_overlay_btn_style()
        self.signals.toggle_debug_overlay.emit(self._debug_overlay_enabled)

    def _update_debug_overlay_btn_style(self):
        if self._debug_overlay_enabled:
            self._debug_overlay_btn.setText("▣")
            self._debug_overlay_btn.setStyleSheet(
                "QPushButton { color: #ff8844; background: transparent; border: none; "
                "font-size: 12px; padding: 0 2px; }"
                "QPushButton:hover { color: #ffaa66; }"
            )
        else:
            self._debug_overlay_btn.setText("□")
            self._debug_overlay_btn.setStyleSheet(
                "QPushButton { color: #666; background: transparent; border: none; "
                "font-size: 12px; padding: 0 2px; }"
                "QPushButton:hover { color: #aaa; }"
            )

    def _update_debug_btn_style(self):
        if self._debug_saving:
            self._debug_btn.setText("⬤")
            self._debug_btn.setStyleSheet(
                "QPushButton { color: #e04040; background: transparent; border: none; "
                "font-size: 14px; padding: 0 4px; }"
                "QPushButton:hover { color: #ff6666; }"
            )
        else:
            self._debug_btn.setText("○")
            self._debug_btn.setStyleSheet(
                "QPushButton { color: #666; background: transparent; border: none; "
                "font-size: 14px; padding: 0 4px; }"
                "QPushButton:hover { color: #aaa; }"
            )

    def _on_close(self):
        self.signals.close_app.emit()

    def show_overlay(self):
        self.show()

    def _force_topmost(self):
        """Windows: forcefully keep window on top using SetWindowPos."""
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)
        except Exception:
            pass

    # ── Setters for settings panel ──

    def set_size(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self.setFixedSize(width, height)
        self._center_on_screen()

    def set_position(self, pos: str) -> None:
        self._position = pos
        self._center_on_screen()

    def set_normal_text(self, text: str) -> None:
        self._normal_text = text

    def set_matched_prefix(self, prefix: str) -> None:
        self._matched_prefix = prefix

    def set_match_show_seconds(self, seconds: float) -> None:
        self._match_show_seconds = max(0.5, seconds)

    def set_debug_saving(self, enabled: bool):
        self._debug_saving = enabled
        self._update_debug_btn_style()

    def reload_config(self, cfg: dict) -> None:
        ov = cfg.get("overlay", {})
        self.set_size(ov.get("width", self._width), ov.get("height", self._height))
        self.set_position(ov.get("position", self._position))
        self.set_normal_text(ov.get("normal_text", self._normal_text))
        self.set_matched_prefix(ov.get("matched_prefix", self._matched_prefix))
        self.set_match_show_seconds(ov.get("match_show_seconds", self._match_show_seconds))
        self._sampling_text = ov.get("sampling_text", self._sampling_text)
        self._bg_color = ov.get("bg_color", self._bg_color)
        self._text_color = ov.get("text_color", self._text_color)
        self._matched_text_color = ov.get("matched_text_color", self._matched_text_color)
        self.setStyleSheet(self._make_stylesheet())
        # Reset to normal display
        self.signals.stop_match_timer.emit()
        self._apply_normal_style()


# ── Result History Overlay ───────────────────────────────────────────

class _RTOSignals(QObject):
    add_result = pyqtSignal(str)
    clear_results = pyqtSignal()
    position_changed = pyqtSignal(int, int)
    size_changed = pyqtSignal(int, int)
    open_settings = pyqtSignal()


def _parse_rgba(s: str) -> QColor:
    s = s.strip()
    if s.startswith("rgba("):
        parts = s[5:-1].split(",")
        if len(parts) == 4:
            return QColor(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    return QColor(s)


class ResultTextOverlay(QWidget):
    """Semi-transparent scrollable history panel.

    Widget tree:
      ResultTextOverlay  (frameless, transparent, topmost)
       └─ #RTO_panel    (QWidget — semi-transparent bg, border, radius)
            ├─ header   (QWidget — title, count, clear btn)
            ├─ QScrollArea (transparent, scrollbar styled)
            │    └─ content (QWidget — record QLabels)
            └─ [QSizeGrip at outer level, bottom-right]
    """

    _HEADER_H = 28

    def __init__(self, config: dict):
        super().__init__()
        self.config = config  # full config for ROI categorization
        self._signals = _RTOSignals()
        cfg = config.get("result_text_overlay", {})

        # Force-topmost timer for fullscreen games
        self._topmost_timer = QTimer()
        self._topmost_timer.setInterval(2000)
        self._topmost_timer.timeout.connect(self._force_topmost)
        self._topmost_timer.start()

        self._enabled = cfg.get("enabled", True)
        self._font_family = cfg.get("font_family", "Microsoft YaHei")
        self._font_size = cfg.get("font_size", 28)
        self._font_size_step = cfg.get("font_size_step", 3)
        self._min_font_size = cfg.get("min_font_size", 14)
        self._default_color = QColor(cfg.get("default_color", "#FFD700"))
        self._outline_color = QColor(cfg.get("outline_color", "#000000"))
        self._outline_width = cfg.get("outline_width", 2)
        self._item_spacing = cfg.get("item_spacing", 42)
        self._max_items = cfg.get("max_items", 100)
        self._text_template = cfg.get("text_template", "{label}")
        self._click_through = cfg.get("click_through", False)
        self._show_counts = cfg.get("show_counts", True)
        self._count_font_size = cfg.get("count_font_size", 9)
        self._label_colors: dict = cfg.get("label_colors", {})

        self._bg_color = _parse_rgba(cfg.get("background_color", "rgba(0,0,0,150)"))
        self._border_color = _parse_rgba(cfg.get("border_color", "rgba(255,255,255,60)"))
        self._border_radius = cfg.get("border_radius", 12)
        self._padding = cfg.get("padding", 10)
        self._title_text = cfg.get("title", "识别记录")
        self._scrollbar_width = cfg.get("scrollbar_width", 6)
        self._min_w = cfg.get("min_width", 180)
        self._min_h = cfg.get("min_height", 120)

        screen = QApplication.primaryScreen()
        geom = screen.geometry() if screen else None
        self._width = cfg.get("width", 280)
        self._height = cfg.get("height", 360)
        # Auto-position: right edge, vertically centered
        if geom:
            def_x = max(0, geom.width() - self._width - 30)
            def_y = max(0, (geom.height() - self._height) // 2)
        else:
            def_x, def_y = 800, 300
        config_x = cfg.get("x", def_x)
        config_y = cfg.get("y", def_y)
        # If saved position is off-screen, fall back to auto
        if geom and (config_x < -500 or config_x > geom.width() + 200
                     or config_y < -500 or config_y > geom.height() + 200):
            print(f"[ResultText] Saved position ({config_x},{config_y}) off-screen, "
                  f"using ({def_x},{def_y})")
            self._pos_x = def_x
            self._pos_y = def_y
        else:
            self._pos_x = config_x
            self._pos_y = config_y

        self._records: list = []
        self._record_labels: list = []

        self._dragging = False
        self._drag_start = QPoint()

        self._build_ui()
        self.resize(self._width, self._height)
        self.move(self._pos_x, self._pos_y)
        self._update_click_through()

        self._signals.add_result.connect(self._do_add)
        self._signals.clear_results.connect(self._do_clear)

        if self._enabled:
            QWidget.show(self)  # auto-show empty panel on startup

    # ── build ─────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("ResultHistory")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMinimumSize(self._min_w, self._min_h)

        # Outer layout → pins panel to outer edges
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── panel container (has the bg / border / radius) ──
        self._panel = QWidget()
        self._panel.setObjectName("RTO_panel")
        self._panel.setAttribute(Qt.WA_StyledBackground, True)
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # ── header ──
        header = QWidget()
        header.setObjectName("RTO_header")
        header.setFixedHeight(self._HEADER_H + self._padding)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(self._padding, 0, self._padding, 0)
        hl.setSpacing(4)

        self._title_lbl = QLabel(self._title_text)
        self._title_lbl.setStyleSheet("color: #aaa; font-size: 11px; background: transparent;")
        hl.addWidget(self._title_lbl)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #666; font-size: 10px; background: transparent;")
        hl.addWidget(self._count_lbl)

        hl.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(32, 22)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setToolTip("清空识别记录")
        clear_btn.setStyleSheet(
            "QPushButton { color: #888; background: transparent; border: none; "
            "font-size: 11px; }"
            "QPushButton:hover { color: #fff; }"
        )
        clear_btn.clicked.connect(self._do_clear)
        hl.addWidget(clear_btn)

        gear_btn = QPushButton("⚙")
        gear_btn.setFixedSize(22, 22)
        gear_btn.setCursor(Qt.PointingHandCursor)
        gear_btn.setToolTip("设置面板")
        gear_btn.setStyleSheet(
            "QPushButton { color: #888; background: transparent; border: none; "
            "font-size: 11px; }"
            "QPushButton:hover { color: #fff; }"
        )
        gear_btn.clicked.connect(lambda: self._signals.open_settings.emit())
        hl.addWidget(gear_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip("关闭面板")
        close_btn.setStyleSheet(
            "QPushButton { color: #888; background: transparent; border: none; "
            "font-size: 12px; }"
            "QPushButton:hover { color: #fff; }"
        )
        close_btn.clicked.connect(lambda: QWidget.hide(self))
        hl.addWidget(close_btn)

        panel_layout.addWidget(header)

        # ── QScrollArea ──
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QScrollArea.NoFrame)

        self._content = QWidget()
        self._content.setObjectName("RTO_content")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(
            self._padding, 0, self._padding, self._padding)
        self._content_layout.setSpacing(
            max(2, self._item_spacing - self._font_size - self._outline_width * 2))
        self._content_layout.addStretch()
        self._scroll.setWidget(self._content)

        panel_layout.addWidget(self._scroll, 1)

        # ── count footer ──
        self._count_footer = QLabel("")
        self._count_footer.setObjectName("RTO_footer")
        self._count_footer.setStyleSheet(
            f"color: #999; font-size: {self._count_font_size}px; "
            "background: transparent; padding: 0 4px;")
        self._count_footer.setWordWrap(True)
        panel_layout.addWidget(self._count_footer)

        outer.addWidget(self._panel)

        # ── QSizeGrip (on outer, bottom-right) ──
        self._size_grip = QSizeGrip(self)
        self._size_grip.setFixedSize(16, 16)
        self._size_grip.setStyleSheet("QSizeGrip { background: transparent; }")

        # ── stylesheets ──
        self._panel.setStyleSheet(self._panel_style())
        self._scroll.setStyleSheet(self._scroll_style())

    # ── stylesheets ───────────────────────────────────────────────────

    def _panel_style(self) -> str:
        bg = self._bg_color
        br = self._border_radius
        bc = self._border_color
        return (
            f"#RTO_panel {{"
            f"  background-color: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
            f"  border: 1px solid "
            f"rgba({bc.red()},{bc.green()},{bc.blue()},{bc.alpha()});"
            f"  border-radius: {br}px;"
            f"}}"
        )

    def _scroll_style(self) -> str:
        w = self._scrollbar_width
        return (
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background: transparent; }}"
            f"QScrollArea > QWidget > QWidget > QLabel {{ background: transparent; }}"
            f"QScrollBar:vertical {{"
            f"  background: transparent; width: {w}px; margin: 4px 2px 4px 2px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"  background: rgba(255,255,255,50); border-radius: {w//2}px;"
            f"  min-height: 30px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{"
            f"  background: rgba(255,255,255,150);"
            f"}}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{"
            f"  height: 0px;"
            f"}}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{"
            f"  background: transparent;"
            f"}}"
        )

    def _update_click_through(self):
        if self._click_through:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        else:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    # ── public API ────────────────────────────────────────────────────

    def _force_topmost(self):
        """Windows: forcefully keep window on top using SetWindowPos."""
        try:
            import ctypes
            hwnd = int(self.winId())
            # HWND_TOPMOST = -1, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            ctypes.windll.user32.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)
        except Exception:
            pass

    def add_result(self, label: str) -> None:
        if not self._enabled:
            return
        self._signals.add_result.emit(label)

    def clear_results(self) -> None:
        self._signals.clear_results.emit()

    # ── slots (main thread) ───────────────────────────────────────────

    def _do_add(self, label: str):
        self._records.append(label)
        if len(self._records) > self._max_items:
            self._records.pop(0)
            if self._record_labels:
                w = self._record_labels.pop(0)
                self._content_layout.removeWidget(w)
                w.deleteLater()

        lbl = self._make_record_label(label)
        self._record_labels.append(lbl)
        self._content_layout.insertWidget(
            self._content_layout.count() - 1, lbl)

        # Font size: newest (bottom) = full size, all above = one step smaller
        n = len(self._record_labels)
        for i, w in enumerate(self._record_labels):
            pos_from_bottom = n - 1 - i
            size = (self._font_size if pos_from_bottom == 0
                    else max(self._min_font_size,
                             self._font_size - self._font_size_step))
            font = w.font()
            font.setPointSize(size)
            w.setFont(font)

        self._count_lbl.setText(f"({len(self._records)})")
        self._update_count_footer()
        QWidget.show(self)
        QTimer.singleShot(20, self._scroll_to_bottom)

    def _update_count_footer(self):
        if not self._show_counts or not self._records:
            self._count_footer.setText("")
            return
        from collections import Counter

        # Split combined labels and categorize
        counts1 = Counter()
        counts2 = Counter()
        seen1 = {}
        ordered1 = []
        seen2 = {}
        ordered2 = []

        for combined in self._records:
            parts = combined.split(" + ")
            for p in parts:
                p = p.strip()
                if self._is_roi2_label(p):
                    if p not in seen2:
                        seen2[p] = True
                        ordered2.append(p)
                    counts2[p] += 1
                else:
                    if p not in seen1:
                        seen1[p] = True
                        ordered1.append(p)
                    counts1[p] += 1

        rows = []
        if ordered1:
            row = [f"<span style='color:#aaa'>ROI1:</span>"]
            for l in ordered1:
                c = self._label_color(l)
                row.append(
                    f"<span style='color:{c.name()}'>{l}×{counts1[l]}</span>")
            rows.append("&nbsp;&nbsp;".join(row))

        if ordered2:
            row = [f"<span style='color:#aaa'>ROI2:</span>"]
            for l in ordered2:
                c = self._label_color(l)
                row.append(
                    f"<span style='color:{c.name()}'>{l}×{counts2[l]}</span>")
            rows.append("&nbsp;&nbsp;".join(row))

        self._count_footer.setText(
            f"<html><body style='margin:0;padding:0'>"
            f"{'<br>'.join(rows)}</body></html>")

    def _is_roi2_label(self, label: str) -> bool:
        """Check if a label belongs to patterns_2 or is the roi_fallback text."""
        p2 = self.config.get("patterns_2", {})
        if label in p2:
            return True
        rto = self.config.get("result_text_overlay", {})
        fallback = rto.get("roi_fallback", "")
        return bool(fallback and label == fallback)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _do_clear(self):
        self._records.clear()
        for w in self._record_labels:
            self._content_layout.removeWidget(w)
            w.deleteLater()
        self._record_labels.clear()
        self._count_lbl.setText("")
        self._count_footer.setText("")

    def _make_record_label(self, label: str) -> QLabel:
        """Create a QLabel with per-pattern coloring for 'X + Y' combined labels."""
        fallback = self.config.get("result_text_overlay", {}).get("roi_fallback", "")
        parts = label.split(" + ")
        if len(parts) == 2:
            c1 = ("#888" if parts[0] == fallback
                  else self._label_color(parts[0]).name())
            c2 = ("#888" if parts[1] == fallback
                  else self._label_color(parts[1]).name())
            text = (f"<span style='color:{c1}'>{parts[0]}</span>"
                    f" <span style='color:#aaa'>+</span> "
                    f"<span style='color:{c2}'>{parts[1]}</span>")
        else:
            c = "#888" if label == fallback else self._label_color(label).name()
            text = f"<span style='color:{c}'>{label}</span>"

        lbl = QLabel(text)
        lbl.setTextFormat(1)  # Qt.RichText
        lbl.setFont(QFont(self._font_family, self._font_size))
        lbl.setStyleSheet(
            f"QLabel {{ background: transparent; "
            f"font-family: '{self._font_family}'; "
            f"font-size: {self._font_size}px; }}"
        )
        return lbl

    def _label_color(self, label: str) -> QColor:
        hex_str = self._label_colors.get(label)
        if hex_str:
            return QColor(hex_str)
        return self._default_color

    # ── drag (on header only) ─────────────────────────────────────────

    def _in_header(self, y: int) -> bool:
        return y <= self._HEADER_H + self._padding

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._in_header(event.y()):
            self._dragging = True
            self._drag_start = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            new_pos = event.globalPos() - self._drag_start
            self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._pos_x = self.x()
            self._pos_y = self.y()
            self._signals.position_changed.emit(self._pos_x, self._pos_y)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── resize ────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._width = self.width()
        self._height = self.height()
        if hasattr(self, '_size_grip'):
            self._size_grip.move(
                self.width() - self._size_grip.width() - 2,
                self.height() - self._size_grip.height() - 2)
        self._signals.size_changed.emit(self._width, self._height)

    # ── config reload ─────────────────────────────────────────────────

    def reload_config(self, config: dict):
        self.config = config  # update full config for ROI categorization
        cfg = config.get("result_text_overlay", {})
        old_cfg = config.get("result_text_overlay", {})  # snapshot before mutation
        self._enabled = cfg.get("enabled", self._enabled)
        self._font_family = cfg.get("font_family", self._font_family)
        self._font_size = cfg.get("font_size", self._font_size)
        self._font_size_step = cfg.get("font_size_step", self._font_size_step)
        self._min_font_size = cfg.get("min_font_size", self._min_font_size)
        self._default_color = QColor(cfg.get("default_color", self._default_color.name()))
        self._outline_color = QColor(cfg.get("outline_color", self._outline_color.name()))
        self._outline_width = cfg.get("outline_width", self._outline_width)
        self._item_spacing = cfg.get("item_spacing", self._item_spacing)
        self._max_items = cfg.get("max_items", self._max_items)
        self._text_template = cfg.get("text_template", self._text_template)
        self._click_through = cfg.get("click_through", self._click_through)
        self._show_counts = cfg.get("show_counts", self._show_counts)
        self._count_font_size = cfg.get("count_font_size", self._count_font_size)
        self._count_footer.setStyleSheet(
            f"color: #999; font-size: {self._count_font_size}px; "
            "background: transparent; padding: 0 4px;")
        self._label_colors = cfg.get("label_colors", self._label_colors)
        self._bg_color = _parse_rgba(cfg.get("background_color",
            f"rgba({self._bg_color.red()},{self._bg_color.green()},"
            f"{self._bg_color.blue()},{self._bg_color.alpha()})"))
        self._border_color = _parse_rgba(cfg.get("border_color",
            f"rgba({self._border_color.red()},{self._border_color.green()},"
            f"{self._border_color.blue()},{self._border_color.alpha()})"))
        self._border_radius = cfg.get("border_radius", self._border_radius)
        self._padding = cfg.get("padding", self._padding)
        self._title_text = cfg.get("title", self._title_text)
        self._scrollbar_width = cfg.get("scrollbar_width", self._scrollbar_width)
        self._min_w = cfg.get("min_width", self._min_w)
        self._min_h = cfg.get("min_height", self._min_h)
        w = cfg.get("width", self._width)
        h = cfg.get("height", self._height)
        self._width, self._height = w, h
        self.resize(w, h)  # only resize, never move — position is drag-managed
        self.setMinimumSize(self._min_w, self._min_h)
        self._title_lbl.setText(self._title_text)
        self._panel.setStyleSheet(self._panel_style())
        self._scroll.setStyleSheet(self._scroll_style())
        self._update_click_through()
        self._content_layout.setSpacing(
            max(2, self._item_spacing - self._font_size - self._outline_width * 2))
        # Only update labels if font settings actually changed
        old_family = old_cfg.get("font_family", self._font_family)
        old_size = old_cfg.get("font_size", self._font_size)
        old_step = old_cfg.get("font_size_step", self._font_size_step)
        old_min = old_cfg.get("min_font_size", self._min_font_size)
        has_changed = (self._font_family != old_family or self._font_size != old_size
                       or self._font_size_step != old_step or self._min_font_size != old_min)
        if has_changed:
            n = len(self._record_labels)
            for i, (lbl, rec_label) in enumerate(zip(self._record_labels, self._records)):
                pos_from_bottom = n - 1 - i
                size = (self._font_size if pos_from_bottom == 0
                        else max(self._min_font_size,
                                 self._font_size - self._font_size_step))
                # Rebuild rich-text label with per-part colors
                parts = rec_label.split(" + ")
                if len(parts) == 2:
                    c1 = self._label_color(parts[0]).name()
                    c2 = self._label_color(parts[1]).name()
                    text = (f"<span style='color:{c1}'>{parts[0]}</span>"
                            f" <span style='color:#aaa'>+</span> "
                            f"<span style='color:{c2}'>{parts[1]}</span>")
                else:
                    text = f"<span style='color:{self._label_color(rec_label).name()}'>{rec_label}</span>"
                lbl.setText(text)
                font = lbl.font()
                font.setFamily(self._font_family)
                font.setPointSize(size)
                lbl.setFont(font)
                lbl.setStyleSheet(
                    f"QLabel {{ background: transparent; "
                    f"font-family: '{self._font_family}'; "
                    f"font-size: {size}px; }}")
        elif self._font_family != old_family:
            for lbl in self._record_labels:
                font = lbl.font()
                font.setFamily(self._font_family)
                lbl.setFont(font)


# ── Debug Box Overlay ──────────────────────────────────────────────────

from PyQt5.QtGui import QPainter, QPen


class DebugBoxOverlay(QWidget):
    """Transparent fullscreen overlay that paints detection boxes directly over the game.

    - Always-on-top, frameless, click-through.
    - Draggable: hold the overlay to reposition it.
    - Updated from main thread via update_boxes().
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BoxOverlay")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # click-through

        screen = QApplication.primaryScreen()
        geom = screen.geometry() if screen else None
        if geom:
            self.setGeometry(geom)
        else:
            self.resize(1920, 1080)

        self.boxes = []  # list of (x, y, w, h, r, g, b, label)

        # Force-topmost timer for fullscreen games
        self._topmost_timer = QTimer()
        self._topmost_timer.setInterval(1500)
        self._topmost_timer.timeout.connect(self._force_topmost)
        self._topmost_timer.start()

        # Drag state
        self._dragging = False
        self._drag_start = QPoint()

    def _force_topmost(self):
        """Windows: forcefully keep window on top using SetWindowPos."""
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(
                hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0010)
        except Exception:
            pass

    def update_boxes(self, boxes):
        """boxes: list of (x, y, w, h, r, g, b, label) in screen coordinates."""
        self.boxes = boxes
        self.update()

    def clear_boxes(self):
        self.boxes.clear()
        self.update()

    def paintEvent(self, event):
        if not self.boxes:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Microsoft YaHei", 10)
        painter.setFont(font)
        for bx in self.boxes:
            x, y, w, h, r, g, b = bx[:7]
            label = bx[7] if len(bx) > 7 else ""
            color = QColor(r, g, b)
            pen = QPen(color, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(x, y, w, h)
            if label:
                # White text with dark outline for readability
                text_x, text_y = x, max(2, y - 6)
                painter.setPen(QColor(0, 0, 0, 180))
                painter.drawText(text_x + 1, text_y + 1, label)
                painter.drawText(text_x - 1, text_y + 1, label)
                painter.drawText(text_x + 1, text_y - 1, label)
                painter.drawText(text_x - 1, text_y - 1, label)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(text_x, text_y, label)

        painter.end()

    def show_overlay(self):
        self.show()

    def hide_overlay(self):
        self.hide()
        self.clear_boxes()
