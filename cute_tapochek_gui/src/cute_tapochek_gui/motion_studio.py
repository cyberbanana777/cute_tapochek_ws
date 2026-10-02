# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT

"""
rqt plugin "Motion Studio".

A thin client of motion_server: every action goes through its services and
the play_motion action, so the GUI holds no state of its own and the same
operations can be done from the terminal or from the behaviour FSM.

ROS callbacks run in rqt's executor thread; they never touch widgets
directly but emit Qt signals, which Qt delivers in the GUI thread.
"""

import re
import time

from python_qt_binding.QtCore import QObject, Qt, QTimer, Signal
from python_qt_binding.QtWidgets import (
    QAbstractItemView, QCheckBox, QDoubleSpinBox, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from rclpy.action import ActionClient
from rqt_gui_py.plugin import Plugin
from std_srvs.srv import SetBool, Trigger

from cute_tapochek_interfaces.action import PlayMotion
from cute_tapochek_interfaces.msg import MotionServerStatus as Status
from cute_tapochek_interfaces.srv import (
    DeleteMotion, ListMotions, SaveMotion, StartRecording)

SERVER_NS = ''  # motion_server interfaces live in the root namespace
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
STATUS_TIMEOUT = 1.5  # s without status -> server considered down

STATE_TEXT = {
    Status.STATE_IDLE: 'ожидание',
    Status.STATE_WAITING: 'жду, когда leader начнёт двигаться…',
    Status.STATE_RECORDING: 'ЗАПИСЬ',
    Status.STATE_PLAYING: 'проигрывание',
}
TELEOP_TEXT = {
    Status.TELEOP_UNKNOWN: 'неизвестно',
    Status.TELEOP_ENABLED: 'включено',
    Status.TELEOP_PAUSED: 'на паузе',
    Status.TELEOP_UNAVAILABLE: 'не запущено',
}


class _Bridge(QObject):
    """Carries data from ROS threads into the Qt thread."""

    status = Signal(object)
    log = Signal(str)
    progress = Signal(float)
    invoke = Signal(object, object)   # (callable, arg) executed in the Qt thread


class MotionStudio(Plugin):

    def __init__(self, context):
        super().__init__(context)
        self.setObjectName('MotionStudio')
        self._node = context.node
        self._status = None
        self._status_time = 0.0
        self._motions = []          # [(name, duration, description)]

        self._bridge = _Bridge()
        self._bridge.status.connect(self._on_status)
        self._bridge.log.connect(self._log)
        self._bridge.progress.connect(lambda v: self._progress.setValue(int(v * 1000)))
        self._bridge.invoke.connect(lambda fn, arg: fn(arg))

        self._build_ui()
        if context.serial_number() > 1:
            self._widget.setWindowTitle(
                f'{self._widget.windowTitle()} ({context.serial_number()})')
        context.add_widget(self._widget)

        n = self._node
        ns = SERVER_NS
        self._play = ActionClient(n, PlayMotion, f'{ns}/play_motion')
        self._srv = {
            'stop_motion': n.create_client(Trigger, f'{ns}/stop_motion'),
            'list': n.create_client(ListMotions, f'{ns}/list_motions'),
            'start_rec': n.create_client(StartRecording, f'{ns}/start_recording'),
            'stop_rec': n.create_client(Trigger, f'{ns}/stop_recording'),
            'discard': n.create_client(Trigger, f'{ns}/discard_recording'),
            'save': n.create_client(SaveMotion, f'{ns}/save_motion'),
            'delete': n.create_client(DeleteMotion, f'{ns}/delete_motion'),
            'teleop': n.create_client(SetBool, f'{ns}/set_teleop'),
        }
        self._status_sub = n.create_subscription(
            Status, f'{ns}/motion_server/status', self._bridge.status.emit, 10)

        self._watchdog = QTimer(self._widget)
        self._watchdog.timeout.connect(self._update_buttons)
        self._watchdog.start(500)
        QTimer.singleShot(800, self._refresh)
        self._update_buttons()

    # ================================================================== UI
    def _build_ui(self):
        w = self._widget = QWidget()
        w.setObjectName('MotionStudioUi')
        w.setWindowTitle('Motion Studio')
        root = QVBoxLayout(w)

        self._server_label = QLabel()
        root.addWidget(self._server_label)

        # ---- library
        lib = QGroupBox('Библиотека движений')
        lv = QVBoxLayout(lib)
        t = self._table = QTableWidget(0, 3)
        t.setHorizontalHeaderLabels(['Имя', 'Длительность, с', 'Описание'])
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.itemSelectionChanged.connect(self._update_buttons)
        t.itemDoubleClicked.connect(lambda _: self._play_selected())
        lv.addWidget(t)

        row = QHBoxLayout()
        row.addWidget(QLabel('Скорость ×'))
        self._speed = QDoubleSpinBox()
        self._speed.setRange(0.1, 2.0)
        self._speed.setSingleStep(0.1)
        self._speed.setValue(1.0)
        row.addWidget(self._speed)
        self._btn_play = self._button(row, '▶ Играть', self._play_selected)
        self._btn_stop = self._button(row, '■ Стоп', self._stop_motion)
        self._btn_delete = self._button(row, 'Удалить', self._delete_selected)
        row.addStretch()
        self._btn_refresh = self._button(row, 'Обновить', self._refresh)
        lv.addLayout(row)
        root.addWidget(lib)

        # ---- recording
        rec = QGroupBox('Запись с leader')
        rv = QVBoxLayout(rec)
        self._rec_label = QLabel()
        f = self._rec_label.font()
        f.setPointSize(f.pointSize() + 2)
        f.setBold(True)
        self._rec_label.setFont(f)
        rv.addWidget(self._rec_label)

        row = QHBoxLayout()
        self._btn_rec = self._button(row, '● Записать', self._start_recording)
        self._chk_wait = QCheckBox('ждать начала движения')
        self._chk_wait.setChecked(True)
        row.addWidget(self._chk_wait)
        self._btn_rec_stop = self._button(row, '■ Остановить', self._stop_recording)
        self._btn_preview = self._button(row, '▶ Посмотреть', self._preview)
        self._btn_discard = self._button(row, '✕ Выбросить', self._discard)
        row.addStretch()
        rv.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel('Имя:'))
        self._name = QLineEdit()
        self._name.setPlaceholderText('wave_hello')
        self._name.setMaxLength(64)
        self._name.textChanged.connect(self._update_buttons)
        row.addWidget(self._name)
        row.addWidget(QLabel('Описание:'))
        self._desc = QLineEdit()
        row.addWidget(self._desc, 2)
        self._btn_save = self._button(row, 'Сохранить', self._save)
        rv.addLayout(row)
        root.addWidget(rec)

        # ---- teleop
        tel = QGroupBox('Телеуправление')
        tv = QHBoxLayout(tel)
        self._teleop_label = QLabel()
        tv.addWidget(self._teleop_label)
        tv.addStretch()
        self._btn_teleop_on = self._button(tv, 'Включить', lambda: self._set_teleop(True))
        self._btn_teleop_off = self._button(tv, 'Пауза', lambda: self._set_teleop(False))
        root.addWidget(tel)

        # ---- progress + log
        self._progress = QProgressBar()
        self._progress.setRange(0, 1000)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(300)
        self._log_view.setMaximumHeight(110)
        root.addWidget(self._log_view)

    @staticmethod
    def _button(layout, text, slot):
        b = QPushButton(text)
        b.clicked.connect(slot)
        layout.addWidget(b)
        return b

    def _log(self, text: str):
        self._log_view.appendPlainText(f'{time.strftime("%H:%M:%S")}  {text}')

    def _selected_name(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).text()

    # =========================================================== status
    def _on_status(self, msg):
        self._status = msg
        self._status_time = time.monotonic()
        if msg.state == Status.STATE_PLAYING:
            self._progress.setValue(int(msg.progress * 1000))
        elif msg.state != Status.STATE_PLAYING and self._progress.value() not in (0, 1000):
            self._progress.setValue(0)
        self._update_buttons()

    def _server_alive(self) -> bool:
        return (self._status is not None
                and time.monotonic() - self._status_time < STATUS_TIMEOUT)

    def _update_buttons(self):
        alive = self._server_alive()
        s = self._status if alive else None
        self._server_label.setText(
            'motion_server: на связи' if alive else
            '<b style="color:#c62828">motion_server не отвечает</b>')

        state = s.state if s else ''
        recording = state in (Status.STATE_WAITING, Status.STATE_RECORDING)
        has_draft = bool(s and s.has_draft)
        selected = self._selected_name() is not None

        if not s:
            self._rec_label.setText('—')
        elif recording:
            extra = f' {s.recording_time:.1f} с' if state == Status.STATE_RECORDING else ''
            self._rec_label.setText(f'● {STATE_TEXT[state]}{extra}')
        elif state == Status.STATE_PLAYING:
            self._rec_label.setText(f'▶ {s.playing} {s.progress * 100:.0f}%')
        elif has_draft:
            self._rec_label.setText(f'Черновик: {s.draft_duration:.1f} с, не сохранён')
        else:
            self._rec_label.setText('Нет записи')
        self._rec_label.setStyleSheet('color:#c62828' if recording else '')
        self._teleop_label.setText(
            f'Состояние: {TELEOP_TEXT.get(s.teleop, s.teleop)}' if s else 'Состояние: —')

        self._btn_play.setEnabled(alive and selected)
        self._btn_stop.setEnabled(alive and state == Status.STATE_PLAYING)
        self._btn_delete.setEnabled(alive and selected)
        self._btn_refresh.setEnabled(alive)
        self._btn_rec.setEnabled(alive and not recording)
        self._chk_wait.setEnabled(not recording)
        self._btn_rec_stop.setEnabled(alive and recording)
        self._btn_preview.setEnabled(alive and has_draft and not recording)
        self._btn_discard.setEnabled(alive and (has_draft or recording))
        self._btn_save.setEnabled(
            alive and has_draft and not recording
            and bool(NAME_RE.match(self._name.text().strip())))
        self._btn_teleop_on.setEnabled(alive)
        self._btn_teleop_off.setEnabled(alive)

    # ========================================================= service calls
    def _call(self, key, request, label, on_done=None):
        client = self._srv[key]
        if not client.service_is_ready():
            self._log(f'{label}: motion_server недоступен')
            return
        future = client.call_async(request)

        def done(f):
            res = f.result()
            if res is None:
                self._bridge.log.emit(f'{label}: нет ответа')
                return
            if hasattr(res, 'success'):
                mark = 'OK' if res.success else 'ошибка'
                self._bridge.log.emit(f'{label}: {mark}, {res.message}')
            if on_done is not None:
                self._bridge.invoke.emit(on_done, res)
        future.add_done_callback(done)

    # -------------------------------------------------------------- library
    def _refresh(self):
        self._call('list', ListMotions.Request(), 'Список', self._fill_table)

    def _fill_table(self, res):
        selected = self._selected_name()
        self._motions = list(zip(res.names, res.durations, res.descriptions))
        t = self._table
        t.setRowCount(len(self._motions))
        for i, (name, dur, desc) in enumerate(self._motions):
            dur_item = QTableWidgetItem(f'{dur:.2f}')
            dur_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(i, 0, QTableWidgetItem(name))
            t.setItem(i, 1, dur_item)
            t.setItem(i, 2, QTableWidgetItem(desc))
            if name == selected:
                t.selectRow(i)
        t.resizeColumnToContents(0)
        self._update_buttons()

    def _play_selected(self):
        name = self._selected_name()
        if name:
            self._send_play(PlayMotion.Goal(name=name, speed=self._speed.value()), name)

    def _preview(self):
        self._send_play(
            PlayMotion.Goal(play_draft=True, speed=self._speed.value()), 'черновик')

    def _send_play(self, goal, label):
        if not self._play.server_is_ready():
            self._log('Играть: action play_motion недоступен')
            return
        self._log(f'Играть: {label}')
        future = self._play.send_goal_async(
            goal, feedback_callback=lambda fb: self._bridge.progress.emit(fb.feedback.progress))

        def accepted(f):
            handle = f.result()
            if handle is None or not handle.accepted:
                self._bridge.log.emit(f'Играть: {label} отклонено сервером')
                return
            def finished(r):
                wrapped = r.result()
                text = wrapped.result.message if wrapped is not None else 'нет результата'
                self._bridge.log.emit(f'Играть: {text}')
            handle.get_result_async().add_done_callback(finished)
        future.add_done_callback(accepted)

    def _stop_motion(self):
        self._call('stop_motion', Trigger.Request(), 'Стоп')

    def _delete_selected(self):
        name = self._selected_name()
        if not name:
            return
        if QMessageBox.question(
                self._widget, 'Удалить движение',
                f'Удалить «{name}» из библиотеки? Файл будет удалён с диска.') \
                != QMessageBox.Yes:
            return
        self._call('delete', DeleteMotion.Request(name=name), f'Удалить {name}',
                   lambda res: self._refresh())

    # ------------------------------------------------------------ recording
    def _start_recording(self):
        if self._status and self._status.has_draft:
            if QMessageBox.question(
                    self._widget, 'Новая запись',
                    'Есть несохранённый черновик. Он будет заменён новой записью. '
                    'Продолжить?') != QMessageBox.Yes:
                return
        req = StartRecording.Request(start_on_motion=self._chk_wait.isChecked())
        self._call('start_rec', req, 'Запись')

    def _stop_recording(self):
        self._call('stop_rec', Trigger.Request(), 'Остановить запись')

    def _discard(self):
        self._call('discard', Trigger.Request(), 'Выбросить')

    def _save(self):
        name = self._name.text().strip()
        if not NAME_RE.match(name):
            self._log('Сохранить: имя — латиница, цифры, "_" и "-", до 64 символов')
            return
        overwrite = False
        if name in (m[0] for m in self._motions):
            if QMessageBox.question(
                    self._widget, 'Перезаписать',
                    f'Движение «{name}» уже есть. Перезаписать?') != QMessageBox.Yes:
                return
            overwrite = True
        req = SaveMotion.Request(name=name, description=self._desc.text(), overwrite=overwrite)

        def saved(res):
            if res.success:
                self._name.clear()
                self._desc.clear()
                self._refresh()
        self._call('save', req, f'Сохранить {name}', saved)

    # --------------------------------------------------------------- teleop
    def _set_teleop(self, enabled: bool):
        self._call('teleop', SetBool.Request(data=enabled),
                   'Телеуправление: ' + ('включить' if enabled else 'пауза'))

    # ============================================================ rqt hooks
    def shutdown_plugin(self):
        self._watchdog.stop()
        self._node.destroy_subscription(self._status_sub)
        for client in self._srv.values():
            self._node.destroy_client(client)
        self._play.destroy()

    def save_settings(self, plugin_settings, instance_settings):
        instance_settings.set_value('speed', self._speed.value())
        instance_settings.set_value('wait_for_motion', self._chk_wait.isChecked())

    def restore_settings(self, plugin_settings, instance_settings):
        speed = instance_settings.value('speed')
        if speed is not None:
            self._speed.setValue(float(speed))
        wait = instance_settings.value('wait_for_motion')
        if wait is not None:
            self._chk_wait.setChecked(wait in (True, 'true', 'True', '1'))
