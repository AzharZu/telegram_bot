from __future__ import annotations

import sqlite3
from typing import Optional

from PyQt5 import QtCore, QtWidgets

from . import db


class LoginWindow(QtWidgets.QWidget):
    authenticated = QtCore.pyqtSignal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FindFood Admin — вход")
        self.resize(360, 220)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel("Админ-панель FindFood")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold")

        form_layout = QtWidgets.QFormLayout()
        self.login_input = QtWidgets.QLineEdit()
        self.login_input.setPlaceholderText("Логин")
        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password_input.setPlaceholderText("Пароль")
        form_layout.addRow("Логин:", self.login_input)
        form_layout.addRow("Пароль:", self.password_input)

        self.error_label = QtWidgets.QLabel()
        self.error_label.setStyleSheet("color: red")

        login_btn = QtWidgets.QPushButton("Войти")
        login_btn.clicked.connect(self._handle_login)
        self.password_input.returnPressed.connect(self._handle_login)

        layout.addWidget(title)
        layout.addLayout(form_layout)
        layout.addWidget(self.error_label)
        layout.addWidget(login_btn)
        layout.addStretch()

    def _handle_login(self) -> None:
        login = self.login_input.text().strip()
        password = self.password_input.text().strip()

        if not login or not password:
            self.error_label.setText("Введите логин и пароль")
            return
        try:
            admin = db.select_one("admins", "login=?", (login,))
        except sqlite3.Error as exc:
            QtWidgets.QMessageBox.critical(self, "Ошибка БД", str(exc))
            return
        if not admin or admin.get("password") != password:
            self.error_label.setText("Неверный логин или пароль")
            return
        self.error_label.clear()
        self.authenticated.emit(admin)
