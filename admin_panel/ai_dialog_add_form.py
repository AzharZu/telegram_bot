from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt5 import QtCore, QtWidgets

from . import db


class AIDialogAddForm(QtWidgets.QDialog):
    saved = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Добавить запись AI")
        self.resize(460, 360)

        form_layout = QtWidgets.QFormLayout()
        self.user_id_input = QtWidgets.QLineEdit()
        self.user_id_input.setPlaceholderText("ID пользователя (опционально)")
        self.question_edit = QtWidgets.QPlainTextEdit()
        self.question_edit.setPlaceholderText("Вопрос")
        self.answer_edit = QtWidgets.QPlainTextEdit()
        self.answer_edit.setPlaceholderText("Ответ")

        form_layout.addRow("User ID:", self.user_id_input)
        form_layout.addRow("Вопрос:", self.question_edit)
        form_layout.addRow("Ответ:", self.answer_edit)

        self.error_label = QtWidgets.QLabel()
        self.error_label.setStyleSheet("color: red")

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._handle_save)
        button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(self.error_label)
        layout.addWidget(button_box)

    def _handle_save(self) -> None:
        question = self.question_edit.toPlainText().strip()
        answer = self.answer_edit.toPlainText().strip()
        user_id_text = self.user_id_input.text().strip()

        if not question or not answer:
            self.error_label.setText("Введите вопрос и ответ")
            return

        data = {"question": question, "answer": answer}
        if user_id_text:
            try:
                data["user_id"] = int(user_id_text)
            except ValueError:
                self.error_label.setText("User ID должен быть числом")
                return
        try:
            db.insert("ai_logs", data)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return

        self.error_label.clear()
        self.saved.emit()
        self.accept()
