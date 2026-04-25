from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.domain.views import SessionSettingsViewModel, DetectionModelItemViewModel
from app.ui.qt.collapsible_widget import CollapsibleBox


class RightControlPanel(QScrollArea):
    """Encapsulates the Detection, Tracking, and Render controls."""

    # --- Signals ---
    # PySide Rule: Signals must be declared at the class level.
    detect_current_frame_requested = Signal()
    start_background_detection_requested = Signal()
    model_changed = Signal(str)
    min_confidence_changed = Signal(float)
    chosen_labels_changed = Signal(str)

    start_tracking_requested = Signal(str, str)
    tracking_strategy_changed = Signal(str)
    tracking_source_changed = Signal(str)
    min_iou_changed = Signal(float)
    min_tracker_confidence_changed = Signal(float)
    confidence_decay_changed = Signal(float)

    draw_boxes_changed = Signal(bool)
    blur_toggled = Signal(bool)
    blur_strength_changed = Signal(float)
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(280)

        # Container to hold everything inside the scroll area
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(5, 5, 5, 5)
        self._layout.setSpacing(10)

        # All widgets are strictly instantiated as instance attributes here.
        self._init_widgets()
        self._build_ui()
        self._connect_signals()

        self.setWidget(self._container)

    def _init_widgets(self) -> None:
        # --- Detection Widgets ---
        self.model_combo_box = QComboBox()
        self.min_confidence_spinbox = QDoubleSpinBox()
        self.min_confidence_spinbox.setRange(0.0, 1.0)
        self.min_confidence_spinbox.setSingleStep(0.05)
        self.chosen_labels_edit = QLineEdit()
        self.chosen_labels_edit.setPlaceholderText("person, cat, dog")
        self.detect_button = QPushButton("Detect Current Frame")
        self.detect_all_button = QPushButton("Start Background Detection")

        # --- Tracking Widgets ---
        self.track_button = QPushButton("Start Tracking")
        self.tracking_strategy_combo_box = QComboBox()
        self.tracking_source_combo_box = QComboBox()

        self.tracking_source_combo_box.addItem("Raw Detections", "layer_a")
        self.tracking_source_combo_box.addItem("Reviewed Detections", "layer_b")

        self.tracking_strategy_combo_box.addItem("Dummy Tracker (Copy)", "dummy")
        self.tracking_strategy_combo_box.addItem("Hungarian IoU (Fast)", "hungarian")
        self.tracking_strategy_combo_box.addItem("ByteTrack (High Perf)", "bytetrack")
        self.tracking_strategy_combo_box.addItem("DeepSORT", "deepsort")
        self.tracking_strategy_combo_box.addItem("CSRT (Manual/Slow)", "csrt")

        self.min_iou_label = QLabel("Min IoU:")
        self.min_iou_spinbox = QDoubleSpinBox()
        self.min_iou_spinbox.setRange(0.0, 1.0)
        self.min_iou_spinbox.setSingleStep(0.05)

        self.min_tracker_confidence_spinbox = QDoubleSpinBox()
        self.min_tracker_confidence_spinbox.setRange(0.0, 1.0)
        self.min_tracker_confidence_spinbox.setSingleStep(0.05)

        self.confidence_decay_spinbox = QDoubleSpinBox()
        self.confidence_decay_spinbox.setRange(0.0, 1.0)
        self.confidence_decay_spinbox.setSingleStep(0.01)

        self.tracking_config_warning_label = QLabel("⚠️ Settings changed. Re-run tracking.")
        self.tracking_config_warning_label.setStyleSheet("color: #d9534f; font-weight: bold;")
        self.tracking_config_warning_label.setVisible(False)
        self.tracking_config_warning_label.setWordWrap(True)

        # --- Render Widgets ---
        self.draw_boxes_checkbox = QCheckBox("Draw bounding boxes")
        self.blur_checkbox = QCheckBox("Blur bounding boxes")
        self.blur_strength_label = QLabel("Blur strength:")
        self.blur_strength_spinbox = QDoubleSpinBox()
        self.blur_strength_spinbox.setRange(1.0, 100.0)
        self.blur_strength_spinbox.setSingleStep(1.0)
        self.blur_strength_spinbox.setVisible(False)
        self.blur_strength_label.setVisible(False)

        self.export_button = QPushButton("Export Video")

    def _build_ui(self) -> None:
        # 1. Detection Group
        detection_box = CollapsibleBox("Detection")
        detection_box.add_layout(self.__generate_qhbox_with_widgets([QLabel("Model:"), self.model_combo_box]))
        detection_box.add_layout(self.__generate_qhbox_with_widgets([QLabel("Min Conf:"), self.min_confidence_spinbox]))
        detection_box.add_layout(self.__generate_qhbox_with_widgets([QLabel("Labels:"), self.chosen_labels_edit]))
        detection_box.add_widget(self.detect_button)
        detection_box.add_widget(self.detect_all_button)

        # 2. Tracking Group
        tracking_box = CollapsibleBox("Tracking")
        tracking_box.add_widget(self.tracking_config_warning_label)
        tracking_box.add_layout(self.__generate_qhbox_with_widgets([QLabel("Source:"), self.tracking_source_combo_box]))
        tracking_box.add_layout(
            self.__generate_qhbox_with_widgets([QLabel("Strategy:"), self.tracking_strategy_combo_box]))
        tracking_box.add_layout(self.__generate_qhbox_with_widgets([self.min_iou_label, self.min_iou_spinbox]))
        tracking_box.add_layout(
            self.__generate_qhbox_with_widgets([QLabel("Min Conf:"), self.min_tracker_confidence_spinbox]))
        tracking_box.add_layout(self.__generate_qhbox_with_widgets([QLabel("Decay:"), self.confidence_decay_spinbox]))
        tracking_box.add_widget(self.track_button)

        # 3. Preview/Render Group
        render_box = CollapsibleBox("Preview & Render")
        render_box.add_widget(self.draw_boxes_checkbox)
        render_box.add_widget(self.blur_checkbox)
        render_box.add_layout(
            self.__generate_qhbox_with_widgets([self.blur_strength_label, self.blur_strength_spinbox]))
        render_box.add_widget(self.export_button)

        self._layout.addWidget(detection_box)
        self._layout.addWidget(tracking_box)
        self._layout.addWidget(render_box)
        self._layout.addStretch()

    def _connect_signals(self) -> None:
        # Detection Panel
        self.detect_button.clicked.connect(self.detect_current_frame_requested.emit)
        self.detect_all_button.clicked.connect(self.start_background_detection_requested.emit)
        self.model_combo_box.currentIndexChanged.connect(self._emit_model_changed)
        self.min_confidence_spinbox.valueChanged.connect(self.min_confidence_changed.emit)
        self.chosen_labels_edit.editingFinished.connect(
            lambda: self.chosen_labels_changed.emit(self.chosen_labels_edit.text())
        )

        # Tracking Panel
        self.track_button.clicked.connect(self._emit_start_tracking)
        self.tracking_strategy_combo_box.currentIndexChanged.connect(self._emit_tracking_strategy_changed)
        self.tracking_source_combo_box.currentIndexChanged.connect(self._emit_tracking_source_changed)
        self.min_iou_spinbox.valueChanged.connect(self.min_iou_changed.emit)
        self.min_tracker_confidence_spinbox.valueChanged.connect(self.min_tracker_confidence_changed.emit)
        self.confidence_decay_spinbox.valueChanged.connect(self.confidence_decay_changed.emit)

        # Render Panel
        self.draw_boxes_checkbox.toggled.connect(self.draw_boxes_changed.emit)
        self.blur_checkbox.toggled.connect(self.blur_toggled.emit)
        self.blur_strength_spinbox.valueChanged.connect(self.blur_strength_changed.emit)
        self.export_button.clicked.connect(self.export_requested.emit)

    def _emit_model_changed(self) -> None:
        model_id = self.model_combo_box.currentData()
        if isinstance(model_id, str):
            self.model_changed.emit(model_id)

    def _emit_tracking_strategy_changed(self) -> None:
        strategy_id = self.tracking_strategy_combo_box.currentData()
        if isinstance(strategy_id, str):
            self.tracking_strategy_changed.emit(strategy_id)

    def _emit_tracking_source_changed(self) -> None:
        source_id = self.tracking_source_combo_box.currentData()
        if isinstance(source_id, str):
            self.tracking_source_changed.emit(source_id)

    def _emit_start_tracking(self) -> None:
        strategy_id = self.tracking_strategy_combo_box.currentData()
        source_id = self.tracking_source_combo_box.currentData()
        if isinstance(strategy_id, str) and isinstance(source_id, str):
            self.start_tracking_requested.emit(strategy_id, source_id)

    # --- Public API ---

    def restore_session_settings(self, vm: SessionSettingsViewModel) -> None:
        """Populates all right-panel widgets from the provided view model using safe signal blocking."""
        with QSignalBlocker(self.model_combo_box):
            idx = self.model_combo_box.findData(vm.detection_model_name)
            if idx >= 0:
                self.model_combo_box.setCurrentIndex(idx)

        with QSignalBlocker(self.tracking_strategy_combo_box):
            idx = self.tracking_strategy_combo_box.findData(vm.tracking_strategy)
            if idx >= 0:
                self.tracking_strategy_combo_box.setCurrentIndex(idx)

        self.set_iou_widgets_visible(vm.tracking_strategy == "hungarian")

        with QSignalBlocker(self.tracking_source_combo_box):
            idx = self.tracking_source_combo_box.findData(vm.tracking_source)
            if idx >= 0:
                self.tracking_source_combo_box.setCurrentIndex(idx)

        with QSignalBlocker(self.chosen_labels_edit):
            self.chosen_labels_edit.setText(vm.chosen_labels)

        with QSignalBlocker(self.min_confidence_spinbox):
            self.min_confidence_spinbox.setValue(vm.min_detection_confidence)

        with QSignalBlocker(self.min_tracker_confidence_spinbox):
            self.min_tracker_confidence_spinbox.setValue(vm.min_tracker_confidence)

        with QSignalBlocker(self.min_iou_spinbox):
            self.min_iou_spinbox.setValue(vm.min_iou)

        with QSignalBlocker(self.confidence_decay_spinbox):
            self.confidence_decay_spinbox.setValue(vm.confidence_decay)

        with QSignalBlocker(self.blur_strength_spinbox):
            self.blur_strength_spinbox.setValue(vm.blur_strength)

        with QSignalBlocker(self.draw_boxes_checkbox):
            self.draw_boxes_checkbox.setChecked(vm.draw_boxes)

        with QSignalBlocker(self.blur_checkbox):
            self.blur_checkbox.setChecked(vm.blur_enabled)

        self.set_blur_strength_visible(vm.blur_enabled)
        self.set_tracking_config_warning_visible(False)

    def set_iou_widgets_visible(self, visible: bool) -> None:
        self.min_iou_label.setVisible(visible)
        self.min_iou_spinbox.setVisible(visible)

    def set_blur_strength_visible(self, visible: bool) -> None:
        self.blur_strength_label.setVisible(visible)
        self.blur_strength_spinbox.setVisible(visible)

    def set_tracking_config_warning_visible(self, visible: bool) -> None:
        self.tracking_config_warning_label.setVisible(visible)

    def set_detection_loading_state(self, is_loading: bool) -> None:
        self.model_combo_box.setEnabled(not is_loading)
        self.detect_button.setEnabled(not is_loading)
        self.detect_all_button.setEnabled(not is_loading)

    def set_tracking_loading_state(self, is_loading: bool) -> None:
        self.track_button.setEnabled(not is_loading)
        self.tracking_strategy_combo_box.setEnabled(not is_loading)
        self.tracking_source_combo_box.setEnabled(not is_loading)

    def set_detection_model_items(self, items: list[DetectionModelItemViewModel]) -> None:
        with QSignalBlocker(self.model_combo_box):
            self.model_combo_box.clear()
            for item in items:
                self.model_combo_box.addItem(item.display_name, item.model_id)

    def set_selected_detection_model(self, model_id: str) -> None:
        with QSignalBlocker(self.model_combo_box):
            index = self.model_combo_box.findData(model_id)
            if index >= 0:
                self.model_combo_box.setCurrentIndex(index)

    @staticmethod
    def __generate_qhbox_with_widgets(widgets: list[QWidget]) -> QHBoxLayout:
        layout = QHBoxLayout()
        for w in widgets:
            layout.addWidget(w)
        return layout