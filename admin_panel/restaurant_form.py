from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt5 import QtCore, QtWidgets

from . import db


class RestaurantForm(QtWidgets.QDialog):
    saved = QtCore.pyqtSignal()

    def __init__(self, restaurant: Optional[dict] = None, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.restaurant = restaurant
        self.setWindowTitle("Редактирование ресторана" if restaurant else "Добавить ресторан")
        self.resize(480, 360)

        form_layout = QtWidgets.QFormLayout()
        self.name_input = QtWidgets.QLineEdit()
        self.city_input = QtWidgets.QLineEdit()
        self.cuisine_input = QtWidgets.QLineEdit()
        self.rating_input = QtWidgets.QDoubleSpinBox()
        self.rating_input.setRange(0, 10)
        self.rating_input.setDecimals(1)
        self.rating_input.setSingleStep(0.1)
        self.rating_input.setValue(4.5)
        self.description_edit = QtWidgets.QPlainTextEdit()

        form_layout.addRow("Название:", self.name_input)
        form_layout.addRow("Город:", self.city_input)
        form_layout.addRow("Кухня:", self.cuisine_input)
        form_layout.addRow("Рейтинг:", self.rating_input)
        form_layout.addRow("Описание:", self.description_edit)

        self.error_label = QtWidgets.QLabel()
        self.error_label.setStyleSheet("color: red")

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._handle_save)
        button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(self.error_label)
        layout.addWidget(button_box)

        if restaurant:
            self._fill_form(restaurant)

    def _fill_form(self, restaurant: dict) -> None:
        self.name_input.setText(restaurant.get("name", ""))
        self.city_input.setText(restaurant.get("city", ""))
        self.cuisine_input.setText(restaurant.get("cuisine", "") or "")
        if restaurant.get("rating") is not None:
            self.rating_input.setValue(float(restaurant["rating"]))
        self.description_edit.setPlainText(restaurant.get("description", "") or "")

    def _handle_save(self) -> None:
        name = self.name_input.text().strip()
        city = self.city_input.text().strip()
        cuisine = self.cuisine_input.text().strip()
        rating = float(self.rating_input.value())
        description = self.description_edit.toPlainText().strip()

        if not name or not city:
            self.error_label.setText("Название и город обязательны")
            return

        payload = {
            "name": name,
            "city": city,
            "cuisine": cuisine,
            "rating": rating,
            "description": description,
        }
        try:
            if self.restaurant:
                db.update("restaurants", payload, "id=?", (self.restaurant["id"],))
            else:
                db.insert("restaurants", payload)
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return

        self.error_label.clear()
        self.saved.emit()
        self.accept()
