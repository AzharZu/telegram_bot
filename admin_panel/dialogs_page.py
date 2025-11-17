from __future__ import annotations

import sqlite3
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from . import db
from .dialog_form import DialogForm


class DialogsPage(QtWidgets.QWidget):
    open_structure_requested = QtCore.pyqtSignal(dict)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = []
        self._setup_ui()
        self.load_dialogs()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        search_layout = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Поиск по названию")
        self.search_input.returnPressed.connect(self.load_dialogs)
        search_btn = QtWidgets.QPushButton("Поиск")
        search_btn.clicked.connect(self.load_dialogs)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)

        self.table = QtWidgets.QTableView()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.model = QtGui.QStandardItemModel(0, 4)
        self.model.setHorizontalHeaderLabels(["ID", "Название", "Активен", "Описание"])
        self.table.setModel(self.model)

        buttons_layout = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Добавить")
        edit_btn = QtWidgets.QPushButton("Редактировать")
        delete_btn = QtWidgets.QPushButton("Удалить")
        structure_btn = QtWidgets.QPushButton("Открыть структуру")
        buttons_layout.addWidget(add_btn)
        buttons_layout.addWidget(edit_btn)
        buttons_layout.addWidget(delete_btn)
        buttons_layout.addWidget(structure_btn)
        buttons_layout.addStretch()

        add_btn.clicked.connect(self._open_create)
        edit_btn.clicked.connect(self._open_edit)
        delete_btn.clicked.connect(self._delete_dialog)
        structure_btn.clicked.connect(self._open_structure)

        layout.addLayout(search_layout)
        layout.addWidget(self.table)
        layout.addLayout(buttons_layout)

    def load_dialogs(self) -> None:
        term = self.search_input.text().strip()
        where = None
        params: List[str] = []
        if term:
            where = "name LIKE ? OR description LIKE ?"
            term_like = f"%{term}%"
            params = [term_like, term_like]
        try:
            self._rows = db.select_all("dialogs", where, params, order_by="id DESC")
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка загрузки", str(exc))
            return

        self.model.setRowCount(0)
        for row in self._rows:
            items = [
                QtGui.QStandardItem(str(row.get("id"))),
                QtGui.QStandardItem(row.get("name") or ""),
                QtGui.QStandardItem("Да" if row.get("is_active", 1) else "Нет"),
                QtGui.QStandardItem(row.get("description") or ""),
            ]
            for item in items:
                item.setEditable(False)
            self.model.appendRow(items)

    def _get_selected_row(self) -> Optional[dict]:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        idx = indexes[0].row()
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

    def _open_create(self) -> None:
        dialog = DialogForm(parent=self)
        dialog.saved.connect(self._handle_saved)
        dialog.exec_()

    def _open_edit(self) -> None:
        record = self._get_selected_row()
        if not record:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите диалог для редактирования")
            return
        dialog = DialogForm(record, parent=self)
        dialog.saved.connect(self._handle_saved)
        dialog.exec_()

    def _delete_dialog(self) -> None:
        record = self._get_selected_row()
        if not record:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите диалог для удаления")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Удаление",
            "Удалить диалог вместе со структурой?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        try:
            db.delete("dialogs", "id=?", (record["id"],))
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return
        self._handle_saved()

    def _open_structure(self) -> None:
        record = self._get_selected_row()
        if not record:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите диалог")
            return
        self.open_structure_requested.emit(record)

    def _handle_saved(self) -> None:
        self.load_dialogs()
