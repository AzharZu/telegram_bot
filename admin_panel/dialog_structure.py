from __future__ import annotations

import sqlite3
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from . import db


class DialogStructurePage(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.dialog_id: Optional[int] = None
        self.dialog_name: str = ""
        self._all_questions: List[dict] = []
        self._dialog_questions: List[dict] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        header_layout = QtWidgets.QHBoxLayout()
        self.dialog_label = QtWidgets.QLabel("Выберите диалог на вкладке 'Диалоги'")
        self.dialog_label.setStyleSheet("font-weight: bold")
        refresh_dialog_btn = QtWidgets.QPushButton("Обновить")
        refresh_dialog_btn.clicked.connect(self.reload_data)
        header_layout.addWidget(self.dialog_label)
        header_layout.addStretch()
        header_layout.addWidget(refresh_dialog_btn)

        content_layout = QtWidgets.QHBoxLayout()

        # Левая колонка с вопросами
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.addWidget(QtWidgets.QLabel("Все вопросы"))
        search_layout = QtWidgets.QHBoxLayout()
        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("Поиск вопросов")
        self.search_input.returnPressed.connect(self._load_all_questions)
        search_btn = QtWidgets.QPushButton("Поиск")
        search_btn.clicked.connect(self._load_all_questions)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)
        left_layout.addLayout(search_layout)

        self.all_table = QtWidgets.QTableView()
        self.all_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.all_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.all_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.all_table.verticalHeader().setVisible(False)
        self.all_table.horizontalHeader().setStretchLastSection(True)
        self.all_model = QtGui.QStandardItemModel(0, 4)
        self.all_model.setHorizontalHeaderLabels(["ID", "Вопрос", "Тип", "Активен"])
        self.all_table.setModel(self.all_model)
        left_layout.addWidget(self.all_table)

        # Центральная колонка с кнопками
        middle_layout = QtWidgets.QVBoxLayout()
        add_btn = QtWidgets.QPushButton("Добавить →")
        remove_btn = QtWidgets.QPushButton("Удалить")
        middle_layout.addStretch()
        middle_layout.addWidget(add_btn)
        middle_layout.addWidget(remove_btn)
        middle_layout.addStretch()

        add_btn.clicked.connect(self._handle_add)
        remove_btn.clicked.connect(self._handle_remove)

        # Правая колонка с выбранным диалогом
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(QtWidgets.QLabel("Вопросы диалога"))
        self.dialog_table = QtWidgets.QTableView()
        self.dialog_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.dialog_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.dialog_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.dialog_table.verticalHeader().setVisible(False)
        self.dialog_table.horizontalHeader().setStretchLastSection(True)
        self.dialog_model = QtGui.QStandardItemModel(0, 4)
        self.dialog_model.setHorizontalHeaderLabels(["№", "ID", "Вопрос", "Тип"])
        self.dialog_table.setModel(self.dialog_model)
        right_layout.addWidget(self.dialog_table)

        order_layout = QtWidgets.QHBoxLayout()
        up_btn = QtWidgets.QPushButton("↑")
        down_btn = QtWidgets.QPushButton("↓")
        order_layout.addWidget(up_btn)
        order_layout.addWidget(down_btn)
        order_layout.addStretch()
        right_layout.addLayout(order_layout)

        up_btn.clicked.connect(lambda: self._move_question(-1))
        down_btn.clicked.connect(lambda: self._move_question(1))

        content_layout.addLayout(left_layout, 2)
        content_layout.addLayout(middle_layout, 1)
        content_layout.addLayout(right_layout, 2)

        layout.addLayout(header_layout)
        layout.addLayout(content_layout)
        self._load_all_questions()

    def load_dialog(self, dialog: dict) -> None:
        self.dialog_id = dialog.get("id")
        self.dialog_name = dialog.get("name") or ""
        self.dialog_label.setText(f"Диалог: {self.dialog_name} (ID: {self.dialog_id})")
        self.reload_data()

    def reload_data(self) -> None:
        self._load_all_questions()
        self._load_dialog_questions()

    def _load_all_questions(self) -> None:
        term = self.search_input.text().strip()
        where = "is_active=1"
        params: List[str] = []
        if term:
            where += " AND question LIKE ?"
            params.append(f"%{term}%")
        try:
            self._all_questions = db.select_all("qa", where, params, order_by="id DESC")
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка загрузки", str(exc))
            return
        self.all_model.setRowCount(0)
        for row in self._all_questions:
            items = [
                QtGui.QStandardItem(str(row.get("id"))),
                QtGui.QStandardItem(row.get("question") or ""),
                QtGui.QStandardItem(row.get("type") or ""),
                QtGui.QStandardItem("Да" if row.get("is_active", 1) else "Нет"),
            ]
            for item in items:
                item.setEditable(False)
            self.all_model.appendRow(items)

    def _load_dialog_questions(self) -> None:
        if not self.dialog_id:
            self.dialog_model.setRowCount(0)
            self._dialog_questions = []
            return
        try:
            self._dialog_questions = db.fetch_dialog_questions(self.dialog_id)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка загрузки", str(exc))
            return
        self.dialog_model.setRowCount(0)
        for row in self._dialog_questions:
            items = [
                QtGui.QStandardItem(str(row.get("order_num"))),
                QtGui.QStandardItem(str(row.get("question_id"))),
                QtGui.QStandardItem(row.get("question") or ""),
                QtGui.QStandardItem(row.get("type") or ""),
            ]
            for item in items:
                item.setEditable(False)
            self.dialog_model.appendRow(items)

    def _selected_all_question(self) -> Optional[dict]:
        indexes = self.all_table.selectionModel().selectedRows()
        if not indexes:
            return None
        idx = indexes[0].row()
        if 0 <= idx < len(self._all_questions):
            return self._all_questions[idx]
        return None

    def _selected_dialog_question(self) -> Optional[dict]:
        indexes = self.dialog_table.selectionModel().selectedRows()
        if not indexes:
            return None
        idx = indexes[0].row()
        if 0 <= idx < len(self._dialog_questions):
            return self._dialog_questions[idx]
        return None

    def _handle_add(self) -> None:
        if not self.dialog_id:
            QtWidgets.QMessageBox.information(self, "Внимание", "Сначала выберите диалог")
            return
        question = self._selected_all_question()
        if not question:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите вопрос")
            return
        if any(row["question_id"] == question["id"] for row in self._dialog_questions):
            QtWidgets.QMessageBox.information(self, "Информация", "Вопрос уже в диалоге")
            return
        try:
            order_num = db.next_order_num(self.dialog_id)
            db.insert(
                "dialog_questions",
                {"dialog_id": self.dialog_id, "question_id": question["id"], "order_num": order_num},
            )
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return
        self._load_dialog_questions()

    def _handle_remove(self) -> None:
        if not self.dialog_id:
            return
        record = self._selected_dialog_question()
        if not record:
            QtWidgets.QMessageBox.information(self, "Внимание", "Выберите вопрос диалога")
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Удаление",
            "Удалить вопрос из диалога?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return
        try:
            db.delete(
                "dialog_questions",
                "dialog_id=? AND question_id=?",
                (self.dialog_id, record["question_id"]),
            )
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return
        self._load_dialog_questions()

    def _move_question(self, direction: int) -> None:
        if not self.dialog_id:
            return
        record = self._selected_dialog_question()
        if not record:
            return
        current_index = self._dialog_questions.index(record)
        target_index = current_index + direction
        if target_index < 0 or target_index >= len(self._dialog_questions):
            return
        target_record = self._dialog_questions[target_index]
        try:
            db.swap_order(self.dialog_id, record["question_id"], target_record["question_id"])
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return
        self._load_dialog_questions()
