from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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

from app.presentation.view_models import (
    DetectionModelItemViewModel,
    FrameDataItemViewModel,
    SessionListItemViewModel,
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


class MainWindow(QMainWindow):
    """
    Main Qt application window.

    This class handles the layout and visual state of the application,
    exposing signals for the Controller to handle.
    """
    # --- Signals: Top row ---
    open_videos_requested = Signal(list)

    # --- Signals: Data tab ---
    add_manual_frame_item_requested = Signal()
    delete_selected_frame_item_requested = Signal()
    duplicate_selected_frame_item_requested = Signal()
    edit_selected_frame_item_requested = Signal()
    reset_all_review_requested = Signal()
    reset_current_frame_review_requested = Signal()

    # --- Signals: Transport controls ---
    pause_requested = Signal()
    play_requested = Signal()
    next_frame_requested = Signal()
    previous_frame_requested = Signal()
    seek_requested = Signal(int)

    # --- Signals: Session management ---
    session_selected = Signal(str)

    # --- Signals: Detection tab ---
    detect_current_frame_requested = Signal()
    detection_model_changed = Signal(str)

    # --- Signals: Tracker tab ---
    start_background_detection_requested = Signal()
    start_tracking_requested = Signal(str, str)

    def __init__(self) -> None:
        logger.info("Initializing UI (MainWindow)")
        super().__init__()

        self.setWindowTitle("Video App Rewrite")
        self.resize(1200, 800)

        # --- UI Elements: Top row ---
        self.open_action = QAction("Open Video(s)...", self)
        self.open_button = QPushButton("Open Video(s)")

        # --- UI Elements: Transport controls ---
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.previous_button = QPushButton("Previous Frame")
        self.next_button = QPushButton("Next Frame")
        self.detect_button = QPushButton("Detect Current Frame")
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)

        # --- UI Elements: Action Row ---
        self.add_manual_button = QPushButton("Add Manual Box")
        self.edit_item_button = QPushButton("Edit Selected")
        self.delete_item_button = QPushButton("Delete Selected")
        self.duplicate_item_button = QPushButton("Duplicate To Next Frame")
        self.reset_frame_button = QPushButton("Reset Frame")
        self.reset_all_button = QPushButton("Reset All Review")

        # --- UI Elements: Detection tab ---
        self.detect_all_button = QPushButton("Start Background Detection")
        self.model_combo_box = QComboBox()

        # --- UI Elements: Tracker tab ---
        self.track_button = QPushButton("Start Tracking")
        self.tracking_strategy_combo_box = QComboBox()
        self.tracking_source_combo_box = QComboBox()

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

        self.model_state_specific_widgets = (self.model_combo_box,
                                             self.detect_button,
                                             self.detect_all_button,)

        self.tracking_state_specific_widgets = (self.add_manual_button,
                                                self.detect_button,
                                                self.detect_all_button,
                                                self.reset_all_button,
                                                self.reset_frame_button,
                                                self.track_button,
                                                self.tracking_strategy_combo_box,
                                                self.tracking_source_combo_box,)

        self._build_toolbar()
        self._build_ui()
        self._build_status_bar()
        self._connect_signals()
        self._update_frame_item_action_state()

    # --- Public API: Session Helpers ---

    def get_selected_session_id(self) -> str | None:
        logger.trace("Getting selected session id")
        item = self.session_list.currentItem()
        if item is None:
            logger.trace("No active session present.")
            return None
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(session_id, str):
            logger.warning("Session ID is not a string: Id={} type(id)={}", session_id, type(session_id))
            return None
        return session_id

    def select_session(self, session_id: str) -> None:
        logger.debug("Selecting session: {}", session_id)
        # TODO: check if it's truly necessary to check the UserRole of EACH session_list item.
        for index in range(self.session_list.count()):
            item = self.session_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == session_id:
                self.session_list.setCurrentItem(item)
                break

    def set_session_items(self, items: list[SessionListItemViewModel]) -> None:
        logger.debug("Setting {} session items", len(items))
        self.session_list.clear()
        for item_view_model in items:
            item = QListWidgetItem(item_view_model.title)
            item.setToolTip(item_view_model.subtitle)
            item.setData(Qt.ItemDataRole.UserRole, item_view_model.session_id)
            self.session_list.addItem(item)

    # --- Public API: Detection Helpers ---

    def set_detection_loading_state(self, is_loading: bool) -> None:
        logger.trace("Setting detection loading state: {}", is_loading)
        for widget in self.model_state_specific_widgets:
            widget.setEnabled(not is_loading)

    def set_tracking_loading_state(self, is_loading: bool) -> None:
        logger.trace("Setting tracking loading state: {}", is_loading)
        for widget in self.tracking_state_specific_widgets:
            widget.setEnabled(not is_loading)

    def set_detection_model_items(self, items: list[DetectionModelItemViewModel]) -> None:
        logger.trace("Setting detection model items: {}", len(items))
        self.model_combo_box.blockSignals(True)
        self.model_combo_box.clear()
        for item in items:
            self.model_combo_box.addItem(item.display_name, item.model_id)
        self.model_combo_box.blockSignals(False)

    def set_tracker_data_items(self, items: list[FrameDataItemViewModel]) -> None:
        """
        Sets the tracker (Layer D) data items in the table view.
        """
        logger.trace("Setting tracker (Layer D) data items: {}", len(items))
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
        logger.trace("Setting selected detection model: {}", model_id)
        self.model_combo_box.blockSignals(True)
        index = self.model_combo_box.findData(model_id)
        if index >= 0:
            self.model_combo_box.setCurrentIndex(index)
        self.model_combo_box.blockSignals(False)

    # --- Public API: Tab-aware helpers ---

    def get_active_tab_index(self) -> int:
        tab_widget_idx = self.data_tab.currentIndex()
        if tab_widget_idx is None:
            return -1
        return tab_widget_idx

    def get_active_frame_data_table(self) -> QTableWidget:
        if self.data_tab.currentIndex() == 1:
            return self.frame_tracker_data_table
        return self.frame_detection_data_table

    def get_frame_data_table(self) -> QTableWidget:
        return self.frame_detection_data_table

    def get_selected_frame_item_keys(self) -> list[str]:
        logger.trace("Getting selected frame item keys (tab-aware)")
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

    def get_selected_frame_item_key(self) -> str | None:
        logger.trace("Getting selected frame item key (tab-aware)")
        table = self.get_active_frame_data_table()
        row_index = table.currentRow()
        if row_index < 0:
            return None
        id_item = table.item(row_index, 0)
        if id_item is None:
            return None
        item_key = id_item.data(Qt.ItemDataRole.UserRole)
        return item_key if isinstance(item_key, str) else None

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

    # --- Public API: Navigation & Status ---

    def set_frame_label_text(self, text: str) -> None:
        logger.trace("Setting frame label text: {}", text)
        self.frame_label.setText(text)

    def set_seek_range(self, maximum_frame_index: int) -> None:
        logger.trace("Setting seek range: {}", maximum_frame_index)
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(max(0, maximum_frame_index))

    def set_seek_value(self, frame_index: int) -> None:
        logger.trace("Setting seek value: {}", frame_index)
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(max(0, frame_index))
        self.seek_slider.blockSignals(False)

    def set_status_text(self, text: str) -> None:
        logger.trace("Setting status text: {}", text)
        self.info_label.setText(text)

    def show_error(self, title: str, message: str) -> None:
        logger.trace("Error dialog shown: {}", message)
        QMessageBox.critical(self, title, message)

    # --- Protected: UI Construction ---

    def _build_status_bar(self) -> None:
        logger.debug("Building status bar")
        status = QStatusBar()
        status.addPermanentWidget(self.info_label, 1)
        self.setStatusBar(status)

    def _build_toolbar(self) -> None:
        logger.debug("Building toolbar")
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addAction(self.open_action)
        self.addToolBar(toolbar)

    def _build_ui(self) -> None:
        logger.debug("Building UI")
        central = QWidget()
        root_layout = QVBoxLayout(central)

        # 1. Top Row (Open Video button)
        top_row = QHBoxLayout()
        top_row.addWidget(self.open_button)
        top_row.addStretch()
        root_layout.addLayout(top_row)

        # 2. Main Horizontal Splitter
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- LEFT SIDE (Preview, Transport Controls, Data/Sessions) ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(self.preview_widget, 5)
        left_layout.addLayout(self._build_transport_controls())

        self._initialize_data_panels()
        left_layout.addWidget(self._build_bottom_data_panel(), 3)

        main_splitter.addWidget(left_panel)

        # --- RIGHT SIDE (ScrollArea + Custom Collapsible Groups) ---
        main_splitter.addWidget(self._build_right_panel())

        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)

        root_layout.addWidget(main_splitter, 1)
        self.setCentralWidget(central)

    def _build_transport_controls(self) -> QVBoxLayout:
        """Builds the Red Area: Seek slider and playback/detect controls."""
        transport_layout = QVBoxLayout()

        # Red Line: Seek Slider
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(0)
        self.seek_slider.setValue(0)
        transport_layout.addWidget(self.seek_slider)

        # Red Box: Buttons
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.play_button)
        btn_row.addWidget(self.pause_button)
        btn_row.addWidget(self.previous_button)
        btn_row.addWidget(self.next_button)
        btn_row.addWidget(self.detect_button)
        btn_row.addStretch()
        btn_row.addWidget(self.frame_label)

        transport_layout.addLayout(btn_row)
        return transport_layout

    def _build_bottom_data_panel(self) -> QWidget:
        """Builds the Blue Area: Data tabs alongside the session list."""
        self.data_tab.addTab(self.frame_detection_data_table, "Detected objects")
        self.data_tab.addTab(self.frame_tracker_data_table, "Tracking results")

        self.session_tab.addTab(self.session_list, "Opened files")

        # Main container for the bottom area
        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter for the tabs (Data vs Opened Files)
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        bottom_splitter.addWidget(self.data_tab)
        bottom_splitter.addWidget(self.session_tab)
        bottom_splitter.setStretchFactor(0, 3)
        bottom_splitter.setStretchFactor(1, 1)

        # Action row spanning across the bottom
        action_row = QHBoxLayout()
        action_row.addWidget(self.add_manual_button)
        action_row.addWidget(self.edit_item_button)
        action_row.addWidget(self.delete_item_button)
        action_row.addWidget(self.duplicate_item_button)
        action_row.addWidget(self.reset_frame_button)
        action_row.addWidget(self.reset_all_button)
        action_row.addStretch()

        # Add both to the layout
        bottom_layout.addWidget(bottom_splitter)
        bottom_layout.addLayout(action_row)

        return bottom_container

    def _build_right_panel(self) -> QScrollArea:
        """Builds the Green Area: Custom collapsible groups inside a scroll area."""
        self.tracking_source_combo_box.addItem("Raw Detections", "layer_a")
        self.tracking_source_combo_box.addItem("Reviewed Detections", "layer_b")

        self.tracking_strategy_combo_box.addItem("Dummy Tracker (Copy)", "dummy")
        self.tracking_strategy_combo_box.addItem("Hungarian IoU (Fast)", "hungarian")
        self.tracking_strategy_combo_box.addItem("ByteTrack (High Perf)", "bytetrack")
        self.tracking_strategy_combo_box.addItem("DeepSORT", "deepsort")
        self.tracking_strategy_combo_box.addItem("CSRT (Manual/Slow)", "csrt")

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(250)

        # Container to hold the independent collapsible boxes
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(5, 5, 5, 5)
        container_layout.setSpacing(10)

        # 1. Detection Group
        detection_box = CollapsibleBox("Background Detection")
        detection_box.add_widget(QLabel("Model:"))
        detection_box.add_widget(self.model_combo_box)
        detection_box.add_widget(self.detect_all_button)

        # 2. Tracking Group
        tracking_box = CollapsibleBox("Tracking")
        tracking_box.add_widget(QLabel("Source:"))
        tracking_box.add_widget(self.tracking_source_combo_box)
        tracking_box.add_widget(QLabel("Strategy:"))
        tracking_box.add_widget(self.tracking_strategy_combo_box)
        tracking_box.add_widget(self.track_button)

        container_layout.addWidget(detection_box)
        container_layout.addWidget(tracking_box)

        # Add stretch to push everything to the top when panels collapse
        container_layout.addStretch()

        scroll_area.setWidget(container)
        return scroll_area

    def _initialize_data_panels(self):
        self.frame_detection_data_table.setHorizontalHeaderLabels(
            ["ID", "Source", "Label", "Detection Confidence", "BBox", "Color"]
        )
        self.frame_detection_data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.frame_detection_data_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.frame_detection_data_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.frame_detection_data_table.verticalHeader().setVisible(False)
        self.frame_detection_data_table.horizontalHeader().setStretchLastSection(True)
        self.frame_detection_data_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        self.frame_tracker_data_table.setHorizontalHeaderLabels(
            ["ID", "Source", "Label", "Tracker Confidence", "BBox", "Color"]
        )
        self.frame_tracker_data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.frame_tracker_data_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.frame_tracker_data_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.frame_tracker_data_table.verticalHeader().setVisible(False)
        self.frame_tracker_data_table.horizontalHeader().setStretchLastSection(True)
        self.frame_tracker_data_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

    # --- Protected: Signal & Event Logic ---

    def _choose_video_files(self) -> None:
        logger.info("Launching file dialog to select video files to open...")
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Video Files",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.m4v);;All Files (*)",
        )
        if paths:
            self.open_videos_requested.emit(paths)

    def _connect_signals(self) -> None:
        logger.debug("Connecting signals")
        self.open_action.triggered.connect(self._choose_video_files)
        self.open_button.clicked.connect(self._choose_video_files)
        self.play_button.clicked.connect(self.play_requested.emit)
        self.pause_button.clicked.connect(self.pause_requested.emit)
        self.previous_button.clicked.connect(self.previous_frame_requested.emit)
        self.next_button.clicked.connect(self.next_frame_requested.emit)
        self.detect_button.clicked.connect(self.detect_current_frame_requested.emit)
        self.detect_all_button.clicked.connect(self.start_background_detection_requested.emit)
        self.track_button.clicked.connect(self._emit_start_tracking)
        self.add_manual_button.clicked.connect(self.add_manual_frame_item_requested.emit)
        self.edit_item_button.clicked.connect(self.edit_selected_frame_item_requested.emit)
        self.delete_item_button.clicked.connect(self.delete_selected_frame_item_requested.emit)
        self.duplicate_item_button.clicked.connect(self.duplicate_selected_frame_item_requested.emit)
        self.reset_frame_button.clicked.connect(self.reset_current_frame_review_requested.emit)
        self.reset_all_button.clicked.connect(self.reset_all_review_requested.emit)
        self.model_combo_box.currentIndexChanged.connect(self._emit_model_changed)
        self.seek_slider.sliderReleased.connect(self._emit_seek_requested)
        self.session_list.itemSelectionChanged.connect(self._emit_selected_session)
        self.frame_detection_data_table.itemSelectionChanged.connect(self._update_frame_item_action_state)
        self.frame_tracker_data_table.itemSelectionChanged.connect(self._update_frame_item_action_state)
        self.data_tab.currentChanged.connect(self._update_frame_item_action_state)

    def _emit_model_changed(self) -> None:
        logger.debug("Emitting model changed")
        model_id = self.model_combo_box.currentData()
        if isinstance(model_id, str):
            logger.debug("Emitting model changed: {}", model_id)
            self.detection_model_changed.emit(model_id)

    def _emit_seek_requested(self) -> None:
        logger.trace("Emitting seek requested")
        frame_index = self.seek_slider.value()
        logger.debug("Emitting seek request: frame_index={}", frame_index)
        self.seek_requested.emit(frame_index)

    def _emit_selected_session(self) -> None:
        logger.trace("Emitting selected session")
        item = self.session_list.currentItem()
        if item is None:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(session_id, str):
            self.session_selected.emit(session_id)

    def _emit_start_tracking(self) -> None:
        logger.debug("Emitting start tracking requested")
        strategy_id = self.tracking_strategy_combo_box.currentData()
        source_id = self.tracking_source_combo_box.currentData()
        if isinstance(strategy_id, str) and isinstance(source_id, str):
            self.start_tracking_requested.emit(strategy_id, source_id)

    def _update_frame_item_action_state(self) -> None:
        selected_count = len(self.get_selected_frame_item_keys())
        self.edit_item_button.setEnabled(selected_count == 1)
        self.delete_item_button.setEnabled(selected_count >= 1)
        self.duplicate_item_button.setEnabled(selected_count >= 1)

    # --- Special Methods ---

    def __repr__(self) -> str:
        return f"MainWindow(title={self.windowTitle()}, size={self.size()})"