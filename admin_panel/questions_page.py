from __future__ import annotations

import sqlite3
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from . import db
from .question_form import QuestionForm


class QuestionsPage(QtWidgets.QWidget):
    data_changed = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = []
        self._setup_ui()
        self.load_questions()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        search_layout = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Поиск по вопросу")
        self.search_input.returnPressed.connect(self.load_questions)
        search_btn = QtWidgets.QPushButton("Поиск")
        search_btn.clicked.connect(self.load_questions)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)

        self.table = QtWidgets.QTableView()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.model = QtGui.QStandardItemModel(0, 4)
        self.model.setHorizontalHeaderLabels(["ID", "Вопрос", "Тип", "Активный"])
        self.table.setModel(self.model)

        buttons_layout = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Добавить")
        edit_btn = QtWidgets.QPushButton("Редактировать")
        delete_btn = QtWidgets.QPushButton("Удалить")
        buttons_layout.addWidget(add_btn)
        buttons_layout.addWidget(edit_btn)
        buttons_layout.addWidget(delete_btn)
        buttons_layout.addStretch()

        add_btn.clicked.connect(self._open_create)
        edit_btn.clicked.connect(self._open_edit)
        delete_btn.clicked.connect(self._delete_question)

        layout.addLayout(search_layout)
        layout.addWidget(self.table)
        layout.addLayout(buttons_layout)

    def load_questions(self) -> None:
        term = self.search_input.text().strip()
        where = None
        params: List[str] = []
        if term:
            where = "question LIKE ?"
            params = [f"%{term}%"]
        try:
            self._rows = db.select_all("qa", where, params, order_by="id DESC")
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка загрузки", str(exc))
            return

        self.model.setRowCount(0)
        for row in self._rows:
            items = [
                QtGui.QStandardItem(str(row.get("id"))),
                QtGui.QStandardItem(row.get("question") or ""),
                QtGui.QStandardItem(row.get("type") or ""),
                QtGui.QStandardItem("Да" if row.get("is_active", 1) else "Нет"),
            ]
            for item in items:
                item.setEditable(False)
            self.model.appendRow(items)

    def _get_selected_row(self) -> Optional[dict]:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        row_idx = indexes[0].row()
        if 0 <= row_idx < len(self._rows):
            return self._rows[row_idx]
        return None

    def _open_create(self) -> None:
        dialog = QuestionForm(parent=self)
        dialog.saved.connect(self._handle_data_updated)
        dialog.exec_()

    def _open_edit(self) -> None:
        selected = self._get_selected_row()
        if not selected:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите запись для редактирования")
            return
        dialog = QuestionForm(question=selected, parent=self)
        dialog.saved.connect(self._handle_data_updated)
        dialog.exec_()

    def _delete_question(self) -> None:
        selected = self._get_selected_row()
        if not selected:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите запись для удаления")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Удаление",
            "Пометить вопрос как неактивный?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        try:
            db.update("qa", {"is_active": 0}, "id=?", (selected["id"],))
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return
        self._handle_data_updated()

    def _handle_data_updated(self) -> None:
        self.load_questions()
        self.data_changed.emit()
