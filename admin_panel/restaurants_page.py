from __future__ import annotations

import sqlite3
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from . import db
from .restaurant_form import RestaurantForm


class RestaurantsPage(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: List[dict] = []
        self._setup_ui()
        self.load_restaurants()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        search_layout = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Поиск по названию или городу")
        self.search_input.returnPressed.connect(self.load_restaurants)
        search_btn = QtWidgets.QPushButton("Поиск")
        search_btn.clicked.connect(self.load_restaurants)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)

        self.table = QtWidgets.QTableView()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.model = QtGui.QStandardItemModel(0, 5)
        self.model.setHorizontalHeaderLabels(["ID", "Название", "Город", "Кухня", "Рейтинг"])
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
        delete_btn.clicked.connect(self._delete)

        layout.addLayout(search_layout)
        layout.addWidget(self.table)
        layout.addLayout(buttons_layout)

    def load_restaurants(self) -> None:
        term = self.search_input.text().strip()
        where = None
        params: List[str] = []
        if term:
            where = "name LIKE ? OR city LIKE ?"
            like = f"%{term}%"
            params = [like, like]
        try:
            self._rows = db.select_all("restaurants", where, params, order_by="id DESC", limit=500)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка загрузки", str(exc))
            return
        self.model.setRowCount(0)
        for row in self._rows:
            items = [
                QtGui.QStandardItem(str(row.get("id"))),
                QtGui.QStandardItem(row.get("name") or ""),
                QtGui.QStandardItem(row.get("city") or ""),
                QtGui.QStandardItem(row.get("cuisine") or ""),
                QtGui.QStandardItem(str(row.get("rating")) if row.get("rating") is not None else ""),
            ]
            for item in items:
                item.setEditable(False)
            self.model.appendRow(items)

    def _selected_row(self) -> Optional[dict]:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        idx = indexes[0].row()
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

    def _open_create(self) -> None:
        dialog = RestaurantForm(parent=self)
        dialog.saved.connect(self.load_restaurants)
        dialog.exec_()

    def _open_edit(self) -> None:
        record = self._selected_row()
        if not record:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите запись")
            return
        dialog = RestaurantForm(record, parent=self)
        dialog.saved.connect(self.load_restaurants)
        dialog.exec_()

    def _delete(self) -> None:
        record = self._selected_row()
        if not record:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите запись")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Удаление",
            f"Удалить ресторан {record.get('name')}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        try:
            db.delete("restaurants", "id=?", (record["id"],))
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return
        self.load_restaurants()
