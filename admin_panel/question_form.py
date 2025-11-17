from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt5 import QtCore, QtWidgets

from . import db


class QuestionForm(QtWidgets.QDialog):
    saved = QtCore.pyqtSignal()

    def __init__(self, question: Optional[dict] = None, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.question = question
        self.setWindowTitle("Редактирование вопроса" if question else "Добавление вопроса")
        self.resize(480, 320)

        form_layout = QtWidgets.QFormLayout()
        self.question_edit = QtWidgets.QPlainTextEdit()
        self.question_edit.setPlaceholderText("Текст вопроса")
        self.question_edit.setTabChangesFocus(True)
        self.type_input = QtWidgets.QLineEdit()
        self.type_input.setPlaceholderText("Тип (например, sweet)")
        self.active_checkbox = QtWidgets.QCheckBox("Активный")
        self.active_checkbox.setChecked(True)

        form_layout.addRow("Вопрос:", self.question_edit)
        form_layout.addRow("Тип:", self.type_input)
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

        if question:
            self._fill_form(question)

    def _fill_form(self, question: dict) -> None:
        self.question_edit.setPlainText(question.get("question", ""))
        self.type_input.setText(question.get("type", "") or "")
        self.active_checkbox.setChecked(bool(question.get("is_active", 1)))

    def _handle_save(self) -> None:
        question_text = self.question_edit.toPlainText().strip()
        type_text = self.type_input.text().strip() or "general"
        is_active = 1 if self.active_checkbox.isChecked() else 0

        if not question_text:
            self.error_label.setText("Введите текст вопроса")
            return

        payload = {"question": question_text, "type": type_text, "is_active": is_active}

        try:
            if self.question:
                db.update("qa", payload, "id=?", (self.question["id"],))
            else:
                db.insert("qa", payload)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return

        self.error_label.clear()
        self.saved.emit()
        self.accept()
