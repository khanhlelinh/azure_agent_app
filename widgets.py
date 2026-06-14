# widgets.py
from PyQt6.QtWidgets import QTextEdit, QLineEdit
from PyQt6.QtCore import pyqtSignal

class AutoSaveTextEdit(QTextEdit):
    focusOut = pyqtSignal(str)
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focusOut.emit(self.toPlainText())

class AutoSaveLineEdit(QLineEdit):
    focusOut = pyqtSignal(str)
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focusOut.emit(self.text())