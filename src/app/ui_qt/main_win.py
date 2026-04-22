from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.domain.presentation import (
    DetectionModelItemViewModel,
    FrameDataItemViewModel,
    SessionListItemViewModel,
    SessionSettingsViewModel,
)
from app.shared.logging_cfg import get_logger
from app.ui_qt.prev_widget import PreviewWidget

logger = get_logger("UI->MainWindow")


class CollapsibleBox(QWidget):
    """
    A custom widget that provides a collapsible panel.
    Clicking the toggle button shows/hides the child widgets.
    """

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.is_expanded = True
        self._title = title

        # Toggle button acts as the header
        self.toggle_button = QPushButton(f"▼ {self._title}")
        self.toggle_button.setStyleSheet(
            "text-align: left; font-weight: bold; padding: 6px;"
        )
        self.toggle_button.clicked.connect(self.toggle)

        # Content area holds the actual widgets
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(15, 5, 5, 10)  # Indent slightly

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(2)
        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.content_area)

    def toggle(self) -> None:
        self.is_expanded = not self.is_expanded
        self.content_area.setVisible(self.is_expanded)
        icon = "▼" if self.is_expanded else "▶"
        self.toggle_button.setText(f"{icon} {self._title}")

    def add_widget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def add_layout(self, layout: QVBoxLayout | QHBoxLayout) -> None:
        self.content_layout.addLayout(layout)


class MainWindow(QMainWindow):
    # --- Signals: Top row ---
    open_videos_requested = Signal(list)

    # --- Signals: Transport controls ---
    pause_requested = Signal()
    play_requested = Signal()
    next_frame_requested = Signal()
    previous_frame_requested = Signal()
    seek_requested = Signal(int)

    # --- Signals: Session management ---
    session_selected = Signal(str)

    # --- Signals: Data tab (Action Row) ---
    add_manual_frame_item_requested = Signal()
    delete_selected_frame_item_requested = Signal()
    duplicate_selected_frame_item_requested = Signal()
    edit_selected_frame_item_requested = Signal()
    reset_all_review_requested = Signal()
    reset_current_frame_review_requested = Signal()

    # --- NEW Signals: Action Row 2 ---
    duplicate_to_prev_frame_requested = Signal()
    reset_tracker_frame_requested = Signal()
    reset_all_trackers_requested = Signal()
    delete_next_occurrences_requested = Signal()
    delete_prev_occurrences_requested = Signal()

    # --- Signals: Detection panel ---
    detect_current_frame_requested = Signal()
    start_background_detection_requested = Signal()
    detection_model_changed = Signal(str)
    min_confidence_changed = Signal(float)
    chosen_labels_changed = Signal(str)

    # --- Signals: Tracking panel ---
    start_tracking_requested = Signal(str, str)
    tracking_strategy_changed = Signal(str)
    tracking_source_changed = Signal(str)
    min_iou_changed = Signal(float)
    min_tracker_confidence_changed = Signal(float)
    confidence_decay_changed = Signal(float)

    # --- Signals: Preview/Render panel ---
    draw_boxes_changed = Signal(bool)
    blur_toggled = Signal(bool)
    blur_strength_changed = Signal(float)
    export_requested = Signal()
    export_all_requested = Signal()

    def __init__(self) -> None:
        logger.info("Initializing UI (MainWindow)")
        super().__init__()

        self.setWindowTitle("Video App Rewrite")
        self.resize(1300, 850)

        # --- UI Elements: Top row ---
        self.open_action = QAction("Open Video(s)...", self)
        self.open_button = QPushButton("Open Video(s)")
        self.export_all_action = QAction("Export All...", self)

        # --- UI Elements: Transport controls ---
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.previous_button = QPushButton("Previous Frame")
        self.next_button = QPushButton("Next Frame")
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)

        # --- UI Elements: Action Row 1 ---
        self.add_manual_button = QPushButton("Add Manual Box")
        self.edit_item_button = QPushButton("Edit Selected")
        self.delete_item_button = QPushButton("Delete Selected")
        self.duplicate_item_button = QPushButton("Dup To Next")
        self.duplicate_to_prev_button = QPushButton("Dup To Prev")

        # --- UI Elements: Action Row 2 ---
        self.reset_frame_button = QPushButton("Reset Review (Frame)")
        self.reset_all_button = QPushButton("Reset Review (All)")
        self.reset_tracker_frame_button = QPushButton("Reset Trackers (Frame)")
        self.reset_all_trackers_button = QPushButton("Reset Trackers (All)")
        self.delete_next_occurrences_button = QPushButton("Delete Next Occurrences")
        self.delete_prev_occurrences_button = QPushButton("Delete Prev Occurrences")

        # --- UI Elements: Detection panel ---
        self.detect_button = QPushButton("Detect Current Frame")
        self.detect_all_button = QPushButton("Start Background Detection")
        self.model_combo_box = QComboBox()
        self.min_confidence_spinbox = QDoubleSpinBox()
        self.min_confidence_spinbox.setRange(0.0, 1.0)
        self.min_confidence_spinbox.setSingleStep(0.05)
        self.chosen_labels_edit = QLineEdit()
        self.chosen_labels_edit.setPlaceholderText("person, cat, dog")

        # --- UI Elements: Tracker panel ---
        self.track_button = QPushButton("Start Tracking")
        self.tracking_strategy_combo_box = QComboBox()
        self.tracking_source_combo_box = QComboBox()

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

        # --- UI Elements: Preview/Render panel ---
        self.draw_boxes_checkbox = QCheckBox("Draw bounding boxes")
        self.blur_checkbox = QCheckBox("Blur bounding boxes")
        self.blur_strength_label = QLabel("Blur strength:")
        self.blur_strength_spinbox = QDoubleSpinBox()
        self.blur_strength_spinbox.setRange(1.0, 100.0)
        self.blur_strength_spinbox.setSingleStep(1.0)
        self.blur_strength_spinbox.setVisible(False)
        self.blur_strength_label.setVisible(False)

        self.export_button = QPushButton("Export Video")
        self.export_all_button = QPushButton("Export All")

        # --- UI Elements: Frame preview ---
        self.preview_widget = PreviewWidget()

        # --- UI Elements: Opened files (session) ---
        self.session_list = QListWidget()
        self.session_tab = QTabWidget()

        # --- UI Elements: Data tab (Detected objects, Tracking results) ---
        self.frame_detection_data_table = QTableWidget(0, 6)
        self.frame_tracker_data_table = QTableWidget(0, 6)
        self.data_tab = QTabWidget()

        self.frame_label = QLabel("Frame 0/0")
        self.info_label = QLabel("No session loaded")

        self.model_state_specific_widgets = (
            self.model_combo_box,
            self.detect_button,
            self.detect_all_button,
        )

        self.tracking_state_specific_widgets = (
            self.track_button,
            self.tracking_strategy_combo_box,
            self.tracking_source_combo_box,
        )

        self._build_toolbar()
        self._build_ui()
        self._build_status_bar()
        self._connect_signals()
        self._update_frame_item_action_state()

    # --- Public API: Widget updates ---

    def restore_session_settings(self, vm: SessionSettingsViewModel) -> None:
        """Populates all right-panel widgets from the provided view model."""
        self.model_combo_box.blockSignals(True)
        idx = self.model_combo_box.findData(vm.detection_model_name)
        if idx >= 0:
            self.model_combo_box.setCurrentIndex(idx)
        self.model_combo_box.blockSignals(False)

        self.min_confidence_spinbox.blockSignals(True)
        self.min_confidence_spinbox.setValue(vm.min_detection_confidence)
        self.min_confidence_spinbox.blockSignals(False)

        self.chosen_labels_edit.blockSignals(True)
        self.chosen_labels_edit.setText(vm.chosen_labels)
        self.chosen_labels_edit.blockSignals(False)

        self.tracking_strategy_combo_box.blockSignals(True)
        idx = self.tracking_strategy_combo_box.findData(vm.tracking_strategy)
        if idx >= 0:
            self.tracking_strategy_combo_box.setCurrentIndex(idx)
        self.tracking_strategy_combo_box.blockSignals(False)
        self.set_iou_widgets_visible(vm.tracking_strategy == "hungarian")

        self.tracking_source_combo_box.blockSignals(True)
        idx = self.tracking_source_combo_box.findData(vm.tracking_source)
        if idx >= 0:
            self.tracking_source_combo_box.setCurrentIndex(idx)
        self.tracking_source_combo_box.blockSignals(False)

        self.min_iou_spinbox.blockSignals(True)
        self.min_iou_spinbox.setValue(vm.min_iou)
        self.min_iou_spinbox.blockSignals(False)

        self.min_tracker_confidence_spinbox.blockSignals(True)
        self.min_tracker_confidence_spinbox.setValue(vm.min_tracker_confidence)
        self.min_tracker_confidence_spinbox.blockSignals(False)

        self.confidence_decay_spinbox.blockSignals(True)
        self.confidence_decay_spinbox.setValue(vm.confidence_decay)
        self.confidence_decay_spinbox.blockSignals(False)

        self.draw_boxes_checkbox.blockSignals(True)
        self.draw_boxes_checkbox.setChecked(vm.draw_boxes)
        self.draw_boxes_checkbox.blockSignals(False)

        self.blur_checkbox.blockSignals(True)
        self.blur_checkbox.setChecked(vm.blur_enabled)
        self.blur_checkbox.blockSignals(False)
        self.set_blur_strength_visible(vm.blur_enabled)

        self.blur_strength_spinbox.blockSignals(True)
        self.blur_strength_spinbox.setValue(vm.blur_strength)
        self.blur_strength_spinbox.blockSignals(False)

        self.set_tracking_config_warning_visible(False)

    def set_iou_widgets_visible(self, visible: bool) -> None:
        self.min_iou_label.setVisible(visible)
        self.min_iou_spinbox.setVisible(visible)

    def set_blur_strength_visible(self, visible: bool) -> None:
        self.blur_strength_label.setVisible(visible)
        self.blur_strength_spinbox.setVisible(visible)

    def set_tracking_config_warning_visible(self, visible: bool) -> None:
        self.tracking_config_warning_label.setVisible(visible)

    # --- Rest of Public API ---

    def get_selected_session_id(self) -> str | None:
        item = self.session_list.currentItem()
        if item is None:
            return None
        session_id = item.data(Qt.ItemDataRole.UserRole)
        return session_id if isinstance(session_id, str) else None

    def select_session(self, session_id: str) -> None:
        for index in range(self.session_list.count()):
            item = self.session_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == session_id:
                self.session_list.setCurrentItem(item)
                break

    def set_session_items(self, items: list[SessionListItemViewModel]) -> None:
        self.session_list.clear()
        for item_view_model in items:
            item = QListWidgetItem(item_view_model.title)
            item.setToolTip(item_view_model.subtitle)
            item.setData(Qt.ItemDataRole.UserRole, item_view_model.session_id)
            self.session_list.addItem(item)

    def set_detection_loading_state(self, is_loading: bool) -> None:
        for widget in self.model_state_specific_widgets:
            widget.setEnabled(not is_loading)

    def set_tracking_loading_state(self, is_loading: bool) -> None:
        for widget in self.tracking_state_specific_widgets:
            widget.setEnabled(not is_loading)

    def set_detection_model_items(self, items: list[DetectionModelItemViewModel]) -> None:
        self.model_combo_box.blockSignals(True)
        self.model_combo_box.clear()
        for item in items:
            self.model_combo_box.addItem(item.display_name, item.model_id)
        self.model_combo_box.blockSignals(False)

    def set_tracker_data_items(self, items: list[FrameDataItemViewModel]) -> None:
        self.frame_tracker_data_table.blockSignals(True)
        self.frame_tracker_data_table.setRowCount(len(items))

        for row_index, item in enumerate(items):
            id_item = QTableWidgetItem(item.item_id)
            id_item.setData(Qt.ItemDataRole.UserRole, item.item_key)
            self.frame_tracker_data_table.setItem(row_index, 0, id_item)
            self.frame_tracker_data_table.setItem(row_index, 1, QTableWidgetItem(item.source))
            self.frame_tracker_data_table.setItem(row_index, 2, QTableWidgetItem(item.label))
            self.frame_tracker_data_table.setItem(row_index, 3, QTableWidgetItem(item.confidence_text))
            self.frame_tracker_data_table.setItem(row_index, 4, QTableWidgetItem(item.bbox_text))
            self.frame_tracker_data_table.setItem(row_index, 5, QTableWidgetItem(item.color_hex))

        self.frame_tracker_data_table.blockSignals(False)

    def set_selected_detection_model(self, model_id: str) -> None:
        self.model_combo_box.blockSignals(True)
        index = self.model_combo_box.findData(model_id)
        if index >= 0:
            self.model_combo_box.setCurrentIndex(index)
        self.model_combo_box.blockSignals(False)

    def get_active_tab_index(self) -> int:
        tab_widget_idx = self.data_tab.currentIndex()
        return tab_widget_idx if tab_widget_idx is not None else -1

    def get_active_frame_data_table(self) -> QTableWidget:
        if self.data_tab.currentIndex() == 1:
            return self.frame_tracker_data_table
        return self.frame_detection_data_table

    def get_frame_data_table(self) -> QTableWidget:
        return self.frame_detection_data_table

    def get_selected_frame_item_keys(self) -> list[str]:
        table = self.get_active_frame_data_table()
        selection_model = table.selectionModel()
        if selection_model is None:
            return []

        selected_keys: list[str] = []
        seen_keys: set[str] = set()

        for index in selection_model.selectedRows():
            id_item = table.item(index.row(), 0)
            if id_item is None:
                continue
            item_key = id_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(item_key, str) and item_key not in seen_keys:
                seen_keys.add(item_key)
                selected_keys.append(item_key)

        return selected_keys

    def set_frame_data_items(self, items: list[FrameDataItemViewModel]) -> None:
        selected_item_keys = set(self.get_selected_frame_item_keys())
        had_focus = self.frame_detection_data_table.hasFocus()

        self.frame_detection_data_table.blockSignals(True)
        self.frame_detection_data_table.setRowCount(len(items))

        rows_to_select: list[int] = []

        for row_index, item in enumerate(items):
            id_item = QTableWidgetItem(item.item_id)
            id_item.setData(Qt.ItemDataRole.UserRole, item.item_key)

            self.frame_detection_data_table.setItem(row_index, 0, id_item)
            self.frame_detection_data_table.setItem(row_index, 1, QTableWidgetItem(item.source))
            self.frame_detection_data_table.setItem(row_index, 2, QTableWidgetItem(item.label))
            self.frame_detection_data_table.setItem(row_index, 3, QTableWidgetItem(item.confidence_text))
            self.frame_detection_data_table.setItem(row_index, 4, QTableWidgetItem(item.bbox_text))
            self.frame_detection_data_table.setItem(row_index, 5, QTableWidgetItem(item.color_hex))

            if item.item_key in selected_item_keys:
                rows_to_select.append(row_index)

        self.frame_detection_data_table.clearSelection()

        for row_index in rows_to_select:
            self.frame_detection_data_table.selectRow(row_index)

        if rows_to_select:
            self.frame_detection_data_table.setCurrentCell(rows_to_select[0], 0)

        self.frame_detection_data_table.blockSignals(False)

        if had_focus:
            self.frame_detection_data_table.setFocus()

        self._update_frame_item_action_state()

    def set_frame_label_text(self, text: str) -> None:
        self.frame_label.setText(text)

    def set_seek_range(self, maximum_frame_index: int) -> None:
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(max(0, maximum_frame_index))

    def set_seek_value(self, frame_index: int) -> None:
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(max(0, frame_index))
        self.seek_slider.blockSignals(False)

    def set_status_text(self, text: str) -> None:
        self.info_label.setText(text)

    def show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    # --- Protected: UI Construction ---

    def _build_status_bar(self) -> None:
        status = QStatusBar()
        status.addPermanentWidget(self.info_label, 1)
        self.setStatusBar(status)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addAction(self.open_action)
        toolbar.addSeparator()
        toolbar.addAction(self.export_all_action)
        self.addToolBar(toolbar)

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)

        # 1. Top Row
        top_row = QHBoxLayout()
        top_row.addWidget(self.open_button)
        top_row.addWidget(self.export_all_button)
        top_row.addStretch()
        root_layout.addLayout(top_row)

        # 2. Main Horizontal Splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- LEFT SIDE ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(self.preview_widget, 5)
        left_layout.addLayout(self._build_transport_controls())

        self._initialize_data_panels()
        left_layout.addWidget(self._build_bottom_data_panel(), 3)

        main_splitter.addWidget(left_panel)

        # --- RIGHT SIDE ---
        main_splitter.addWidget(self._build_right_panel())

        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)

        root_layout.addWidget(main_splitter, 1)
        self.setCentralWidget(central)

    def _build_transport_controls(self) -> QVBoxLayout:
        transport_layout = QVBoxLayout()
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(0)
        self.seek_slider.setValue(0)
        transport_layout.addWidget(self.seek_slider)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.play_button)
        btn_row.addWidget(self.pause_button)
        btn_row.addWidget(self.previous_button)
        btn_row.addWidget(self.next_button)
        btn_row.addStretch()
        btn_row.addWidget(self.frame_label)

        transport_layout.addLayout(btn_row)
        return transport_layout

    def _build_bottom_data_panel(self) -> QWidget:
        self.data_tab.addTab(self.frame_detection_data_table, "Detected objects")
        self.data_tab.addTab(self.frame_tracker_data_table, "Tracking results")
        self.session_tab.addTab(self.session_list, "Opened files")

        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        bottom_splitter.addWidget(self.data_tab)
        bottom_splitter.addWidget(self.session_tab)
        bottom_splitter.setStretchFactor(0, 3)
        bottom_splitter.setStretchFactor(1, 1)

        # Action row 1
        action_row_1 = QHBoxLayout()
        action_row_1.addWidget(self.add_manual_button)
        action_row_1.addWidget(self.edit_item_button)
        action_row_1.addWidget(self.delete_item_button)
        action_row_1.addWidget(self.duplicate_item_button)
        action_row_1.addWidget(self.duplicate_to_prev_button)
        action_row_1.addStretch()

        # Action row 2
        action_row_2 = QHBoxLayout()
        action_row_2.addWidget(self.reset_frame_button)
        action_row_2.addWidget(self.reset_all_button)
        action_row_2.addWidget(self.reset_tracker_frame_button)
        action_row_2.addWidget(self.reset_all_trackers_button)
        action_row_2.addWidget(self.delete_next_occurrences_button)
        action_row_2.addWidget(self.delete_prev_occurrences_button)
        action_row_2.addStretch()

        bottom_layout.addWidget(bottom_splitter)
        bottom_layout.addLayout(action_row_1)
        bottom_layout.addLayout(action_row_2)

        return bottom_container

    def _build_right_panel(self) -> QScrollArea:
        self.tracking_source_combo_box.addItem("Raw Detections", "layer_a")
        self.tracking_source_combo_box.addItem("Reviewed Detections", "layer_b")

        self.tracking_strategy_combo_box.addItem("Dummy Tracker (Copy)", "dummy")
        self.tracking_strategy_combo_box.addItem("Hungarian IoU (Fast)", "hungarian")
        self.tracking_strategy_combo_box.addItem("ByteTrack (High Perf)", "bytetrack")
        self.tracking_strategy_combo_box.addItem("DeepSORT", "deepsort")
        self.tracking_strategy_combo_box.addItem("CSRT (Manual/Slow)", "csrt")

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(280)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(5, 5, 5, 5)
        container_layout.setSpacing(10)

        # 1. Detection Group
        detection_box = CollapsibleBox("Detection")

        row = QHBoxLayout()
        row.addWidget(QLabel("Model:"))
        row.addWidget(self.model_combo_box)
        detection_box.add_layout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Min Conf:"))
        row.addWidget(self.min_confidence_spinbox)
        detection_box.add_layout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Labels:"))
        row.addWidget(self.chosen_labels_edit)
        detection_box.add_layout(row)

        detection_box.add_widget(self.detect_button)
        detection_box.add_widget(self.detect_all_button)

        # 2. Tracking Group
        tracking_box = CollapsibleBox("Tracking")
        tracking_box.add_widget(self.tracking_config_warning_label)

        row = QHBoxLayout()
        row.addWidget(QLabel("Source:"))
        row.addWidget(self.tracking_source_combo_box)
        tracking_box.add_layout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Strategy:"))
        row.addWidget(self.tracking_strategy_combo_box)
        tracking_box.add_layout(row)

        row = QHBoxLayout()
        row.addWidget(self.min_iou_label)
        row.addWidget(self.min_iou_spinbox)
        tracking_box.add_layout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Min Conf:"))
        row.addWidget(self.min_tracker_confidence_spinbox)
        tracking_box.add_layout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Decay:"))
        row.addWidget(self.confidence_decay_spinbox)
        tracking_box.add_layout(row)

        tracking_box.add_widget(self.track_button)

        # 3. Preview/Render Group
        render_box = CollapsibleBox("Preview & Render")
        render_box.add_widget(self.draw_boxes_checkbox)
        render_box.add_widget(self.blur_checkbox)

        row = QHBoxLayout()
        row.addWidget(self.blur_strength_label)
        row.addWidget(self.blur_strength_spinbox)
        render_box.add_layout(row)

        render_box.add_widget(self.export_button)

        container_layout.addWidget(detection_box)
        container_layout.addWidget(tracking_box)
        container_layout.addWidget(render_box)
        container_layout.addStretch()

        scroll_area.setWidget(container)
        return scroll_area

    def _initialize_data_panels(self):
        self.frame_detection_data_table.setHorizontalHeaderLabels(
            ["ID", "Source", "Label", "Detection Confidence", "BBox", "Color"]
        )
        detection_data_table = self.frame_detection_data_table

        detection_data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        detection_data_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        detection_data_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        detection_data_table.verticalHeader().setVisible(False)
        detection_data_table.horizontalHeader().setStretchLastSection(True)
        detection_data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        tracker_data_table = self.frame_tracker_data_table

        tracker_data_table.setHorizontalHeaderLabels(["ID", "Source", "Label", "Tracker Confidence", "BBox", "Color" ])
        tracker_data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tracker_data_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tracker_data_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tracker_data_table.verticalHeader().setVisible(False)
        tracker_data_table.horizontalHeader().setStretchLastSection(True)
        tracker_data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    # --- Protected: Signal & Event Logic ---

    def _choose_video_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Video Files",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.m4v);;All Files (*)",
        )
        if paths:
            self.open_videos_requested.emit(paths)

    def _connect_signals(self) -> None:
        # Top/Transport
        self.open_action.triggered.connect(self._choose_video_files)
        self.open_button.clicked.connect(self._choose_video_files)
        self.export_all_action.triggered.connect(self.export_all_requested.emit)
        self.export_all_button.clicked.connect(self.export_all_requested.emit)

        self.play_button.clicked.connect(self.play_requested.emit)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.previous_button.clicked.connect(self.previous_frame_requested.emit)
        self.next_button.clicked.connect(self.next_frame_requested.emit)
        self.seek_slider.sliderReleased.connect(self._emit_seek_requested)
        self.session_list.itemSelectionChanged.connect(self._emit_selected_session)

        # Detection Panel
        self.detect_button.clicked.connect(self.detect_current_frame_requested.emit)
        self.detect_all_button.clicked.connect(self.start_background_detection_requested.emit)
        self.model_combo_box.currentIndexChanged.connect(self._emit_model_changed)
        self.min_confidence_spinbox.valueChanged.connect(self.min_confidence_changed.emit)
        self.chosen_labels_edit.editingFinished.connect(
            lambda: self.chosen_labels_changed.emit(self.chosen_labels_edit.text()))

        # Tracking Panel
        self.track_button.clicked.connect(self._emit_start_tracking)
        self.tracking_strategy_combo_box.currentIndexChanged.connect(self._emit_tracking_strategy_changed)
        self.tracking_source_combo_box.currentIndexChanged.connect(self._emit_tracking_source_changed)
        self.min_iou_spinbox.valueChanged.connect(self.min_iou_changed.emit)
        self.min_tracker_confidence_spinbox.valueChanged.connect(self.min_tracker_confidence_changed.emit)
        self.confidence_decay_spinbox.valueChanged.connect(self.confidence_decay_changed.emit)

        # Preview/Render Panel
        self.draw_boxes_checkbox.toggled.connect(self.draw_boxes_changed.emit)
        self.blur_checkbox.toggled.connect(self.blur_toggled.emit)
        self.blur_strength_spinbox.valueChanged.connect(self.blur_strength_changed.emit)
        self.export_button.clicked.connect(self.export_requested.emit)

        # Action Row 1
        self.add_manual_button.clicked.connect(self.add_manual_frame_item_requested.emit)
        self.edit_item_button.clicked.connect(self.edit_selected_frame_item_requested.emit)
        self.delete_item_button.clicked.connect(self.delete_selected_frame_item_requested.emit)
        self.duplicate_item_button.clicked.connect(self.duplicate_selected_frame_item_requested.emit)
        self.duplicate_to_prev_button.clicked.connect(self.duplicate_to_prev_frame_requested.emit)

        # Action Row 2
        self.reset_frame_button.clicked.connect(self.reset_current_frame_review_requested.emit)
        self.reset_all_button.clicked.connect(self.reset_all_review_requested.emit)
        self.reset_tracker_frame_button.clicked.connect(self.reset_tracker_frame_requested.emit)
        self.reset_all_trackers_button.clicked.connect(self.reset_all_trackers_requested.emit)
        self.delete_next_occurrences_button.clicked.connect(self.delete_next_occurrences_requested.emit)
        self.delete_prev_occurrences_button.clicked.connect(self.delete_prev_occurrences_requested.emit)

        # Tabs/Tables
        self.frame_detection_data_table.itemSelectionChanged.connect(self._update_frame_item_action_state)
        self.frame_tracker_data_table.itemSelectionChanged.connect(self._update_frame_item_action_state)
        self.data_tab.currentChanged.connect(self._update_frame_item_action_state)

    def _emit_model_changed(self) -> None:
        model_id = self.model_combo_box.currentData()
        if isinstance(model_id, str):
            self.detection_model_changed.emit(model_id)

    def _emit_tracking_strategy_changed(self) -> None:
        strategy_id = self.tracking_strategy_combo_box.currentData()
        if isinstance(strategy_id, str):
            self.tracking_strategy_changed.emit(strategy_id)

    def _emit_tracking_source_changed(self) -> None:
        source_id = self.tracking_source_combo_box.currentData()
        if isinstance(source_id, str):
            self.tracking_source_changed.emit(source_id)

    def _emit_seek_requested(self) -> None:
        frame_index = self.seek_slider.value()
        self.seek_requested.emit(frame_index)

    def _emit_selected_session(self) -> None:
        item = self.session_list.currentItem()
        if item is None:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(session_id, str):
            self.session_selected.emit(session_id)

    def _emit_start_tracking(self) -> None:
        strategy_id = self.tracking_strategy_combo_box.currentData()
        source_id = self.tracking_source_combo_box.currentData()
        if isinstance(strategy_id, str) and isinstance(source_id, str):
            self.start_tracking_requested.emit(strategy_id, source_id)

    def _update_frame_item_action_state(self) -> None:
        selected_count = len(self.get_selected_frame_item_keys())
        self.edit_item_button.setEnabled(selected_count == 1)
        self.delete_item_button.setEnabled(selected_count >= 1)
        self.duplicate_item_button.setEnabled(selected_count >= 1)
        self.duplicate_to_prev_button.setEnabled(selected_count >= 1)
        self.delete_next_occurrences_button.setEnabled(selected_count >= 1)
        self.delete_prev_occurrences_button.setEnabled(selected_count >= 1)