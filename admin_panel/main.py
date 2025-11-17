from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt5 import QtWidgets

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from admin_panel.login_window import LoginWindow
from admin_panel.main_window import MainWindow


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    login_window = LoginWindow()
    main_window: Optional[MainWindow] = None

    def handle_authenticated(admin: dict) -> None:
        nonlocal main_window
        if main_window is None:
            main_window = MainWindow()
        main_window.show()
        login_window.close()

    login_window.authenticated.connect(handle_authenticated)
    login_window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
