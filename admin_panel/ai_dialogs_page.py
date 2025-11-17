from __future__ import annotations

import sqlite3
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from . import db
from .ai_dialog_add_form import AIDialogAddForm


class AIDialogsPage(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = []
        self._setup_ui()
        self.load_logs()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        header_layout = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Поиск по вопросу")
        self.search_input.returnPressed.connect(self.load_logs)
        search_btn = QtWidgets.QPushButton("Поиск")
        search_btn.clicked.connect(self.load_logs)
        add_btn = QtWidgets.QPushButton("Добавить тестовую запись")
        add_btn.clicked.connect(self._open_add_dialog)
        header_layout.addWidget(self.search_input)
        header_layout.addWidget(search_btn)
        header_layout.addStretch()
        header_layout.addWidget(add_btn)

        self.table = QtWidgets.QTableView()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.model = QtGui.QStandardItemModel(0, 5)
        self.model.setHorizontalHeaderLabels(["ID", "User ID", "Вопрос", "Ответ", "Создано"])
        self.table.setModel(self.model)
        self.table.selectionModel().selectionChanged.connect(self._update_preview)

        preview_layout = QtWidgets.QHBoxLayout()
        self.question_preview = QtWidgets.QPlainTextEdit()
        self.question_preview.setReadOnly(True)
        self.question_preview.setPlaceholderText("Полный текст вопроса")
        self.answer_preview = QtWidgets.QPlainTextEdit()
        self.answer_preview.setReadOnly(True)
        self.answer_preview.setPlaceholderText("Полный текст ответа")
        preview_layout.addWidget(self.question_preview)
        preview_layout.addWidget(self.answer_preview)

        layout.addLayout(header_layout)
        layout.addWidget(self.table)
        layout.addLayout(preview_layout)

    def load_logs(self) -> None:
        term = self.search_input.text().strip()
        where = None
        params: List[str] = []
        if term:
            where = "question LIKE ?"
            params = [f"%{term}%"]
        try:
            self._rows = db.select_all("ai_logs", where, params, order_by="id DESC", limit=500)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка загрузки", str(exc))
            return
        self.model.setRowCount(0)
        for row in self._rows:
            items = [
                QtGui.QStandardItem(str(row.get("id"))),
                QtGui.QStandardItem(str(row.get("user_id")) if row.get("user_id") is not None else ""),
                QtGui.QStandardItem(self._short_text(row.get("question"))),
                QtGui.QStandardItem(self._short_text(row.get("answer"))),
                QtGui.QStandardItem(row.get("created_at") or ""),
            ]
            for item in items:
                item.setEditable(False)
            self.model.appendRow(items)
        self.question_preview.clear()
        self.answer_preview.clear()

    def _short_text(self, value: Optional[str], limit: int = 80) -> str:
        if not value:
            return ""
        value = value.strip()
        return value if len(value) <= limit else value[: limit - 1] + "…"

    def _select_current(self) -> Optional[dict]:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        idx = indexes[0].row()
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

    def _update_preview(self) -> None:
        record = self._select_current()
        if not record:
            self.question_preview.clear()
            self.answer_preview.clear()
            return
        self.question_preview.setPlainText(record.get("question") or "")
        self.answer_preview.setPlainText(record.get("answer") or "")

    def _open_add_dialog(self) -> None:
        dialog = AIDialogAddForm(parent=self)
        dialog.saved.connect(self.load_logs)
        dialog.exec_()
