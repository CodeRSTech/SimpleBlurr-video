import sys

from PySide6.QtWidgets import QApplication

from app.application.editor_svc import EditorAppService
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

    app_service = EditorAppService()
    window = MainWindow()
    _controller = EditorController(
        app=app,
        window=window,
        app_service=app_service,
    )

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()