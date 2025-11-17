from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt5 import QtCore, QtWidgets

from . import db


class DialogForm(QtWidgets.QDialog):
    saved = QtCore.pyqtSignal()

    def __init__(self, dialog: Optional[dict] = None, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.dialog = dialog
        self.setWindowTitle("Редактирование диалога" if dialog else "Новый диалог")
        self.resize(420, 320)

        form_layout = QtWidgets.QFormLayout()
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("Название")
        self.description_edit = QtWidgets.QPlainTextEdit()
        self.description_edit.setPlaceholderText("Описание диалога")
        self.active_checkbox = QtWidgets.QCheckBox("Активен")
        self.active_checkbox.setChecked(True)

        form_layout.addRow("Название:", self.name_input)
        form_layout.addRow("Описание:", self.description_edit)
        form_layout.addRow("Статус:", self.active_checkbox)

        self.error_label = QtWidgets.QLabel()
        self.error_label.setStyleSheet("color: red")

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._handle_save)
        button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(self.error_label)
        layout.addWidget(button_box)

        if dialog:
            self._fill_form(dialog)

    def _fill_form(self, dialog: dict) -> None:
        self.name_input.setText(dialog.get("name", ""))
        self.description_edit.setPlainText(dialog.get("description", "") or "")
        self.active_checkbox.setChecked(bool(dialog.get("is_active", 1)))

    def _handle_save(self) -> None:
        name = self.name_input.text().strip()
        description = self.description_edit.toPlainText().strip()
        is_active = 1 if self.active_checkbox.isChecked() else 0

        if not name:
            self.error_label.setText("Введите название диалога")
            return

        payload = {"name": name, "description": description, "is_active": is_active}
        try:
            if self.dialog:
                db.update("dialogs", payload, "id=?", (self.dialog["id"],))
            else:
                db.insert("dialogs", payload)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return

        self.error_label.clear()
        self.saved.emit()
        self.accept()
