from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout

from local_transcriber.export.service import FORMATS


class ExportDialog(QDialog):
    def __init__(self, parent, localize):
        super().__init__(parent)
        self.setWindowTitle(localize("Экспорт стенограммы", "Export transcript"))
        self.file_format = QComboBox()
        for entry in FORMATS:
            self.file_format.addItem(entry.upper(), entry)
        self.timestamps = QCheckBox(localize("Показывать таймкоды", "Show timestamps"))
        self.timestamps.setChecked(True)
        self.precision = QComboBox()
        self.precision.addItem("HH:MM:SS", "seconds")
        self.precision.addItem("HH:MM:SS.mmm", "milliseconds")
        self.timestamps.toggled.connect(self.precision.setEnabled)
        self.speakers = QCheckBox(localize("Показывать спикеров", "Show speakers"))
        self.speakers.setChecked(True)
        self.separate = QCheckBox(localize("Интервал между репликами", "Space between phrases"))
        self.separate.setChecked(True)
        self.bom = QCheckBox(localize("UTF-8 с BOM для TXT", "UTF-8 BOM for TXT"))
        self.file_format.currentIndexChanged.connect(self._update_bom)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(localize("Выбрать файл…", "Choose file…"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(localize("Отмена", "Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QFormLayout(self)
        layout.addRow(localize("Формат", "Format"), self.file_format)
        layout.addRow(self.timestamps)
        layout.addRow(localize("Точность таймкодов", "Timestamp precision"), self.precision)
        layout.addRow(self.speakers)
        layout.addRow(self.separate)
        layout.addRow(self.bom)
        layout.addRow(buttons)

    def _update_bom(self):
        self.bom.setEnabled(self.file_format.currentData() == "txt")

    def arguments(self, filename: Path, language: str) -> list[str]:
        file_format = self.file_format.currentData()
        args = ["--format", file_format, "--output", str(filename), "--language", language,
                "--precision", self.precision.currentData()]
        for selected, flag in (
            (not self.timestamps.isChecked(), "--no-timestamps"),
            (not self.speakers.isChecked(), "--no-speakers"),
            (not self.separate.isChecked(), "--compact"),
            (file_format == "txt" and self.bom.isChecked(), "--bom"),
        ):
            if selected:
                args.append(flag)
        return args
