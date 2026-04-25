from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget, QDoubleSpinBox, QApplication,
)

from app.domain.views import (
    DetectionModelItemViewModel,
    FrameDataItemViewModel,
    SessionListItemViewModel,
    SessionSettingsViewModel,
)
from app.shared.logging_cfg import get_logger
from app.ui.qt.prev_widget import PreviewWidget
from app.ui.qt.right_panel import RightControlPanel

logger = get_logger("UI->MainWindow")


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

    # --- Signals: Bridged from RightControlPanel ---
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
        self.export_all_button = QPushButton("Export All")

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

        # --- UI Elements: The Extracted Right Panel ---
        self.right_control_panel = RightControlPanel(self)

        self._build_toolbar()
        self._build_ui()
        self._build_status_bar()
        self._initialize_data_panels()
        self._connect_signals()
        self._update_frame_item_action_state()

    # --- Public API: Delegations to Right Panel ---

    @property
    def export_button(self) -> QPushButton:
        """Property bridge so external handlers can access the nested export button directly."""
        return self.right_control_panel.export_button

    def restore_session_settings(self, vm: SessionSettingsViewModel) -> None:
        self.right_control_panel.restore_session_settings(vm)

    def set_tracking_config_warning_visible(self, visible: bool) -> None:
        self.right_control_panel.set_tracking_config_warning_visible(visible)

    def set_iou_widgets_visible(self, visible: bool) -> None:
        self.right_control_panel.set_iou_widgets_visible(visible)

    def set_blur_strength_visible(self, visible: bool) -> None:
        self.right_control_panel.set_blur_strength_visible(visible)

    def set_detection_loading_state(self, is_loading: bool) -> None:
        self.right_control_panel.set_detection_loading_state(is_loading)

    def set_tracking_loading_state(self, is_loading: bool) -> None:
        self.right_control_panel.set_tracking_loading_state(is_loading)

    def set_detection_model_items(self, items: list[DetectionModelItemViewModel]) -> None:
        self.right_control_panel.set_detection_model_items(items)

    def set_selected_detection_model(self, model_id: str) -> None:
        self.right_control_panel.set_selected_detection_model(model_id)

    # --- Public API: Native MainWindow Elements ---

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
        with QSignalBlocker(self.seek_slider):
            self.seek_slider.setValue(max(0, frame_index))

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
        left_layout.addWidget(self._build_bottom_data_panel(), 3)

        main_splitter.addWidget(left_panel)

        # --- RIGHT SIDE ---
        main_splitter.addWidget(self.right_control_panel)

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
        action_row_1 = self.__generate_qhbox_with_widgets([
            self.add_manual_button,
            self.edit_item_button,
            self.delete_item_button,
            self.duplicate_item_button,
            self.duplicate_to_prev_button,
        ])
        action_row_1.addStretch()

        # Action row 2
        action_row_2 = self.__generate_qhbox_with_widgets([
            self.reset_frame_button,
            self.reset_all_button,
            self.reset_tracker_frame_button,
            self.reset_all_trackers_button,
            self.delete_next_occurrences_button,
            self.delete_prev_occurrences_button,
        ])
        action_row_2.addStretch()

        bottom_layout.addWidget(bottom_splitter)
        bottom_layout.addLayout(action_row_1)
        bottom_layout.addLayout(action_row_2)

        return bottom_container

    def _initialize_data_panels(self):
        detection_data_table = self.frame_detection_data_table
        detection_data_table.setHorizontalHeaderLabels(
            ["ID", "Source", "Label", "Detection Confidence", "BBox", "Color"])
        self.__post_data_table_labels_init(detection_data_table)

        tracker_data_table = self.frame_tracker_data_table
        tracker_data_table.setHorizontalHeaderLabels(
            ["ID", "Source", "Label", "Tracker Confidence", "BBox", "Color"])
        self.__post_data_table_labels_init(tracker_data_table)

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
        for signal, slot in [(self.open_action.triggered, self._choose_video_files),
                             (self.open_button.clicked, self._choose_video_files),
                             (self.export_all_action.triggered, self.export_all_requested.emit),
                             (self.export_all_button.clicked, self.export_all_requested.emit),
                             (self.play_button.clicked, self.play_requested.emit),
                             (self.pause_button.clicked, self.pause_requested.emit),
                             (self.previous_button.clicked, self.previous_frame_requested.emit),
                             (self.next_button.clicked, self.next_frame_requested.emit),
                             (self.seek_slider.sliderReleased, self._emit_seek_requested),
                             (self.session_list.itemSelectionChanged, self._emit_selected_session),
                             ]:
            signal.connect(slot)

        # Action Row 1
        for signal, slot in [(self.add_manual_button.clicked, self.add_manual_frame_item_requested.emit),
                             (self.edit_item_button.clicked, self.edit_selected_frame_item_requested.emit),
                             (self.delete_item_button.clicked, self.delete_selected_frame_item_requested.emit),
                             (self.duplicate_item_button.clicked, self.duplicate_selected_frame_item_requested.emit),
                             (self.duplicate_to_prev_button.clicked, self.duplicate_to_prev_frame_requested.emit),
                             ]:
            signal.connect(slot)

        # Action Row 2
        for signal, slot in [(self.reset_frame_button.clicked, self.reset_current_frame_review_requested.emit),
                             (self.reset_all_button.clicked, self.reset_all_review_requested.emit),
                             (self.reset_tracker_frame_button.clicked, self.reset_tracker_frame_requested.emit),
                             (self.reset_all_trackers_button.clicked, self.reset_all_trackers_requested.emit),
                             (self.delete_next_occurrences_button.clicked, self.delete_next_occurrences_requested.emit),
                             (self.delete_prev_occurrences_button.clicked, self.delete_prev_occurrences_requested.emit),
                             ]:
            signal.connect(slot)

        # Tabs/Tables
        detection_data_table = self.frame_detection_data_table
        tracker_data_table = self.frame_tracker_data_table
        for signal, slot in [(self.data_tab.currentChanged, self._update_frame_item_action_state),
                             (detection_data_table.itemSelectionChanged, self._update_frame_item_action_state),
                             (tracker_data_table.itemSelectionChanged, self._update_frame_item_action_state),
                             (detection_data_table.cellClicked, self._update_frame_item_action_state),
                             (tracker_data_table.cellClicked, self._update_frame_item_action_state),
                             (detection_data_table.cellDoubleClicked, self.edit_selected_frame_item_requested.emit),
                             (self.data_tab.currentChanged, self._update_frame_item_action_state),
                             ]:
            signal.connect(slot)

        # --- BRIDGE SIGNALS FROM RIGHT PANEL ---
        right_panel = self.right_control_panel
        for signal, slot in [(right_panel.detect_current_frame_requested,
                              self.detect_current_frame_requested.emit),
                             (right_panel.start_background_detection_requested,
                              self.start_background_detection_requested.emit),
                             (right_panel.model_changed, self.model_changed.emit),
                             (right_panel.min_confidence_changed, self.min_confidence_changed.emit),
                             (right_panel.chosen_labels_changed, self.chosen_labels_changed.emit),
                             (right_panel.start_tracking_requested, self.start_tracking_requested.emit),
                             (right_panel.tracking_strategy_changed, self.tracking_strategy_changed.emit),
                             (right_panel.tracking_source_changed, self.tracking_source_changed.emit),
                             (right_panel.min_iou_changed, self.min_iou_changed.emit),
                             (right_panel.min_tracker_confidence_changed, self.min_tracker_confidence_changed.emit),
                             (right_panel.confidence_decay_changed, self.confidence_decay_changed.emit),
                             (right_panel.draw_boxes_changed, self.draw_boxes_changed.emit),
                             (right_panel.blur_toggled, self.blur_toggled.emit),
                             (right_panel.blur_strength_changed, self.blur_strength_changed.emit),
                             (right_panel.export_requested, self.export_requested.emit)]:
            signal.connect(slot)

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

    def _update_frame_item_action_state(self) -> None:
        selected_count = len(self.get_selected_frame_item_keys())
        self.edit_item_button.setEnabled(selected_count == 1)
        self.delete_item_button.setEnabled(selected_count >= 1)
        self.duplicate_item_button.setEnabled(selected_count >= 1)
        self.duplicate_to_prev_button.setEnabled(selected_count >= 1)
        self.delete_next_occurrences_button.setEnabled(selected_count >= 1)
        self.delete_prev_occurrences_button.setEnabled(selected_count >= 1)

    @staticmethod
    def __generate_qhbox_with_widgets(widgets: list[QWidget]) -> QHBoxLayout:
        parent_layout = QHBoxLayout()
        for widget in widgets:
            parent_layout.addWidget(widget)
        return parent_layout

    @staticmethod
    def __post_data_table_labels_init(detection_data_table: QTableWidget):
        detection_data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        detection_data_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        detection_data_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        detection_data_table.verticalHeader().setVisible(False)
        detection_data_table.horizontalHeader().setStretchLastSection(True)
        detection_data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)