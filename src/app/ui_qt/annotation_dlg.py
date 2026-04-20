from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)


class ManualAnnotationDialog(QDialog):
    def __init__(
            self,
            parent=None,
            *,
            title: str = "Add Manual Annotation",
            initial_label: str = "",
            initial_bbox_xyxy: tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle(title)

        self._label_edit = QLineEdit()
        self._x1_spin = QSpinBox()
        self._y1_spin = QSpinBox()
        self._x2_spin = QSpinBox()
        self._y2_spin = QSpinBox()

        for spin_box in (self._x1_spin, self._y1_spin, self._x2_spin, self._y2_spin):
            spin_box.setRange(0, 100000)

        self._label_edit.setText(initial_label)
        self._x1_spin.setValue(initial_bbox_xyxy[0])
        self._y1_spin.setValue(initial_bbox_xyxy[1])
        self._x2_spin.setValue(initial_bbox_xyxy[2])
        self._y2_spin.setValue(initial_bbox_xyxy[3])

        form_layout = QFormLayout()
        form_layout.addRow("Label", self._label_edit)
        form_layout.addRow("X1", self._x1_spin)
        form_layout.addRow("Y1", self._y1_spin)
        form_layout.addRow("X2", self._x2_spin)
        form_layout.addRow("Y2", self._y2_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root_layout = QVBoxLayout(self)
        root_layout.addLayout(form_layout)
        root_layout.addWidget(buttons)

    def get_annotation_data(self) -> tuple[str, tuple[int, int, int, int]]:
        return (
            self._label_edit.text().strip(),
            (
                self._x1_spin.value(),
                self._y1_spin.value(),
                self._x2_spin.value(),
                self._y2_spin.value(),
            ),
        )