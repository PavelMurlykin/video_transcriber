import json
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from local_transcriber.core.offline_guard import offline_environment


class CliProcess(QObject):
    message = Signal(dict)
    done = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        environment = QProcessEnvironment()
        for key, value in offline_environment().items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(self._stdout)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self._buffers = [b"", b""]

    def start(self, arguments: list[str]) -> None:
        self._buffers = [b"", b""]
        self.process.setArguments(["-u", "-m", "local_transcriber", *arguments])
        self.process.start()

    def _stdout(self):
        self._read(0, bytes(self.process.readAllStandardOutput()))

    def _stderr(self):
        self._read(1, bytes(self.process.readAllStandardError()))

    def _read(self, channel, data):
        lines = (self._buffers[channel] + data).split(b"\n")
        self._buffers[channel] = lines.pop()
        for line in lines:
            self._message(line)

    def _message(self, line):
        try:
            payload = json.loads(line)
        except (ValueError, UnicodeError):
            return
        if isinstance(payload, dict):
            self.message.emit(payload)

    def _finished(self, code, exit_status):
        self._stdout()
        self._stderr()
        for ending in self._buffers:
            if ending:
                self._message(ending)
        self.done.emit(code if exit_status == QProcess.ExitStatus.NormalExit else -1)

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.done.emit(-1)
