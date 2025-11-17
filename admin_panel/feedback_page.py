from __future__ import annotations

import sqlite3
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from . import db


class FeedbackPage(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = []
        self._current_filter = "all"
        self._setup_ui()
        self.load_feedback()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(QtWidgets.QLabel("Фильтр:"))
        self.filter_group = QtWidgets.QButtonGroup(self)
        all_btn = QtWidgets.QRadioButton("Все")
        all_btn.setChecked(True)
        liked_btn = QtWidgets.QRadioButton("Liked")
        disliked_btn = QtWidgets.QRadioButton("Disliked")
        self.filter_group.addButton(all_btn, 0)
        self.filter_group.addButton(liked_btn, 1)
        self.filter_group.addButton(disliked_btn, 2)
        for btn in (all_btn, liked_btn, disliked_btn):
            filter_layout.addWidget(btn)
        filter_layout.addStretch()
        self.filter_group.buttonClicked.connect(self._on_filter_changed)

        self.table = QtWidgets.QTableView()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.model = QtGui.QStandardItemModel(0, 4)
        self.model.setHorizontalHeaderLabels(["ID", "Вопрос", "Ответ", "Liked"])
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

        toggle_btn = QtWidgets.QPushButton("Изменить оценку")
        toggle_btn.clicked.connect(self._toggle_like)

        layout.addLayout(filter_layout)
        layout.addWidget(self.table)
        layout.addWidget(toggle_btn)
        layout.addLayout(preview_layout)

    def _on_filter_changed(self, button: QtWidgets.QAbstractButton) -> None:
        data = self.filter_group.id(button)
        if data == 1:
            self._current_filter = "liked"
        elif data == 2:
            self._current_filter = "disliked"
        else:
            self._current_filter = "all"
        self.load_feedback()

    def load_feedback(self) -> None:
        where = None
        params: List[int] = []
        if self._current_filter == "liked":
            where = "liked=1"
        elif self._current_filter == "disliked":
            where = "liked=0"
        try:
            self._rows = db.select_all("ai_feedback", where, params, order_by="id DESC", limit=500)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка загрузки", str(exc))
            return
        self.model.setRowCount(0)
        for row in self._rows:
            items = [
                QtGui.QStandardItem(str(row.get("id"))),
                QtGui.QStandardItem((row.get("question") or "").strip()),
                QtGui.QStandardItem((row.get("answer") or "").strip()),
                QtGui.QStandardItem("👍" if row.get("liked") else "👎"),
            ]
            for item in items:
                item.setEditable(False)
            self.model.appendRow(items)
        self.question_preview.clear()
        self.answer_preview.clear()

    def _selected_row(self) -> Optional[dict]:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        idx = indexes[0].row()
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

    def _update_preview(self) -> None:
        record = self._selected_row()
        if not record:
            self.question_preview.clear()
            self.answer_preview.clear()
            return
        self.question_preview.setPlainText(record.get("question") or "")
        self.answer_preview.setPlainText(record.get("answer") or "")

    def _toggle_like(self) -> None:
        record = self._selected_row()
        if not record:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите запись")
            return
        new_value = 0 if record.get("liked") else 1
        try:
            db.update("ai_feedback", {"liked": new_value}, "id=?", (record["id"],))
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return
        self.load_feedback()
