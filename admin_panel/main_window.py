from __future__ import annotations

from typing import List, Tuple

from PyQt5 import QtCore, QtWidgets

from .ai_dialogs_page import AIDialogsPage
from .dialog_structure import DialogStructurePage
from .dialogs_page import DialogsPage
from .feedback_page import FeedbackPage
from .questions_page import QuestionsPage
from .restaurants_page import RestaurantsPage


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FindFood Admin")
        self.resize(1320, 860)
        self._nav_buttons: List[QtWidgets.QPushButton] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        sidebar_widget = QtWidgets.QWidget()
        sidebar_layout = QtWidgets.QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(8)

        self.stack = QtWidgets.QStackedWidget()

        self.questions_page = QuestionsPage()
        self.dialogs_page = DialogsPage()
        self.dialog_structure_page = DialogStructurePage()
        self.ai_dialogs_page = AIDialogsPage()
        self.feedback_page = FeedbackPage()
        self.restaurants_page = RestaurantsPage()

        self.questions_page.data_changed.connect(self.dialog_structure_page.reload_data)
        self.dialogs_page.open_structure_requested.connect(self._open_dialog_structure)

        pages: List[Tuple[str, QtWidgets.QWidget]] = [
            ("Вопросы", self.questions_page),
            ("Диалоги", self.dialogs_page),
            ("Структура диалога", self.dialog_structure_page),
            ("AI История", self.ai_dialogs_page),
            ("AI Feedback", self.feedback_page),
            ("Рестораны", self.restaurants_page),
        ]

        for idx, (title, widget) in enumerate(pages):
            self.stack.addWidget(widget)
            btn = QtWidgets.QPushButton(title)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, i=idx: self._switch_page(i))
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sidebar_layout.addStretch()

        layout.addWidget(sidebar_widget)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        if self._nav_buttons:
            self._nav_buttons[0].setChecked(True)
            self.stack.setCurrentIndex(0)

    def _switch_page(self, index: int) -> None:
        if index < 0 or index >= self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        for idx, button in enumerate(self._nav_buttons):
            button.setChecked(idx == index)

    def _open_dialog_structure(self, dialog: dict) -> None:
        self.dialog_structure_page.load_dialog(dialog)
        target_index = self.stack.indexOf(self.dialog_structure_page)
        if target_index != -1:
            self._switch_page(target_index)
