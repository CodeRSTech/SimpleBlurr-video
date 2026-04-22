import sys

from PySide6.QtWidgets import QApplication

from app.application.coordinator import AppCoordinator
from app.shared.logging_cfg import configure_logging
from app.ui_qt.controller import EditorController
from app.ui_qt.main_win import MainWindow


def main() -> None:
    configure_logging(
        console_level="DEBUG",
        file_level="TRACE",
        enabled_areas=None,
    )

    app = QApplication(sys.argv)

    # 1. Instantiate the new Application layer facade
    facade = AppCoordinator()

    # 2. Instantiate the UI
    window = MainWindow()

    # 3. Wire them together via the Controller
    controller = EditorController(app, window, facade)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()