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
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget, QTabWidget,
)

from app.presentation.view_models import (
    DetectionModelItemViewModel,
    FrameDataItemViewModel,
    SessionListItemViewModel,
)
from app.shared.logging_cfg import get_logger
from app.ui_qt.prev_widget import PreviewWidget

logger = get_logger("UI->MainWindow")


class MainWindow(QMainWindow):
    """
    Main Qt application window.

    This class handles the layout and visual state of the application,
    exposing signals for the Controller to handle.
    """

    # --- Signals ---
    add_manual_frame_item_requested = Signal()
    delete_selected_frame_item_requested = Signal()
    detect_current_frame_requested = Signal()
    detection_model_changed = Signal(str)
    duplicate_selected_frame_item_requested = Signal()
    edit_selected_frame_item_requested = Signal()
    next_frame_requested = Signal()
    open_videos_requested = Signal(list)
    pause_requested = Signal()
    play_requested = Signal()
    previous_frame_requested = Signal()
    reset_all_review_requested = Signal()
    reset_current_frame_review_requested = Signal()
    seek_requested = Signal(int)
    session_selected = Signal(str)
    start_background_detection_requested = Signal()
    # NEW SIGNAL
    start_tracking_requested = Signal(str)

    def __init__(self) -> None:
        logger.info("Initializing UI (MainWindow)")
        super().__init__()

        self.setWindowTitle("Video App Rewrite")
        self.resize(1200, 800)

        self.open_action = QAction("Open Video(s)...", self)
        self.open_button = QPushButton("Open Video(s)")
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.previous_button = QPushButton("Previous Frame")
        self.next_button = QPushButton("Next Frame")
        self.detect_button = QPushButton("Detect Current Frame")
        self.detect_all_button = QPushButton("Start Background Detection")
        self.add_manual_button = QPushButton("Add Manual Box")
        self.edit_item_button = QPushButton("Edit Selected")
        self.delete_item_button = QPushButton("Delete Selected")
        self.duplicate_item_button = QPushButton("Duplicate To Next Frame")
        self.reset_frame_button = QPushButton("Reset Frame")
        self.reset_all_button = QPushButton("Reset All Review")
        self.model_combo_box = QComboBox()

        # NEW: Tracking Widgets
        self.track_button = QPushButton("Start Tracking")
        self.tracking_strategy_combo_box = QComboBox()
        # Add some placeholder strategies (Display Name, Internal ID)
        self.tracking_strategy_combo_box.addItem("ByteTrack (High Perf)", "bytetrack")
        self.tracking_strategy_combo_box.addItem("DeepSORT", "deepsort")
        self.tracking_strategy_combo_box.addItem("CSRT (Manual/Slow)", "csrt")

        self.preview_widget = PreviewWidget()
        self.session_list = QListWidget()
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_label = QLabel("Frame 0/0")
        self.info_label = QLabel("No session loaded")
        self.frame_detection_data_table = QTableWidget(0, 6)
        self.frame_tracker_data_table = QTableWidget(0, 6)
        self.data_tab = QTabWidget()
        self.data_tab.addTab(self.frame_detection_data_table, "Detected objects")
        self.data_tab.addTab(self.frame_tracker_data_table, "Tracking results")

        self._build_toolbar()
        self._build_ui()
        self._build_status_bar()
        self._connect_signals()
        self._update_frame_item_action_state()

    # --- Public API: Session Helpers ---

    def get_selected_session_id(self) -> str | None:
        """Return the session ID currently selected in the sidebar."""
        logger.trace("Getting selected session id")
        item = self.session_list.currentItem()
        if item is None:
            return None

        session_id = item.data(Qt.ItemDataRole.UserRole)
        return session_id if isinstance(session_id, str) else None

    def select_session(self, session_id: str) -> None:
        """Programmatically select a session in the list."""
        logger.debug("Selecting session: {}", session_id)
        for index in range(self.session_list.count()):
            item = self.session_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == session_id:
                self.session_list.setCurrentItem(item)
                break

    def set_session_items(self, items: list[SessionListItemViewModel]) -> None:
        """Populate the sidebar session list."""
        logger.debug("Setting session items")
        self.session_list.clear()

        for item_view_model in items:
            item = QListWidgetItem(item_view_model.title)
            item.setToolTip(item_view_model.subtitle)
            item.setData(Qt.ItemDataRole.UserRole, item_view_model.session_id)
            self.session_list.addItem(item)

    # --- Public API: Detection Helpers ---

    def set_detection_loading_state(self, is_loading: bool) -> None:
        """Toggle interactivity of detection controls during model loads."""
        logger.trace("Setting detection loading state: {}", is_loading)
        self.model_combo_box.setEnabled(not is_loading)
        self.detect_button.setEnabled(not is_loading)
        self.detect_all_button.setEnabled(not is_loading)

    def set_detection_model_items(
        self, items: list[DetectionModelItemViewModel]
    ) -> None:
        """Populate the model combo box."""
        logger.trace("Setting detection model items: {}", len(items))
        self.model_combo_box.blockSignals(True)
        self.model_combo_box.clear()

        for item in items:
            self.model_combo_box.addItem(item.display_name, item.model_id)

        self.model_combo_box.blockSignals(False)

    def set_selected_detection_model(self, model_id: str) -> None:
        """Update the combo box selection to match the active session."""
        logger.trace("Setting selected detection model: {}", model_id)
        self.model_combo_box.blockSignals(True)
        index = self.model_combo_box.findData(model_id)
        if index >= 0:
            self.model_combo_box.setCurrentIndex(index)
        self.model_combo_box.blockSignals(False)

    # --- Public API: Frame & Table Helpers ---

    def get_frame_data_table(self) -> QTableWidget:
        """Return the internal table widget."""
        return self.frame_detection_data_table

    def get_selected_frame_item_key(self) -> str | None:
        """Return the item key for the single currently focused row."""
        logger.trace("Getting selected frame item key")
        row_index = self.frame_detection_data_table.currentRow()
        if row_index < 0:
            return None

        id_item = self.frame_detection_data_table.item(row_index, 0)
        if id_item is None:
            return None

        item_key = id_item.data(Qt.ItemDataRole.UserRole)
        return item_key if isinstance(item_key, str) else None

    def get_selected_frame_item_keys(self) -> list[str]:
        """Return a list of item keys for all selected rows."""
        logger.trace("Getting selected frame item keys")
        selection_model = self.frame_detection_data_table.selectionModel()
        if selection_model is None:
            return []

        selected_keys: list[str] = []
        seen_keys: set[str] = set()

        for index in selection_model.selectedRows():
            id_item = self.frame_detection_data_table.item(index.row(), 0)
            if id_item is None:
                continue

            item_key = id_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(item_key, str) and item_key not in seen_keys:
                seen_keys.add(item_key)
                selected_keys.append(item_key)

        return selected_keys

    def set_frame_data_items(self, items: list[FrameDataItemViewModel]) -> None:
        """Rebuild the frame data table rows and restore selection."""
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
            self.frame_detection_data_table.setItem(
                row_index, 3, QTableWidgetItem(item.confidence_text)
            )
            self.frame_detection_data_table.setItem(
                row_index, 4, QTableWidgetItem(item.bbox_text)
            )
            self.frame_detection_data_table.setItem(
                row_index, 5, QTableWidgetItem(item.color_hex)
            )

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
        """Set the navigation frame label text."""
        logger.trace("Setting frame label text: {}", text)
        self.frame_label.setText(text)

    def set_seek_range(self, maximum_frame_index: int) -> None:
        """Set the slider's maximum range based on video metadata."""
        logger.trace("Setting seek range: {}", maximum_frame_index)
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(max(0, maximum_frame_index))

    def set_seek_value(self, frame_index: int) -> None:
        """Set the current slider position."""
        logger.trace("Setting seek value: {}", frame_index)
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(max(0, frame_index))
        self.seek_slider.blockSignals(False)

    def set_status_text(self, text: str) -> None:
        """Update the status bar text."""
        logger.trace("Setting status text: {}", text)
        self.info_label.setText(text)

    def show_error(self, title: str, message: str) -> None:
        """Display a critical error dialog."""
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

        top_row = self._build_top_row()
        root_layout.addLayout(top_row)

        nav_row = self._build_nav_row()
        root_layout.addLayout(nav_row)

        self._initialize_data_panels()

        action_row = QHBoxLayout()
        action_row.addWidget(self.add_manual_button)
        action_row.addWidget(self.edit_item_button)
        action_row.addWidget(self.delete_item_button)
        action_row.addWidget(self.duplicate_item_button)
        action_row.addWidget(self.reset_frame_button)
        action_row.addWidget(self.reset_all_button)
        action_row.addStretch(1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(self.preview_widget, 4)
        left_layout.addWidget(self.data_tab, 2)
        left_layout.addLayout(action_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(self.session_list)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter, 1)

        self.setCentralWidget(central)

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

    def _build_nav_row(self) -> QHBoxLayout:
        nav_row = QHBoxLayout()
        self.seek_slider.setMinimum(0)
        self.seek_slider.setMaximum(0)
        self.seek_slider.setValue(0)
        nav_row.addWidget(self.seek_slider, 1)
        nav_row.addWidget(self.frame_label)
        return nav_row

    def _build_top_row(self) -> QHBoxLayout:
        top_row = QHBoxLayout()
        top_row.addWidget(self.open_button)
        top_row.addWidget(self.play_button)
        top_row.addWidget(self.pause_button)
        top_row.addWidget(self.previous_button)
        top_row.addWidget(self.next_button)

        # Detection Controls
        top_row.addWidget(QLabel("Model:"))
        top_row.addWidget(self.model_combo_box)
        top_row.addWidget(self.detect_button)
        top_row.addWidget(self.detect_all_button)

        # NEW: Tracking Controls
        top_row.addSpacing(20)  # Add a little visual gap between detection and tracking
        top_row.addWidget(QLabel("Strategy:"))
        top_row.addWidget(self.tracking_strategy_combo_box)
        top_row.addWidget(self.track_button)

        return top_row

    # --- Protected: Signal & Event Logic ---

    def _choose_video_files(self) -> None:
        """Launch file dialog to select video files."""
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
        self.detect_all_button.clicked.connect(
            self.start_background_detection_requested.emit
        )
        # NEW: Connect the tracking button
        self.track_button.clicked.connect(self._emit_start_tracking)
        self.add_manual_button.clicked.connect(
            self.add_manual_frame_item_requested.emit
        )
        self.edit_item_button.clicked.connect(
            self.edit_selected_frame_item_requested.emit
        )
        self.delete_item_button.clicked.connect(
            self.delete_selected_frame_item_requested.emit
        )
        self.duplicate_item_button.clicked.connect(
            self.duplicate_selected_frame_item_requested.emit
        )
        self.reset_frame_button.clicked.connect(
            self.reset_current_frame_review_requested.emit
        )
        self.reset_all_button.clicked.connect(self.reset_all_review_requested.emit)
        self.model_combo_box.currentIndexChanged.connect(self._emit_model_changed)
        self.seek_slider.sliderReleased.connect(self._emit_seek_requested)
        self.session_list.itemSelectionChanged.connect(self._emit_selected_session)
        self.frame_detection_data_table.itemSelectionChanged.connect(
            self._update_frame_item_action_state
        )

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
        if isinstance(strategy_id, str):
            self.start_tracking_requested.emit(strategy_id)

    def _update_frame_item_action_state(self) -> None:
        """Enable/disable annotation buttons based on current table selection."""
        selected_count = len(self.get_selected_frame_item_keys())
        self.edit_item_button.setEnabled(selected_count == 1)
        self.delete_item_button.setEnabled(selected_count >= 1)
        self.duplicate_item_button.setEnabled(selected_count >= 1)

    # --- Special Methods ---

    def __repr__(self) -> str:
        return f"MainWindow(title={self.windowTitle()}, size={self.size()})"
