from __future__ import annotations

from dataclasses import asdict, dataclass

from PyQt6 import QtGui


def _relative_luminance(color: QtGui.QColor) -> float:
    def channel(value: int) -> float:
        normalized = value / 255.0
        return (
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def contrast_ratio(foreground: QtGui.QColor, background: QtGui.QColor) -> float:
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _mix(
    first: QtGui.QColor,
    second: QtGui.QColor,
    second_weight: float,
) -> QtGui.QColor:
    weight = min(max(float(second_weight), 0.0), 1.0)
    return QtGui.QColor(
        round(first.red() * (1.0 - weight) + second.red() * weight),
        round(first.green() * (1.0 - weight) + second.green() * weight),
        round(first.blue() * (1.0 - weight) + second.blue() * weight),
    )


def _readable(
    preferred: QtGui.QColor,
    background: QtGui.QColor,
    *,
    minimum: float,
) -> QtGui.QColor:
    if contrast_ratio(preferred, background) >= minimum:
        return preferred
    black = QtGui.QColor("#000000")
    white = QtGui.QColor("#ffffff")
    return (
        black
        if contrast_ratio(black, background) >= contrast_ratio(white, background)
        else white
    )


def _contrast_pair(
    background: QtGui.QColor,
    preferred_text: QtGui.QColor,
    *,
    minimum: float,
) -> tuple[QtGui.QColor, QtGui.QColor]:
    readable = _readable(preferred_text, background, minimum=minimum)
    if contrast_ratio(readable, background) >= minimum:
        return background, readable
    black = QtGui.QColor("#000000")
    white = QtGui.QColor("#ffffff")
    best_background = background
    best_text = readable
    best_ratio = contrast_ratio(readable, background)
    for step in range(1, 21):
        weight = step / 20.0
        for candidate_background in (
            _mix(background, black, weight),
            _mix(background, white, weight),
        ):
            candidate_text = _readable(
                preferred_text,
                candidate_background,
                minimum=minimum,
            )
            candidate_ratio = contrast_ratio(candidate_text, candidate_background)
            if candidate_ratio > best_ratio:
                best_background = candidate_background
                best_text = candidate_text
                best_ratio = candidate_ratio
            if candidate_ratio >= minimum:
                return candidate_background, candidate_text
    return best_background, best_text


def _hex(color: QtGui.QColor) -> str:
    return color.name(QtGui.QColor.NameFormat.HexRgb)


@dataclass(frozen=True)
class CanvasThemeTokens:
    mode: str
    high_contrast: bool
    window: str
    toolbar: str
    inspector: str
    canvas_well: str
    text: str
    muted_text: str
    disabled_text: str
    border: str
    input: str
    hover: str
    pressed: str
    focus: str
    accent: str
    accent_hover: str
    accent_text: str
    positive_background: str
    positive_text: str
    neutral_background: str
    neutral_text: str
    warning_background: str
    warning_text: str
    negative_background: str
    negative_text: str
    recovery_background: str
    recovery_text: str
    recovery_border: str
    text_contrast: float
    accent_contrast: float
    muted_contrast: float

    def to_dict(self) -> dict[str, str | bool | float]:
        return asdict(self)


def build_canvas_theme(
    palette: QtGui.QPalette,
    *,
    high_contrast: bool = False,
) -> CanvasThemeTokens:
    window = palette.color(QtGui.QPalette.ColorRole.Window)
    base = palette.color(QtGui.QPalette.ColorRole.Base)
    text = palette.color(QtGui.QPalette.ColorRole.WindowText)
    base_text = palette.color(QtGui.QPalette.ColorRole.Text)
    highlight = palette.color(QtGui.QPalette.ColorRole.Highlight)
    disabled_text = palette.color(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.WindowText,
    )
    mode = "dark" if _relative_luminance(window) < 0.36 else "light"
    minimum = 7.0 if high_contrast else 4.5

    toolbar = _mix(window, base, 0.82 if mode == "light" else 0.62)
    inspector = base
    text = _readable(text, window, minimum=minimum)
    input_text = _readable(base_text, base, minimum=minimum)
    muted_candidate = _mix(
        input_text,
        inspector,
        0.34 if high_contrast else 0.46,
    )
    muted_text = _readable(
        muted_candidate,
        inspector,
        minimum=4.5 if high_contrast else 3.3,
    )
    border = _mix(
        inspector,
        input_text,
        0.52 if high_contrast else 0.18,
    )
    input_surface = _mix(
        inspector,
        window,
        0.28 if mode == "light" else 0.46,
    )
    hover = _mix(toolbar, highlight, 0.22 if high_contrast else 0.10)
    pressed = _mix(toolbar, highlight, 0.34 if high_contrast else 0.18)
    focus = _readable(highlight, window, minimum=3.0)
    accent, accent_text = _contrast_pair(
        highlight,
        palette.color(QtGui.QPalette.ColorRole.HighlightedText),
        minimum=minimum,
    )
    accent_hover = _mix(
        accent,
        QtGui.QColor("#000000" if mode == "light" else "#ffffff"),
        0.16,
    )
    canvas_well = _mix(
        window,
        QtGui.QColor("#000000"),
        0.72 if mode == "light" else 0.24,
    )

    def semantic(seed: str) -> tuple[QtGui.QColor, QtGui.QColor]:
        background = _mix(
            inspector,
            QtGui.QColor(seed),
            0.24 if high_contrast else 0.13,
        )
        foreground = _readable(
            QtGui.QColor(seed),
            background,
            minimum=minimum,
        )
        return background, foreground

    positive_bg, positive_text = semantic("#147a55")
    neutral_bg, neutral_text = semantic("#246b9f")
    warning_bg, warning_text = semantic("#9a6500")
    negative_bg, negative_text = semantic("#b33b32")
    recovery_bg, recovery_text = semantic("#9a6500")
    recovery_border = _mix(recovery_bg, recovery_text, 0.34)

    return CanvasThemeTokens(
        mode=mode,
        high_contrast=bool(high_contrast),
        window=_hex(window),
        toolbar=_hex(toolbar),
        inspector=_hex(inspector),
        canvas_well=_hex(canvas_well),
        text=_hex(text),
        muted_text=_hex(muted_text),
        disabled_text=_hex(disabled_text),
        border=_hex(border),
        input=_hex(input_surface),
        hover=_hex(hover),
        pressed=_hex(pressed),
        focus=_hex(focus),
        accent=_hex(accent),
        accent_hover=_hex(accent_hover),
        accent_text=_hex(accent_text),
        positive_background=_hex(positive_bg),
        positive_text=_hex(positive_text),
        neutral_background=_hex(neutral_bg),
        neutral_text=_hex(neutral_text),
        warning_background=_hex(warning_bg),
        warning_text=_hex(warning_text),
        negative_background=_hex(negative_bg),
        negative_text=_hex(negative_text),
        recovery_background=_hex(recovery_bg),
        recovery_text=_hex(recovery_text),
        recovery_border=_hex(recovery_border),
        text_contrast=round(contrast_ratio(text, window), 3),
        accent_contrast=round(contrast_ratio(accent_text, accent), 3),
        muted_contrast=round(contrast_ratio(muted_text, inspector), 3),
    )


def build_canvas_stylesheet(tokens: CanvasThemeTokens) -> str:
    border_width = 2 if tokens.high_contrast else 1
    focus_width = 3 if tokens.high_contrast else 2
    return f"""
QMainWindow {{
    background: {tokens.window};
    color: {tokens.text};
}}
QMenuBar, QMenu {{
    background: {tokens.toolbar};
    color: {tokens.text};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background: {tokens.hover};
}}
QToolBar#sciplotToolbar {{
    background: {tokens.toolbar};
    border: 0;
    border-bottom: {border_width}px solid {tokens.border};
    spacing: 5px;
    padding: 7px 10px;
}}
QToolBar#sciplotToolbar QToolButton {{
    background: transparent;
    border: {border_width}px solid transparent;
    border-radius: 7px;
    padding: 6px 9px;
    color: {tokens.text};
}}
QToolBar#sciplotToolbar QToolButton:hover {{
    background: {tokens.hover};
    border-color: {tokens.border};
}}
QToolBar#sciplotToolbar QToolButton:pressed {{
    background: {tokens.pressed};
}}
QToolBar#sciplotToolbar QToolButton:focus {{
    border: {focus_width}px solid {tokens.focus};
}}
QToolBar#sciplotToolbar QToolButton:disabled {{
    color: {tokens.disabled_text};
}}
QLabel#documentTitle {{
    font-size: 15px;
    font-weight: 700;
    color: {tokens.text};
    padding-left: 4px;
}}
QLabel#toolbarMeta {{
    color: {tokens.muted_text};
    padding: 0 5px;
}}
QFrame#canvasWell {{
    background: {tokens.canvas_well};
    border: {border_width}px solid {tokens.border};
}}
QFrame#recoveryBanner {{
    background: {tokens.recovery_background};
    border: 0;
    border-bottom: {border_width}px solid {tokens.recovery_border};
}}
QLabel#recoveryText {{
    color: {tokens.recovery_text};
    padding: 8px 12px;
    font-weight: 650;
}}
QDockWidget#inspectorDock {{
    color: {tokens.text};
}}
QDockWidget#inspectorDock::title {{
    background: {tokens.toolbar};
    color: {tokens.muted_text};
    border-bottom: {border_width}px solid {tokens.border};
    padding: 6px 10px;
}}
QTabWidget#inspectorTabs::pane {{
    border: 0;
    background: {tokens.inspector};
}}
QTabBar::tab {{
    background: {tokens.toolbar};
    color: {tokens.muted_text};
    border: 0;
    border-bottom: {border_width}px solid {tokens.border};
    padding: 9px 18px;
    font-weight: 650;
}}
QTabBar::tab:selected {{
    background: {tokens.inspector};
    color: {tokens.text};
    border-bottom: {focus_width}px solid {tokens.accent};
}}
QTabBar::tab:focus {{
    outline: {focus_width}px solid {tokens.focus};
}}
QFrame#inspector {{
    background: {tokens.inspector};
    border-left: {border_width}px solid {tokens.border};
}}
QFrame#reviewInspector {{
    background: {tokens.inspector};
    border-left: {border_width}px solid {tokens.border};
}}
QWidget#assistantPanel,
QWidget#assistantContent {{
    background: {tokens.inspector};
}}
QScrollArea#assistantScroll,
QScrollArea#assistantScroll QWidget#qt_scrollarea_viewport {{
    background: transparent;
    border: 0;
}}
QFrame#assistantCard,
QFrame#assistantEmptyCard,
QFrame#assistantComposerCard,
QFrame#assistantProgressCard,
QFrame#assistantProposalCard {{
    background: {tokens.input};
    border: {border_width}px solid {tokens.border};
    border-radius: 10px;
}}
QFrame#assistantProposalCard {{
    border-color: {tokens.accent};
}}
QLabel#assistantCardTitle {{
    color: {tokens.text};
    font-size: 13px;
    font-weight: 750;
}}
QLabel#assistantBody {{
    color: {tokens.text};
}}
QLabel#assistantMeta {{
    color: {tokens.muted_text};
    font-size: 11px;
}}
QLabel#assistantStatusCopy {{
    color: {tokens.muted_text};
    padding: 2px 3px;
}}
QLabel#assistantWarningCopy {{
    color: {tokens.warning_text};
    background: {tokens.warning_background};
    border-radius: 6px;
    padding: 7px 8px;
}}
QPlainTextEdit#assistantRequestEditor {{
    background: {tokens.inspector};
    color: {tokens.text};
    border: {border_width}px solid {tokens.border};
    border-radius: 7px;
    padding: 8px;
    selection-background-color: {tokens.accent};
    selection-color: {tokens.accent_text};
}}
QPlainTextEdit#assistantRequestEditor:focus {{
    border: {focus_width}px solid {tokens.focus};
}}
QProgressBar#assistantProgressBar {{
    background: {tokens.input};
    border: 0;
    border-radius: 3px;
    min-height: 5px;
    max-height: 5px;
}}
QProgressBar#assistantProgressBar::chunk {{
    background: {tokens.accent};
    border-radius: 3px;
}}
QLabel#assistantStateChip {{
    background: {tokens.neutral_background};
    color: {tokens.neutral_text};
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 10px;
    font-weight: 750;
    letter-spacing: 0.5px;
}}
QLabel#assistantStateChip[assistantState="active"] {{
    background: {tokens.positive_background};
    color: {tokens.positive_text};
}}
QLabel#assistantStateChip[assistantState="proposal"],
QLabel#assistantStateChip[assistantState="paused"] {{
    background: {tokens.warning_background};
    color: {tokens.warning_text};
}}
QLabel#assistantStateChip[assistantState="applying"] {{
    background: {tokens.neutral_background};
    color: {tokens.neutral_text};
}}
QLabel#assistantStateChip[assistantState="conflict"] {{
    background: {tokens.negative_background};
    color: {tokens.negative_text};
}}
QWidget#assistantChangeList {{
    background: transparent;
}}
QFrame#assistantChangeCard {{
    background: {tokens.inspector};
    border: {border_width}px solid {tokens.border};
    border-radius: 7px;
}}
QLabel#assistantChangeTarget {{
    color: {tokens.text};
    font-weight: 750;
}}
QLabel#assistantDiffLabel {{
    color: {tokens.muted_text};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#assistantDiffValue,
QLabel#assistantDiffAfter {{
    background: {tokens.input};
    color: {tokens.text};
    border-radius: 5px;
    padding: 6px 7px;
}}
QLabel#assistantDiffAfter {{
    background: {tokens.neutral_background};
    color: {tokens.text};
}}
QFrame#assistantActionBar {{
    background: {tokens.toolbar};
    border-top: {border_width}px solid {tokens.border};
}}
QPushButton#assistantPrimaryButton {{
    background: {tokens.accent};
    color: {tokens.accent_text};
    border-color: {tokens.accent};
}}
QPushButton#assistantSecondaryButton {{
    background: transparent;
    color: {tokens.text};
    border-color: {tokens.border};
}}
QPushButton#assistantSecondaryButton:hover {{
    background: {tokens.hover};
}}
QPushButton#assistantDangerButton {{
    background: transparent;
    color: {tokens.negative_text};
    border-color: {tokens.negative_text};
}}
QPushButton#assistantDangerButton:hover {{
    background: {tokens.negative_background};
}}
QScrollArea#inspectorScroll,
QScrollArea#inspectorScroll QWidget#qt_scrollarea_viewport {{
    background: transparent;
    border: 0;
}}
QLabel#inspectorTitle {{
    color: {tokens.text};
    font-size: 18px;
    font-weight: 750;
}}
QLabel#sectionTitle {{
    color: {tokens.muted_text};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.7px;
}}
QLabel#stateChip {{
    background: {tokens.neutral_background};
    color: {tokens.neutral_text};
    border-radius: 8px;
    padding: 4px 8px;
    font-weight: 700;
}}
QLabel#stateChip[canvasState="ready"] {{
    background: {tokens.positive_background};
    color: {tokens.positive_text};
}}
QLabel#stateChip[canvasState="editing"],
QLabel#stateChip[canvasState="needs_human_confirmation"] {{
    background: {tokens.warning_background};
    color: {tokens.warning_text};
}}
QLabel#stateChip[canvasState="needs_rule_repair"],
QLabel#stateChip[canvasState="conflict"] {{
    background: {tokens.negative_background};
    color: {tokens.negative_text};
}}
QLabel#muted {{
    color: {tokens.muted_text};
}}
QLabel#value {{
    color: {tokens.text};
}}
QLabel#breadcrumb {{
    color: {tokens.text};
    font-weight: 650;
}}
QLabel#pointSelection,
QLabel#directManipulationHint {{
    background: {tokens.neutral_background};
    color: {tokens.neutral_text};
    border-radius: 7px;
    padding: 8px 10px;
}}
QLabel#validationMessage {{
    background: {tokens.negative_background};
    color: {tokens.negative_text};
    border-radius: 7px;
    padding: 8px 10px;
}}
QLabel#reviewSafetyBadge {{
    background: {tokens.warning_background};
    color: {tokens.warning_text};
    border-radius: 7px;
    padding: 6px 9px;
    font-size: 10px;
    font-weight: 750;
    letter-spacing: 0.8px;
}}
QLabel#readOnlyValue {{
    background: {tokens.input};
    color: {tokens.muted_text};
    border: {border_width}px solid {tokens.border};
    border-radius: 7px;
    padding: 7px 9px;
}}
QLabel#fieldLabel {{
    color: {tokens.muted_text};
}}
QLabel[qaState="passed"] {{
    color: {tokens.positive_text};
}}
QLabel[qaState="warning"] {{
    color: {tokens.warning_text};
}}
QLabel[qaState="failed"] {{
    color: {tokens.negative_text};
}}
QGroupBox#inspectorSection {{
    background: transparent;
    color: {tokens.text};
    border: {border_width}px solid {tokens.border};
    border-radius: 9px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 650;
}}
QGroupBox#inspectorSection::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {tokens.text};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {tokens.input};
    color: {tokens.text};
    border: {border_width}px solid {tokens.border};
    border-radius: 7px;
    padding: 7px 9px;
    min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: {focus_width}px solid {tokens.focus};
    background: {tokens.inspector};
}}
QCheckBox {{
    color: {tokens.text};
    spacing: 8px;
}}
QPushButton {{
    background: {tokens.accent};
    color: {tokens.accent_text};
    border: {border_width}px solid {tokens.accent};
    border-radius: 7px;
    padding: 8px 12px;
    font-weight: 650;
}}
QPushButton:hover {{
    background: {tokens.accent_hover};
}}
QPushButton:focus {{
    border: {focus_width}px solid {tokens.focus};
}}
QPushButton:disabled {{
    background: {tokens.border};
    color: {tokens.disabled_text};
}}
QPushButton#secondaryButton {{
    background: transparent;
    color: {tokens.text};
    border-color: {tokens.border};
}}
QPushButton#secondaryButton:hover {{
    background: {tokens.hover};
}}
QToolButton#secondaryToolButton {{
    background: transparent;
    color: {tokens.text};
    border: {border_width}px solid {tokens.border};
    border-radius: 6px;
    padding: 5px 8px;
}}
QToolButton#secondaryToolButton:hover {{
    background: {tokens.hover};
}}
QToolButton#secondaryToolButton:disabled {{
    color: {tokens.disabled_text};
}}
QToolButton#reviewToolButton {{
    background: transparent;
    color: {tokens.text};
    border: {border_width}px solid {tokens.border};
    border-radius: 7px;
    padding: 7px 8px;
    min-width: 64px;
}}
QToolButton#reviewToolButton:hover {{
    background: {tokens.hover};
}}
QToolButton#reviewToolButton:checked {{
    background: {tokens.accent};
    color: {tokens.accent_text};
    border-color: {tokens.accent};
}}
QToolButton#reviewToolButton:focus {{
    border: {focus_width}px solid {tokens.focus};
}}
QToolButton#colorSwatch {{
    background: {tokens.input};
    border: {border_width}px solid {tokens.border};
    border-radius: 6px;
    min-width: 28px;
    padding: 5px;
}}
QToolButton#colorSwatch:hover {{
    background: {tokens.hover};
}}
QListWidget#reviewAnnotationList {{
    background: {tokens.input};
    color: {tokens.text};
    border: {border_width}px solid {tokens.border};
    border-radius: 7px;
    padding: 4px;
    min-height: 92px;
}}
QListWidget#reviewAnnotationList::item {{
    border-radius: 5px;
    padding: 7px 8px;
}}
QListWidget#reviewAnnotationList::item:hover {{
    background: {tokens.hover};
}}
QListWidget#reviewAnnotationList::item:selected {{
    background: {tokens.accent};
    color: {tokens.accent_text};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 1px;
}}
QScrollBar::handle:vertical {{
    background: {tokens.border};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {tokens.muted_text};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: transparent;
    border: 0;
    height: 0;
}}
QFrame#divider {{
    background: {tokens.border};
    min-height: {border_width}px;
    max-height: {border_width}px;
}}
QStatusBar {{
    background: {tokens.toolbar};
    border-top: {border_width}px solid {tokens.border};
    color: {tokens.muted_text};
}}
QStatusBar QLabel {{
    color: {tokens.muted_text};
    padding: 2px 8px;
}}
QToolTip {{
    background: {tokens.inspector};
    color: {tokens.text};
    border: {border_width}px solid {tokens.border};
}}
"""


__all__ = [
    "CanvasThemeTokens",
    "build_canvas_stylesheet",
    "build_canvas_theme",
    "contrast_ratio",
]
