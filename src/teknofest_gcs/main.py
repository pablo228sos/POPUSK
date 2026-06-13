from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from teknofest_gcs.config.settings import Settings
from teknofest_gcs.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Teknofest GCS")

    settings_path = Path("settings.yaml").resolve()
    _ensure_settings(settings_path)
    settings = Settings.load(settings_path)

    window = MainWindow(settings, settings_path)
    window.show()
    return app.exec()


def _ensure_settings(path: Path) -> None:
    if path.exists():
        return
    source = Path(__file__).resolve().parent / "config" / "default.yaml"
    shutil.copyfile(source, path)


if __name__ == "__main__":
    raise SystemExit(main())
