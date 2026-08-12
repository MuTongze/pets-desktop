import ctypes
import json
import math
import os
import random
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSettings,
    QSharedMemory,
    Signal,
    QTemporaryDir,
    QTimer,
    Qt,
    Slot,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from input_statistics import (
    InputStatisticsDialog,
    InputStatisticsStore,
    POLL_KEY_CODES,
    STATISTICS_FILENAME,
    normalize_windows_key,
)


APP_NAME = "豆豆桌宠"
APP_VERSION = "1.7.0"
DEFAULT_PET_HEIGHT = 150
MIN_PET_HEIGHT = 90
MAX_PET_HEIGHT = 365
SIZE_PRESET_VERSION = 2
CONFIG_FILENAME = "豆豆桌宠配置.ini"
SINGLE_INSTANCE_KEY = "DoudouDesktopPet.SingleInstance.v1"
AUTOSTART_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "DoudouDesktopPet"


def resource_path(relative_path):
    """Return a resource path that works both in source and PyInstaller builds."""
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def settings_file_path():
    if getattr(sys, "frozen", False):
        base_path = Path(sys.executable).resolve().parent
    else:
        base_path = Path(__file__).resolve().parent
    return base_path / CONFIG_FILENAME


def file_settings(path=None):
    target = Path(path) if path is not None else settings_file_path()
    return QSettings(str(target), QSettings.Format.IniFormat)


def create_single_instance_guard(key=SINGLE_INSTANCE_KEY, parent=None):
    guard = QSharedMemory(key, parent)
    if guard.create(1):
        return guard
    return None


def autostart_command():
    if getattr(sys, "frozen", False):
        arguments = [str(Path(sys.executable).resolve())]
    else:
        arguments = [
            str(Path(sys.executable).resolve()),
            str(Path(__file__).resolve()),
        ]
    return subprocess.list2cmdline(arguments)


def is_autostart_enabled():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_REGISTRY_PATH,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return bool(str(value).strip())
    except FileNotFoundError:
        return False


def set_autostart_enabled(enabled):
    if enabled:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_REGISTRY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                AUTOSTART_VALUE_NAME,
                0,
                winreg.REG_SZ,
                autostart_command(),
            )
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_REGISTRY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
    except FileNotFoundError:
        pass


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def smoothstep(value):
    value = clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class GlobalInputWatcher(QObject):
    """Observe physical input without recording text or injecting input."""

    mouse_clicked = Signal(str)
    key_pressed = Signal()
    key_pressed_detailed = Signal(str)
    activity_detected = Signal()
    _hook_failed = Signal()

    MOUSE_BUTTONS = {"left": 0x01, "right": 0x02, "middle": 0x04}
    _MOUSE_DOWN_MESSAGES = {
        0x0201: "left",  # WM_LBUTTONDOWN
        0x0204: "right",  # WM_RBUTTONDOWN
        0x0207: "middle",  # WM_MBUTTONDOWN
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._supported = sys.platform == "win32"
        self._enabled = False
        self._user32 = ctypes.windll.user32 if self._supported else None
        self._kernel32 = ctypes.windll.kernel32 if self._supported else None
        self._hook_thread = None
        self._hook_thread_id = None
        self._keyboard_hook = None
        self._mouse_hook = None
        self._keyboard_callback = None
        self._mouse_callback = None
        self._pressed_keys = set()
        self._last_mouse_activity = 0.0

        self._key_states = {}
        self._mouse_states = {}
        self._last_cursor_pos = None
        self._using_fallback = False
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setInterval(16)
        self._fallback_timer.timeout.connect(self._poll_fallback)
        self._hook_failed.connect(self._start_polling_fallback)

    def _is_down(self, virtual_key):
        return bool(self._user32.GetAsyncKeyState(virtual_key) & 0x8000)

    def set_enabled(self, enabled):
        enabled = bool(enabled and self._supported)
        if enabled:
            if self._enabled and (
                self._using_fallback
                or (self._hook_thread is not None and self._hook_thread.is_alive())
            ):
                return
            self._enabled = True
            self._ensure_hook_running()
            return

        self._enabled = False
        self._fallback_timer.stop()
        self._using_fallback = False
        self._key_states.clear()
        self._mouse_states.clear()
        self._pressed_keys.clear()
        self._last_cursor_pos = None
        thread_id = self._hook_thread_id
        if thread_id:
            self._user32.PostThreadMessageW(thread_id, 0x0012, 0, 0)  # WM_QUIT

    def _ensure_hook_running(self):
        if not self._enabled or self._using_fallback:
            return
        if self._hook_thread is not None and self._hook_thread.is_alive():
            QTimer.singleShot(50, self._ensure_hook_running)
            return
        self._hook_thread = threading.Thread(
            target=self._run_hooks,
            name="DoudouInputHooks",
            daemon=True,
        )
        self._hook_thread.start()

    def _run_hooks(self):
        hook_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        user32 = self._user32
        kernel32 = self._kernel32
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            hook_proc_type,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        self._hook_thread_id = kernel32.GetCurrentThreadId()
        if not self._enabled:
            self._hook_thread_id = None
            return

        def keyboard_proc(code, message_id, data_pointer):
            if code >= 0 and self._enabled:
                info = ctypes.cast(
                    data_pointer, ctypes.POINTER(_KBDLLHOOKSTRUCT)
                ).contents
                if not info.flags & 0x10:  # LLKHF_INJECTED
                    key_id = normalize_windows_key(
                        info.vkCode, info.scanCode, info.flags
                    )
                    if message_id in (0x0100, 0x0104):  # KEYDOWN / SYSKEYDOWN
                        if key_id not in self._pressed_keys:
                            self._pressed_keys.add(key_id)
                            self.key_pressed_detailed.emit(key_id)
                            self.key_pressed.emit()
                            self.activity_detected.emit()
                    elif message_id in (0x0101, 0x0105):  # KEYUP / SYSKEYUP
                        self._pressed_keys.discard(key_id)
            return user32.CallNextHookEx(None, code, message_id, data_pointer)

        def mouse_proc(code, message_id, data_pointer):
            if code >= 0 and self._enabled:
                info = ctypes.cast(
                    data_pointer, ctypes.POINTER(_MSLLHOOKSTRUCT)
                ).contents
                if not info.flags & 0x01:  # LLMHF_INJECTED
                    button = self._MOUSE_DOWN_MESSAGES.get(message_id)
                    if button:
                        self.mouse_clicked.emit(button)
                        self.activity_detected.emit()
                    elif message_id == 0x0200:  # WM_MOUSEMOVE
                        now = time.monotonic()
                        if now - self._last_mouse_activity >= 0.25:
                            self._last_mouse_activity = now
                            self.activity_detected.emit()
            return user32.CallNextHookEx(None, code, message_id, data_pointer)

        self._keyboard_callback = hook_proc_type(keyboard_proc)
        self._mouse_callback = hook_proc_type(mouse_proc)
        module_handle = kernel32.GetModuleHandleW(None)
        self._keyboard_hook = user32.SetWindowsHookExW(
            13, self._keyboard_callback, module_handle, 0
        )
        self._mouse_hook = user32.SetWindowsHookExW(
            14, self._mouse_callback, module_handle, 0
        )
        if not self._keyboard_hook or not self._mouse_hook:
            if self._keyboard_hook:
                user32.UnhookWindowsHookEx(self._keyboard_hook)
            if self._mouse_hook:
                user32.UnhookWindowsHookEx(self._mouse_hook)
            self._keyboard_hook = None
            self._mouse_hook = None
            self._hook_thread_id = None
            self._hook_failed.emit()
            return

        try:
            while self._enabled:
                result = user32.GetMessageW(
                    ctypes.byref(message), None, 0, 0
                )
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._keyboard_hook:
                user32.UnhookWindowsHookEx(self._keyboard_hook)
            if self._mouse_hook:
                user32.UnhookWindowsHookEx(self._mouse_hook)
            self._keyboard_hook = None
            self._mouse_hook = None
            self._hook_thread_id = None
            self._pressed_keys.clear()

    @Slot()
    def _start_polling_fallback(self):
        if not self._enabled:
            return
        self._using_fallback = True
        self._key_states = {
            virtual_key: self._is_down(virtual_key)
            for virtual_key in POLL_KEY_CODES
        }
        self._mouse_states = {
            name: self._is_down(virtual_key)
            for name, virtual_key in self.MOUSE_BUTTONS.items()
        }
        self._last_cursor_pos = QCursor.pos()
        self._fallback_timer.start()

    def _poll_fallback(self):
        if not self._enabled:
            return
        activity = False
        cursor_pos = QCursor.pos()
        if self._last_cursor_pos is not None and cursor_pos != self._last_cursor_pos:
            activity = True
        self._last_cursor_pos = cursor_pos

        for name, virtual_key in self.MOUSE_BUTTONS.items():
            is_down = self._is_down(virtual_key)
            if is_down and not self._mouse_states.get(name, False):
                self.mouse_clicked.emit(name)
                activity = True
            self._mouse_states[name] = is_down

        for virtual_key in POLL_KEY_CODES:
            is_down = self._is_down(virtual_key)
            if is_down and not self._key_states.get(virtual_key, False):
                key_id = normalize_windows_key(virtual_key)
                self.key_pressed_detailed.emit(key_id)
                self.key_pressed.emit()
                activity = True
            self._key_states[virtual_key] = is_down
        if activity:
            self.activity_detected.emit()


class SpeechBubble(QWidget):
    """A lightweight, click-through speech bubble shown outside the pet."""

    def __init__(self):
        super().__init__(None)
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(224, 78)
        self._text = ""
        self._tail_direction = "down"
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_message(self, text, pet_rect, screen_rect, topmost=True):
        self._text = text
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, topmost)

        gap = 10
        bubble_width = self.width()
        bubble_height = self.height()

        if pet_rect.top() - bubble_height - gap >= screen_rect.top():
            x = pet_rect.center().x() - bubble_width // 2
            y = pet_rect.top() - bubble_height - gap
            self._tail_direction = "down"
        elif pet_rect.right() + bubble_width + gap <= screen_rect.right():
            x = pet_rect.right() + gap
            y = pet_rect.center().y() - bubble_height // 2
            self._tail_direction = "left"
        elif pet_rect.left() - bubble_width - gap >= screen_rect.left():
            x = pet_rect.left() - bubble_width - gap
            y = pet_rect.center().y() - bubble_height // 2
            self._tail_direction = "right"
        else:
            x = pet_rect.center().x() - bubble_width // 2
            y = pet_rect.bottom() + gap
            self._tail_direction = "up"

        x = clamp(x, screen_rect.left(), screen_rect.right() - bubble_width + 1)
        y = clamp(y, screen_rect.top(), screen_rect.bottom() - bubble_height + 1)
        self.move(x, y)
        self.update()
        self.show()
        self.raise_()
        self._hide_timer.start(2400)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        margin = 3.0
        tail = 12.0
        body = QRectF(margin, margin, self.width() - margin * 2, self.height() - margin * 2)
        if self._tail_direction == "down":
            body.adjust(0, 0, 0, -tail)
        elif self._tail_direction == "up":
            body.adjust(0, tail, 0, 0)
        elif self._tail_direction == "left":
            body.adjust(tail, 0, 0, 0)
        else:
            body.adjust(0, 0, -tail, 0)

        fill = QColor(255, 252, 240, 248)
        outline = QColor(85, 67, 52, 235)
        path = QPainterPath()
        path.addRoundedRect(body, 16, 16)

        if self._tail_direction == "down":
            center = body.center().x()
            triangle = QPolygonF(
                [
                    QPoint(int(center - 9), int(body.bottom() - 1)),
                    QPoint(int(center + 9), int(body.bottom() - 1)),
                    QPoint(int(center), int(self.height() - margin)),
                ]
            )
        elif self._tail_direction == "up":
            center = body.center().x()
            triangle = QPolygonF(
                [
                    QPoint(int(center - 9), int(body.top() + 1)),
                    QPoint(int(center + 9), int(body.top() + 1)),
                    QPoint(int(center), int(margin)),
                ]
            )
        elif self._tail_direction == "left":
            center = body.center().y()
            triangle = QPolygonF(
                [
                    QPoint(int(body.left() + 1), int(center - 9)),
                    QPoint(int(body.left() + 1), int(center + 9)),
                    QPoint(int(margin), int(center)),
                ]
            )
        else:
            center = body.center().y()
            triangle = QPolygonF(
                [
                    QPoint(int(body.right() - 1), int(center - 9)),
                    QPoint(int(body.right() - 1), int(center + 9)),
                    QPoint(int(self.width() - margin), int(center)),
                ]
            )

        painter.setPen(QPen(outline, 2.2))
        painter.setBrush(fill)
        painter.drawPath(path)
        painter.drawPolygon(triangle)

        text_rect = body.adjusted(15, 7, -15, -7)
        painter.setPen(QColor(69, 52, 42))
        font = QFont("Microsoft YaHei UI", 11)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self._text,
        )


class DialogueEditorDialog(QDialog):
    dialogues_changed = Signal(dict)

    CATEGORY_LABELS = {
        "jump": "点击：跳跃",
        "squash": "点击：压扁回弹",
        "shake": "点击：左右抖动",
        "mouse": "跟随：鼠标点击",
        "keyboard": "跟随：键盘输入",
        "idle": "空闲动作",
    }

    def __init__(self, dialogues, defaults, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑豆豆的对话")
        self.setMinimumSize(560, 440)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._defaults = {
            key: list(defaults.get(key, [])) for key in self.CATEGORY_LABELS
        }
        self._dialogues = {
            key: list(dialogues.get(key, self._defaults[key]))
            for key in self.CATEGORY_LABELS
        }
        self._current_key = None
        self._loading_category = False

        description = QLabel(
            "选择动作分类后，可以新增、删除或双击修改句子。"
            "输入框里的文字在关闭窗口时也会自动加入。"
            "允许把某一类全部删空，届时该动作只播放动画，不显示气泡。"
        )
        description.setWordWrap(True)

        self.category_combo = QComboBox()
        for key, label in self.CATEGORY_LABELS.items():
            self.category_combo.addItem(label, key)

        self.dialogue_list = QListWidget()
        self.dialogue_list.setAlternatingRowColors(True)
        self.dialogue_list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )

        self.dialogue_input = QLineEdit()
        self.dialogue_input.setPlaceholderText("输入一句新的短对话，按回车即可添加")
        add_button = QPushButton("新增")
        delete_button = QPushButton("删除选中")
        reset_button = QPushButton("恢复本类内置对话")

        input_row = QHBoxLayout()
        input_row.addWidget(self.dialogue_input, 1)
        input_row.addWidget(add_button)

        action_row = QHBoxLayout()
        action_row.addWidget(delete_button)
        action_row.addWidget(reset_button)
        action_row.addStretch(1)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.button(QDialogButtonBox.StandardButton.Close).setText("完成")

        layout = QVBoxLayout(self)
        layout.addWidget(description)
        layout.addWidget(self.category_combo)
        layout.addWidget(self.dialogue_list, 1)
        layout.addLayout(input_row)
        layout.addLayout(action_row)
        layout.addWidget(button_box)

        self.setStyleSheet(
            """
            QDialog {
                background: #fffaf0;
                color: #45352b;
                font: 10pt "Microsoft YaHei UI";
            }
            QComboBox, QLineEdit, QListWidget {
                background: white;
                border: 1px solid #cdb9a5;
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton {
                background: #f1dac1;
                border: 1px solid #c8aa8c;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover { background: #ead0b3; }
            """
        )

        self.category_combo.currentIndexChanged.connect(self._switch_category)
        self.dialogue_input.returnPressed.connect(self._add_dialogue)
        add_button.clicked.connect(self._add_dialogue)
        delete_button.clicked.connect(self._delete_selected)
        reset_button.clicked.connect(self._reset_current_category)
        button_box.rejected.connect(self.reject)
        self.dialogue_list.itemChanged.connect(self._emit_dialogues_changed)

        self._switch_category(self.category_combo.currentIndex())

    def _store_current_category(self):
        if self._current_key is None:
            return
        values = []
        for index in range(self.dialogue_list.count()):
            value = self.dialogue_list.item(index).text().strip()
            if value and value not in values:
                values.append(value)
        self._dialogues[self._current_key] = values

    def _switch_category(self, index):
        self._store_current_category()
        self._current_key = self.category_combo.itemData(index)
        self._loading_category = True
        try:
            self.dialogue_list.clear()
            if self._current_key is not None:
                self.dialogue_list.addItems(self._dialogues[self._current_key])
        finally:
            self._loading_category = False

    def _add_dialogue(self):
        value = self.dialogue_input.text().strip()
        if not value:
            return
        existing = {
            self.dialogue_list.item(index).text().strip()
            for index in range(self.dialogue_list.count())
        }
        if value not in existing:
            self.dialogue_list.addItem(value)
            self.dialogue_list.scrollToBottom()
            self._emit_dialogues_changed()
        self.dialogue_input.clear()
        self.dialogue_input.setFocus()

    def _delete_selected(self):
        rows = sorted(
            {self.dialogue_list.row(item) for item in self.dialogue_list.selectedItems()},
            reverse=True,
        )
        for row in rows:
            self.dialogue_list.takeItem(row)
        if rows:
            self._emit_dialogues_changed()

    def _reset_current_category(self):
        if self._current_key is None:
            return
        self._loading_category = True
        try:
            self.dialogue_list.clear()
            self.dialogue_list.addItems(self._defaults[self._current_key])
        finally:
            self._loading_category = False
        self._emit_dialogues_changed()

    def _emit_dialogues_changed(self, *args):
        del args
        if self._loading_category:
            return
        self._store_current_category()
        self.dialogues_changed.emit(
            {key: list(values) for key, values in self._dialogues.items()}
        )

    def configured_dialogues(self):
        if self.dialogue_input.text().strip():
            self._add_dialogue()
        self._store_current_category()
        return {key: list(values) for key, values in self._dialogues.items()}


class DesktopPet(QWidget):
    IDLE_ACTIONS = {
        "yawn": "打哈欠",
        "stretch_pose": "伸懒腰",
        "look": "左右张望",
        "wave": "挥爪招呼",
    }
    POSE_FILES = {
        "typing_left": "assets/poses_v2/typing_left.png",
        "typing_right": "assets/poses_v2/typing_right.png",
        "mouse_ready": "assets/poses_v2/mouse_ready.png",
        "mouse_click": "assets/poses_v2/mouse_click.png",
        "idle_yawn": "assets/poses_v2/idle_yawn.png",
        "idle_stretch": "assets/poses_v2/idle_stretch.png",
        "idle_look_left": "assets/poses_v2/idle_look_left.png",
        "idle_look_right": "assets/poses_v2/idle_look_right.png",
        "idle_wave": "assets/poses_v2/idle_wave.png",
    }

    DIALOGUES = {
        "jump": [
            "起飞！今天也要轻盈～",
            "跳一下，烦恼掉一地！",
            "看我原地升空！",
            "汪！云朵借我踩一下。",
            "这一下有冠军水平吧？",
        ],
        "squash": [
            "我只是暂时变扁啦！",
            "弹性小狗，拒绝内耗。",
            "压一压，马上满血！",
            "别慌，我会自己回弹。",
            "今日份压力已释放！",
        ],
        "shake": [
            "抖掉一点小烦恼～",
            "信号满格，尾巴代收！",
            "左右确认：你最可爱。",
            "启动快乐扫描！",
            "晃一晃，灵感就来啦！",
        ],
        "mouse": [
            "你点一下，豆豆也点一下！",
            "咔哒！这个我也会。",
            "鼠标交给我，效率汪汪涨！",
            "点到哪里，快乐跟到哪里。",
        ],
        "keyboard": [
            "你敲字，豆豆负责加速！",
            "噼里啪啦，灵感来啦！",
            "键盘搭子已上线。",
            "这段代码一定很厉害！",
            "继续敲，我在旁边伴奏～",
        ],
        "idle": [
            "忙完记得摸摸豆豆。",
            "豆豆在认真帮你看桌面。",
            "休息十秒，也算充电。",
            "今天也要对自己好一点。",
        ],
    }

    def __init__(
        self,
        enable_system_input=True,
        settings=None,
    ):
        super().__init__(None)
        self.settings = settings or file_settings()
        if not self.settings.contains("settings_initialized"):
            self.settings.setValue("settings_initialized", True)
            self.settings.sync()
        if (
            self.settings.value("size_preset_version", 0, type=int)
            < SIZE_PRESET_VERSION
        ):
            self.settings.setValue("pet_height", DEFAULT_PET_HEIGHT)
            self.settings.setValue("size_preset_version", SIZE_PRESET_VERSION)
            self.settings.sync()
        self._topmost = self.settings.value("topmost", True, type=bool)
        self._input_echo_enabled = self.settings.value(
            "input_echo_enabled", True, type=bool
        )
        self._idle_enabled = self.settings.value("idle_enabled", True, type=bool)
        self._idle_interval_seconds = int(
            clamp(
                self.settings.value("idle_interval_seconds", 20, type=int),
                5,
                300,
            )
        )
        saved_idle_actions = self.settings.value(
            "idle_actions", ",".join(self.IDLE_ACTIONS.keys()), type=str
        )
        idle_action_migration = {
            "nod": "yawn",
            "stretch": "stretch_pose",
            "look": "look",
            "breathe": "wave",
        }
        self._enabled_idle_actions = set()
        for saved_action in saved_idle_actions.split(","):
            action = idle_action_migration.get(saved_action, saved_action)
            if action in self.IDLE_ACTIONS:
                self._enabled_idle_actions.add(action)
        if not self._enabled_idle_actions:
            self._enabled_idle_actions = set(self.IDLE_ACTIONS.keys())
        self._dialogues = self._load_dialogues()
        self._enable_system_input = bool(enable_system_input)
        self._pet_height = clamp(
            self.settings.value("pet_height", DEFAULT_PET_HEIGHT, type=int),
            MIN_PET_HEIGHT,
            MAX_PET_HEIGHT,
        )
        self._interaction_index = 0
        self._animation = None
        self._animation_base_rect = None
        self._press_global = None
        self._drag_origin = None
        self._dragging = False
        self._overlay_kind = None
        self._overlay_progress = 0.0
        self._overlay_animation = None
        self._typing_phase = 0
        self._typing_deadline = 0.0
        self._last_input_bubble = 0.0
        self._last_key_bob = 0.0
        self._input_reactions_suspended = False
        self._statistics_dialog = None

        self.pet_pixmap = QPixmap(str(resource_path("assets/pet_cropped.png")))
        if self.pet_pixmap.isNull():
            raise RuntimeError("无法加载桌宠图片资源 assets/pet_cropped.png")
        self.pet_image = self.pet_pixmap.toImage()
        self._pose_pixmaps = {}
        self._pose_images = {}
        for pose_name, relative_path in self.POSE_FILES.items():
            pixmap = QPixmap(str(resource_path(relative_path)))
            if pixmap.isNull():
                raise RuntimeError("无法加载完整姿态资源 {}".format(relative_path))
            self._pose_pixmaps[pose_name] = pixmap
            self._pose_images[pose_name] = pixmap.toImage()
        self._active_pose = None
        self._pose_mode = None
        self._pose_anchor_rect = None
        self._pose_sequence = []
        self._pose_sequence_index = 0

        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if self._topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setWindowTitle(APP_NAME)
        icon_path = resource_path("assets/pet.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.bubble = SpeechBubble()
        statistics_path = Path(self.settings.fileName()).resolve().with_name(
            STATISTICS_FILENAME
        )
        self.statistics = InputStatisticsStore(statistics_path, self)
        self.input_watcher = GlobalInputWatcher(self)
        self.input_watcher.mouse_clicked.connect(self.react_to_mouse_click)
        self.input_watcher.mouse_clicked.connect(self.statistics.record_mouse)
        self.input_watcher.key_pressed.connect(self.react_to_keyboard_press)
        self.input_watcher.key_pressed_detailed.connect(
            self.statistics.record_key
        )
        self.input_watcher.activity_detected.connect(self._reset_idle_timer)

        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(120)
        self._typing_timer.timeout.connect(self._tick_typing)

        self._pose_timer = QTimer(self)
        self._pose_timer.setSingleShot(True)
        self._pose_timer.timeout.connect(self._advance_pose_sequence)

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._idle_reaction)

        self._resize_to_pet_height(self._pet_height, preserve_anchor=False)
        self._restore_or_place_window()
        self._refresh_input_watcher()
        self._reset_idle_timer()

    def _screen_geometry(self):
        center = self.frameGeometry().center()
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _restore_or_place_window(self):
        saved = self.settings.value("position")
        screen_rect = QGuiApplication.primaryScreen().availableGeometry()
        if isinstance(saved, QPoint):
            self.move(saved)
            current_screen = QGuiApplication.screenAt(self.frameGeometry().center())
            if current_screen is not None:
                screen_rect = current_screen.availableGeometry()
        else:
            self.move(
                screen_rect.right() - self.width() - 36,
                screen_rect.bottom() - self.height() - 36,
            )
        self._keep_inside(screen_rect)

    def _keep_inside(self, screen_rect=None):
        screen_rect = screen_rect or self._screen_geometry()
        x = clamp(self.x(), screen_rect.left(), screen_rect.right() - self.width() + 1)
        y = clamp(self.y(), screen_rect.top(), screen_rect.bottom() - self.height() + 1)
        self.move(x, y)

    def _current_pixmap(self):
        return self._pose_pixmaps.get(self._active_pose, self.pet_pixmap)

    def _current_image(self):
        return self._pose_images.get(self._active_pose, self.pet_image)

    def _set_active_pose(self, pose_name, pose_mode=None):
        if pose_name is not None and pose_name not in self._pose_pixmaps:
            raise ValueError("未知姿态资源：{}".format(pose_name))

        if pose_name is None and self._pose_anchor_rect is not None:
            anchor_rect = QRect(self._pose_anchor_rect)
            self._active_pose = None
            self._pose_anchor_rect = None
            self.setGeometry(anchor_rect)
            self.update()
            return

        if pose_name is not None and self._pose_anchor_rect is None:
            self._pose_anchor_rect = QRect(self.geometry())

        anchor_rect = self._pose_anchor_rect or QRect(self.geometry())
        self._active_pose = pose_name
        if pose_mode is not None:
            self._pose_mode = pose_mode
        pixmap = self._current_pixmap()
        width = max(
            1,
            round(self._pet_height * pixmap.width() / pixmap.height()),
        )
        if anchor_rect.isValid():
            center_x = anchor_rect.center().x()
            bottom = anchor_rect.bottom()
            self.setGeometry(
                center_x - width // 2,
                bottom - self._pet_height + 1,
                width,
                self._pet_height,
            )
        else:
            self.resize(width, self._pet_height)
        self.update()

    def _resize_to_pet_height(self, height, preserve_anchor=True):
        self._stop_animation()
        height = int(clamp(height, MIN_PET_HEIGHT, MAX_PET_HEIGHT))
        pixmap = self._current_pixmap()
        width = max(1, round(height * pixmap.width() / pixmap.height()))
        old_rect = self.geometry()
        self._pet_height = height
        if preserve_anchor and old_rect.isValid():
            center_x = old_rect.center().x()
            bottom = old_rect.bottom()
            self.setGeometry(center_x - width // 2, bottom - height + 1, width, height)
            self._keep_inside()
        else:
            self.resize(width, height)
        self.update()

    def set_pet_height(self, height):
        if self._active_pose is not None or self._pose_timer.isActive():
            self._typing_timer.stop()
            self._typing_deadline = 0.0
            self._stop_pose_sequence()
        self._resize_to_pet_height(height)
        self.settings.setValue("pet_height", self._pet_height)

    def _alpha_hit(self, point):
        if not self.rect().contains(point):
            return False
        image = self._current_image()
        source_x = int(point.x() * image.width() / max(1, self.width()))
        source_y = int(point.y() * image.height() / max(1, self.height()))
        source_x = clamp(source_x, 0, image.width() - 1)
        source_y = clamp(source_y, 0, image.height() - 1)
        return image.pixelColor(source_x, source_y).alpha() > 24

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(self.rect(), self._current_pixmap())

    def _draw_mouse_mimic(self, painter):
        painter.save()
        mouse_width = float(clamp(self.width() * 0.29, 34, 76))
        mouse_height = mouse_width * 1.24
        x = (self.width() - mouse_width) / 2.0
        y = self.height() - mouse_height - max(3.0, self.height() * 0.012)
        body = QRectF(x, y, mouse_width, mouse_height)
        flash = math.sin(math.pi * self._overlay_progress)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(75, 54, 42, 65))
        painter.drawEllipse(
            QRectF(
                body.left() - 4,
                body.bottom() - mouse_height * 0.12,
                body.width() + 8,
                mouse_height * 0.22,
            )
        )

        painter.setPen(QPen(QColor(88, 67, 54, 245), max(1.4, mouse_width * 0.035)))
        painter.setBrush(QColor(220, 234, 246, 250))
        painter.drawRoundedRect(body, mouse_width * 0.44, mouse_width * 0.44)

        split_y = body.top() + body.height() * 0.38
        center_x = body.center().x()
        painter.drawLine(
            QPoint(int(body.left() + 2), int(split_y)),
            QPoint(int(body.right() - 2), int(split_y)),
        )
        painter.drawLine(
            QPoint(int(center_x), int(body.top() + 2)),
            QPoint(int(center_x), int(split_y)),
        )

        button = self._overlay_kind.split("_", 1)[1]
        if button == "left":
            highlight = QRectF(
                body.left() + 3,
                body.top() + 3,
                body.width() / 2.0 - 4,
                body.height() * 0.34,
            )
        elif button == "right":
            highlight = QRectF(
                body.center().x() + 1,
                body.top() + 3,
                body.width() / 2.0 - 4,
                body.height() * 0.34,
            )
        else:
            highlight = QRectF(
                body.center().x() - mouse_width * 0.08,
                body.top() + body.height() * 0.17,
                mouse_width * 0.16,
                mouse_height * 0.16,
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(245, 164, 86, int(100 + flash * 150)))
        painter.drawRoundedRect(highlight, 5, 5)

        tip_source = self._paw_source_rects["right_tip"]
        scale_x = self.width() / self.pet_pixmap.width()
        scale_y = self.height() / self.pet_pixmap.height()
        tip_width = tip_source.width() * scale_x
        natural_center_x = (
            tip_source.x() * scale_x + tip_width / 2.0
        )
        target_center_x = body.center().x() + {
            "left": -body.width() * 0.16,
            "right": body.width() * 0.16,
            "middle": 0.0,
        }[button]
        natural_top = tip_source.y() * scale_y
        target_top = (
            body.top()
            + body.height() * 0.14
            + body.height() * 0.13 * flash
        )
        self._draw_paw_sprite(
            painter,
            "right_tip",
            offset_x=target_center_x - natural_center_x,
            offset_y=target_top - natural_top,
        )

        dot_radius = max(1.8, mouse_width * 0.045)
        painter.setBrush(QColor(255, 190, 88, int(70 + flash * 185)))
        for index in range(3):
            dot_x = center_x + (index - 1) * mouse_width * 0.25
            dot_y = body.top() - 5 - flash * (8 + index % 2 * 4)
            painter.drawEllipse(
                QRectF(
                    dot_x - dot_radius,
                    dot_y - dot_radius,
                    dot_radius * 2,
                    dot_radius * 2,
                )
            )
        painter.restore()

    def _draw_keyboard_mimic(self, painter):
        painter.save()
        keyboard_width = float(clamp(self.width() * 0.82, 74, 210))
        keyboard_height = float(clamp(self.height() * 0.16, 35, 82))
        x = (self.width() - keyboard_width) / 2.0
        bounce = math.sin(self._typing_phase * math.pi / 2.0) * 2.0
        y = self.height() - keyboard_height - 4 + bounce
        keyboard = QRectF(x, y, keyboard_width, keyboard_height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(64, 45, 35, 65))
        painter.drawRoundedRect(
            keyboard.adjusted(-4, keyboard_height * 0.72, 4, 7),
            7,
            7,
        )

        painter.setPen(QPen(QColor(83, 64, 51, 245), max(1.2, keyboard_height * 0.035)))
        painter.setBrush(QColor(245, 232, 210, 248))
        painter.drawRoundedRect(keyboard, 8, 8)

        rows = 3
        columns = 7
        gap = max(1.5, keyboard_width * 0.012)
        inner = keyboard.adjusted(gap * 2.2, gap * 2.2, -gap * 2.2, -gap * 2.2)
        key_width = (inner.width() - gap * (columns - 1)) / columns
        key_height = (inner.height() - gap * (rows - 1)) / rows
        active_key = self._typing_phase % (rows * columns)

        for row in range(rows):
            for column in range(columns):
                index = row * columns + column
                key = QRectF(
                    inner.left() + column * (key_width + gap),
                    inner.top() + row * (key_height + gap),
                    key_width,
                    key_height,
                )
                if index == active_key:
                    painter.setBrush(QColor(246, 165, 83, 255))
                    painter.setPen(QPen(QColor(126, 76, 42, 245), 1))
                else:
                    painter.setBrush(QColor(255, 251, 242, 245))
                    painter.setPen(QPen(QColor(157, 133, 111, 220), 0.8))
                painter.drawRoundedRect(key, 2.2, 2.2)

        phase = self._typing_phase * math.pi / 2.0
        left_press = (math.sin(phase) + 1.0) / 2.0
        right_press = (math.sin(phase + math.pi) + 1.0) / 2.0
        paw_travel = max(6.0, self.height() * 0.026)
        self._draw_paw_sprite(
            painter,
            "left",
            offset_x=max(2.0, self.width() * 0.025),
            offset_y=left_press * paw_travel,
        )
        self._draw_paw_sprite(
            painter,
            "right",
            offset_x=-max(2.0, self.width() * 0.022),
            offset_y=right_press * paw_travel,
        )
        painter.restore()

    def _draw_paw_sprite(self, painter, paw_name, offset_x=0.0, offset_y=0.0):
        source_rect = self._paw_source_rects[paw_name]
        paw_pixmap = self._paw_pixmaps[paw_name]
        scale_x = self.width() / self.pet_pixmap.width()
        scale_y = self.height() / self.pet_pixmap.height()
        destination = QRectF(
            source_rect.x() * scale_x + offset_x,
            source_rect.y() * scale_y + offset_y,
            source_rect.width() * scale_x,
            source_rect.height() * scale_y,
        )
        painter.drawPixmap(destination, paw_pixmap, QRectF(paw_pixmap.rect()))

    def _start_pose_sequence(self, sequence, mode):
        self._stop_animation()
        self._pose_timer.stop()
        self._pose_sequence = list(sequence)
        self._pose_sequence_index = 0
        self._pose_mode = mode
        self._advance_pose_sequence()

    def _advance_pose_sequence(self):
        if self._pose_sequence_index >= len(self._pose_sequence):
            self._stop_pose_sequence()
            return
        pose_name, duration = self._pose_sequence[self._pose_sequence_index]
        self._pose_sequence_index += 1
        self._set_active_pose(pose_name, self._pose_mode)
        self._pose_timer.start(int(duration))

    def _stop_pose_sequence(self):
        self._pose_timer.stop()
        self._pose_sequence = []
        self._pose_sequence_index = 0
        self._pose_mode = None
        if self._active_pose is not None:
            self._set_active_pose(None)

    def _start_idle_pose_action(self, action_name):
        sequences = {
            "yawn": [
                ("idle_yawn", 1450),
                (None, 180),
            ],
            "stretch_pose": [
                ("idle_stretch", 1550),
                (None, 200),
            ],
            "look": [
                ("idle_look_left", 620),
                (None, 150),
                ("idle_look_right", 620),
                (None, 180),
            ],
            "wave": [
                ("idle_wave", 520),
                (None, 180),
                ("idle_wave", 520),
                (None, 180),
            ],
        }
        self._start_pose_sequence(sequences[action_name], "idle")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._alpha_hit(event.position().toPoint()):
            self._stop_animation()
            self._typing_timer.stop()
            self._typing_deadline = 0.0
            self._stop_pose_sequence()
            self.bubble.hide()
            self._reset_idle_timer()
            self._press_global = event.globalPosition().toPoint()
            self._drag_origin = self.frameGeometry().topLeft()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_global is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._press_global
            if (
                not self._dragging
                and delta.manhattanLength() >= QApplication.startDragDistance()
            ):
                self._dragging = True
                # The global watcher can see this same press before Qt decides
                # it is a drag. Clear any reaction using the old position as
                # its anchor before moving the pet.
                self._typing_timer.stop()
                self._typing_deadline = 0.0
                self._stop_animation()
                self._stop_pose_sequence()
                self.bubble.hide()
            if self._dragging:
                self.move(self._drag_origin + delta)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press_global is not None:
            was_dragging = self._dragging
            self._press_global = None
            self._drag_origin = None
            self._dragging = False
            if was_dragging:
                self._keep_inside()
                self.settings.setValue("position", self.pos())
            else:
                self.trigger_interaction()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self._alpha_hit(event.position().toPoint()):
            event.ignore()
            return
        steps = event.angleDelta().y() / 120.0
        if steps:
            factor = math.pow(1.09, steps)
            self.set_pet_height(round(self._pet_height * factor))
            event.accept()

    def contextMenuEvent(self, event):
        if not self._alpha_hit(event.pos()):
            event.ignore()
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background: #fffaf0;
                color: #45352b;
                border: 1px solid #bda892;
                border-radius: 8px;
                padding: 5px;
                font: 10pt "Microsoft YaHei UI";
            }
            QMenu::item { padding: 7px 24px 7px 12px; border-radius: 5px; }
            QMenu::item:selected { background: #f1dac1; }
            QMenu::separator { height: 1px; background: #ddcdbd; margin: 4px 8px; }
            """
        )

        size_menu = menu.addMenu("调整大小")
        size_options = [
            ("迷你（约 65×110）", 110),
            ("小巧（约 80×130）", 130),
            ("推荐（约 90×150）", 150),
            ("标准（约 110×180）", 180),
            ("大号（约 135×220）", 220),
        ]
        for label, height in size_options:
            action = QAction(label, size_menu)
            action.setCheckable(True)
            action.setChecked(abs(self._pet_height - height) < 8)
            action.triggered.connect(
                lambda checked=False, selected_height=height: self.set_pet_height(selected_height)
            )
            size_menu.addAction(action)

        idle_menu = menu.addMenu("空闲互动设置")

        idle_enabled_action = QAction("启用空闲互动", idle_menu)
        idle_enabled_action.setCheckable(True)
        idle_enabled_action.setChecked(self._idle_enabled)
        idle_enabled_action.toggled.connect(self.set_idle_enabled)
        idle_menu.addAction(idle_enabled_action)

        wait_menu = idle_menu.addMenu("等待时间")
        wait_options = [
            ("5 秒（快速看看）", 5),
            ("10 秒", 10),
            ("20 秒", 20),
            ("30 秒", 30),
            ("1 分钟", 60),
            ("2 分钟", 120),
            ("5 分钟", 300),
        ]
        for label, seconds in wait_options:
            action = QAction(label, wait_menu)
            action.setCheckable(True)
            action.setChecked(self._idle_interval_seconds == seconds)
            action.triggered.connect(
                lambda checked=False, selected_seconds=seconds: self.set_idle_interval(
                    selected_seconds
                )
            )
            wait_menu.addAction(action)

        action_selection_menu = idle_menu.addMenu("选择启用的动作")
        for action_name, label in self.IDLE_ACTIONS.items():
            action = QAction(label, action_selection_menu)
            action.setCheckable(True)
            action.setChecked(action_name in self._enabled_idle_actions)
            action.toggled.connect(
                lambda enabled, selected_action=action_name: self.set_idle_action_enabled(
                    selected_action, enabled
                )
            )
            action_selection_menu.addAction(action)

        preview_menu = idle_menu.addMenu("立即预览动作")
        for action_name, label in self.IDLE_ACTIONS.items():
            action = QAction(label, preview_menu)
            action.triggered.connect(
                lambda checked=False, selected_action=action_name: self.preview_idle_action(
                    selected_action
                )
            )
            preview_menu.addAction(action)
        preview_menu.addSeparator()
        random_preview_action = QAction("随机预览一个", preview_menu)
        random_preview_action.triggered.connect(self.preview_random_idle_action)
        preview_menu.addAction(random_preview_action)

        dialogue_action = QAction("编辑对话内容…", menu)
        dialogue_action.triggered.connect(self.edit_dialogues)
        menu.addAction(dialogue_action)

        statistics_action = QAction("键鼠统计…", menu)
        statistics_action.triggered.connect(self.show_input_statistics)
        menu.addAction(statistics_action)

        input_echo_action = QAction("跟随鼠标和键盘", menu)
        input_echo_action.setCheckable(True)
        input_echo_action.setChecked(self._input_echo_enabled)
        input_echo_action.toggled.connect(self.set_input_echo)
        menu.addAction(input_echo_action)

        autostart_action = QAction("开机自动启动", menu)
        autostart_action.setCheckable(True)
        autostart_action.setChecked(is_autostart_enabled())
        autostart_action.toggled.connect(self.set_autostart)
        menu.addAction(autostart_action)

        topmost_action = QAction("始终置顶", menu)
        topmost_action.setCheckable(True)
        topmost_action.setChecked(self._topmost)
        topmost_action.toggled.connect(self.set_topmost)
        menu.addAction(topmost_action)

        menu.addSeparator()
        exit_action = QAction("退出程序", menu)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)
        menu.exec(event.globalPos())

    def set_topmost(self, enabled):
        position = self.pos()
        self._topmost = bool(enabled)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._topmost)
        self.move(position)
        self.show()
        self.raise_()
        self.settings.setValue("topmost", self._topmost)

    def set_autostart(self, enabled):
        try:
            set_autostart_enabled(enabled)
        except OSError:
            self._show_bubble("开机自启设置失败，请检查系统权限。")
            return
        if enabled:
            self._show_bubble("开机后，豆豆会自动来上班！")
        else:
            self._show_bubble("已关闭开机自动启动。")

    def _load_dialogues(self):
        defaults = {key: list(values) for key, values in self.DIALOGUES.items()}
        raw_value = self.settings.value("dialogues_json", "", type=str)
        if not raw_value:
            return defaults
        try:
            saved = json.loads(raw_value)
        except (TypeError, ValueError):
            return defaults
        if not isinstance(saved, dict):
            return defaults

        configured = {}
        for key, default_values in defaults.items():
            values = saved.get(key, default_values)
            if not isinstance(values, list):
                values = default_values
            cleaned = []
            for value in values:
                value = str(value).strip()
                if value and value not in cleaned:
                    cleaned.append(value)
            configured[key] = cleaned
        return configured

    def _save_dialogues(self):
        raw_value = json.dumps(
            self._dialogues,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self.settings.setValue(
            "dialogues_json",
            raw_value,
        )
        self.settings.sync()

    def _apply_configured_dialogues(self, dialogues):
        configured = {}
        for key, default_values in self.DIALOGUES.items():
            values = dialogues.get(key, default_values)
            cleaned = []
            for value in values:
                value = str(value).strip()
                if value and value not in cleaned:
                    cleaned.append(value)
            configured[key] = cleaned
        self._dialogues = configured
        self._save_dialogues()

    def edit_dialogues(self):
        self._input_reactions_suspended = True
        self._typing_timer.stop()
        self._typing_deadline = 0.0
        self._stop_pose_sequence()
        dialog = DialogueEditorDialog(self._dialogues, self.DIALOGUES, self)
        initial_dialogues = {
            key: list(values) for key, values in self._dialogues.items()
        }
        dialog.dialogues_changed.connect(self._apply_configured_dialogues)
        try:
            dialog.exec()
            configured = dialog.configured_dialogues()
            if configured != self._dialogues:
                self._apply_configured_dialogues(configured)
            if self._dialogues != initial_dialogues:
                self._show_bubble("对话已经保存，豆豆记住啦！")
        finally:
            dialog.deleteLater()
            self._input_reactions_suspended = False
            self._refresh_input_watcher()

    def show_input_statistics(self):
        if self._statistics_dialog is None:
            self._statistics_dialog = InputStatisticsDialog(
                self.statistics, self
            )
        self._statistics_dialog.show()
        self._statistics_dialog.raise_()
        self._statistics_dialog.activateWindow()

    def _refresh_input_watcher(self):
        self.input_watcher.set_enabled(self._enable_system_input)

    def set_idle_enabled(self, enabled):
        self._idle_enabled = bool(enabled)
        self._refresh_input_watcher()
        if self._idle_enabled:
            self._reset_idle_timer()
            self._show_bubble(
                "空闲互动已开启，等待 {} 秒～".format(
                    self._idle_interval_seconds
                )
            )
        else:
            self._idle_timer.stop()
            self._show_bubble("空闲互动已暂停。")
        self.settings.setValue("idle_enabled", self._idle_enabled)

    def set_idle_interval(self, seconds):
        self._idle_interval_seconds = int(clamp(seconds, 5, 300))
        self.settings.setValue(
            "idle_interval_seconds", self._idle_interval_seconds
        )
        self._reset_idle_timer()
        self._show_bubble(
            "空闲 {} 秒后表演动作！".format(self._idle_interval_seconds)
        )

    def set_idle_action_enabled(self, action_name, enabled):
        if action_name not in self.IDLE_ACTIONS:
            return
        if enabled:
            self._enabled_idle_actions.add(action_name)
        else:
            self._enabled_idle_actions.discard(action_name)
        self.settings.setValue(
            "idle_actions", ",".join(sorted(self._enabled_idle_actions))
        )
        self._reset_idle_timer()

    def preview_idle_action(self, action_name):
        if action_name not in self.IDLE_ACTIONS:
            return
        self._stop_animation()
        self._stop_pose_sequence()
        self._typing_timer.stop()
        self._typing_deadline = 0.0
        self._start_idle_pose_action(action_name)
        self._show_bubble("动作预览：{}".format(self.IDLE_ACTIONS[action_name]))
        self._reset_idle_timer()

    def preview_random_idle_action(self):
        self.preview_idle_action(random.choice(tuple(self.IDLE_ACTIONS.keys())))

    def set_input_echo(self, enabled):
        self._input_echo_enabled = bool(enabled)
        self._refresh_input_watcher()
        if not self._input_echo_enabled:
            self._typing_timer.stop()
            self._typing_deadline = 0.0
            if self._pose_mode in ("typing", "mouse"):
                self._stop_pose_sequence()
            self.update()
        else:
            self._show_bubble("收到！我来模仿你的操作～")
        self.settings.setValue("input_echo_enabled", self._input_echo_enabled)

    def _show_bubble(self, message):
        if not message:
            return
        self.bubble.show_message(
            message,
            self.frameGeometry(),
            self._screen_geometry(),
            self._topmost,
        )

    def _maybe_show_input_bubble(self, kind, minimum_interval=5.5):
        message = self._random_dialogue(kind)
        if message is None:
            return
        now = time.monotonic()
        if now - self._last_input_bubble < minimum_interval:
            return
        self._last_input_bubble = now
        self._show_bubble(message)

    def _random_dialogue(self, kind):
        values = self._dialogues.get(kind, [])
        if not values:
            return None
        return random.choice(values)

    def react_to_mouse_click(self, button):
        if (
            not self._input_echo_enabled
            or self._input_reactions_suspended
            or self._press_global is not None
            or self._dragging
        ):
            return
        del button
        self._reset_idle_timer()
        self._typing_timer.stop()
        self._typing_deadline = 0.0
        self._start_pose_sequence(
            [
                ("mouse_ready", 110),
                ("mouse_click", 250),
                ("mouse_ready", 130),
            ],
            "mouse",
        )
        self._maybe_show_input_bubble("mouse", 5.0)

    def react_to_keyboard_press(self):
        if (
            not self._input_echo_enabled
            or self._input_reactions_suspended
            or self._dragging
        ):
            return
        now = time.monotonic()
        new_burst = now >= self._typing_deadline
        self._typing_deadline = now + 0.86
        self._typing_phase = (self._typing_phase + 1) % 10000
        self._reset_idle_timer()

        if self._pose_mode != "typing":
            self._stop_pose_sequence()
            self._stop_animation()
            self._pose_mode = "typing"
        pose_name = (
            "typing_left" if self._typing_phase % 2 else "typing_right"
        )
        self._set_active_pose(pose_name, "typing")
        if not self._typing_timer.isActive():
            self._typing_timer.start()
        if new_burst:
            self._maybe_show_input_bubble("keyboard", 5.5)

    def _tick_typing(self):
        if time.monotonic() >= self._typing_deadline:
            self._typing_timer.stop()
            if self._pose_mode == "typing":
                self._stop_pose_sequence()
            return
        self._typing_phase = (self._typing_phase + 1) % 10000
        pose_name = (
            "typing_left" if self._typing_phase % 2 else "typing_right"
        )
        self._set_active_pose(pose_name, "typing")

    def _start_overlay(self, kind, duration):
        self._stop_overlay_animation()
        self._overlay_kind = kind
        self._overlay_progress = 0.0
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(duration)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(self._set_overlay_progress)
        animation.finished.connect(
            lambda finished_kind=kind: self._finish_overlay(finished_kind)
        )
        self._overlay_animation = animation
        animation.start()

    def _set_overlay_progress(self, progress):
        self._overlay_progress = float(progress)
        self.update()

    def _finish_overlay(self, finished_kind):
        self._overlay_animation = None
        if self._overlay_kind != finished_kind:
            return
        if time.monotonic() < self._typing_deadline:
            self._overlay_kind = "keyboard"
            self._overlay_progress = 1.0
        else:
            self._overlay_kind = None
            self._overlay_progress = 0.0
        self.update()

    def _stop_overlay_animation(self):
        if self._overlay_animation is not None:
            animation = self._overlay_animation
            self._overlay_animation = None
            animation.stop()
            animation.deleteLater()

    def _reset_idle_timer(self):
        if (
            self._enable_system_input
            and self._idle_enabled
            and self._enabled_idle_actions
        ):
            self._idle_timer.start(self._idle_interval_seconds * 1000)
        else:
            self._idle_timer.stop()

    def _idle_reaction(self):
        if not self._idle_enabled or not self._enabled_idle_actions:
            self._idle_timer.stop()
            return
        if (
            self._dragging
            or self._animation is not None
            or self._active_pose is not None
            or self._pose_timer.isActive()
        ):
            self._reset_idle_timer()
            return
        kind = random.choice(tuple(self._enabled_idle_actions))
        self._start_idle_pose_action(kind)
        if random.random() < 0.42:
            self._show_bubble(self._random_dialogue("idle"))
        self._reset_idle_timer()

    def trigger_interaction(self):
        if self._active_pose is not None or self._pose_timer.isActive():
            self._typing_timer.stop()
            self._typing_deadline = 0.0
            self._stop_pose_sequence()
        if self._animation is not None:
            return
        self._reset_idle_timer()
        kinds = ("jump", "squash", "shake")
        kind = kinds[self._interaction_index % len(kinds)]
        self._interaction_index += 1
        self._show_bubble(self._random_dialogue(kind))
        self._start_animation(kind)

    def _start_animation(self, kind):
        if self._animation is not None:
            return False
        self._animation_base_rect = QRect(self.geometry())
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.Linear)
        animation.setDuration(
            {
                "jump": 620,
                "squash": 720,
                "shake": 650,
                "mouse_click": 330,
                "type": 240,
                "nod": 620,
                "stretch": 880,
                "look": 1100,
                "breathe": 1800,
            }[kind]
        )
        animation.valueChanged.connect(
            lambda value, animation_kind=kind: self._apply_animation(
                animation_kind, float(value)
            )
        )
        animation.finished.connect(self._finish_animation)
        self._animation = animation
        animation.start()
        return True

    def _apply_animation(self, kind, progress):
        if self._animation_base_rect is None:
            return
        base = self._animation_base_rect
        if kind == "jump":
            height = round(base.height() * 0.24 * math.sin(math.pi * progress))
            self.move(base.x(), base.y() - height)
        elif kind == "shake":
            damping = 1.0 - 0.35 * progress
            offset = round(
                base.width()
                * 0.075
                * math.sin(progress * math.pi * 8.0)
                * damping
            )
            self.move(base.x() + offset, base.y())
        elif kind == "mouse_click":
            amount = math.sin(math.pi * progress)
            self._set_scaled_geometry(
                base,
                1.0 + amount * 0.035,
                1.0 - amount * 0.065,
            )
        elif kind == "type":
            amount = math.sin(progress * math.pi)
            self._set_scaled_geometry(
                base,
                1.0 + amount * 0.035,
                1.0 - amount * 0.075,
            )
            offset_x = round(
                base.width() * 0.016 * math.sin(progress * math.pi * 4.0)
            )
            self.move(self.x() + offset_x, self.y())
        elif kind == "nod":
            amount = math.sin(math.pi * progress)
            self._set_scaled_geometry(
                base,
                1.0 + amount * 0.035,
                1.0 - amount * 0.09,
            )
        elif kind == "stretch":
            amount = math.sin(math.pi * progress)
            self._set_scaled_geometry(
                base,
                1.0 + amount * 0.11,
                1.0 - amount * 0.075,
            )
        elif kind == "look":
            damping = 0.72 + 0.28 * (1.0 - progress)
            offset_x = round(
                base.width()
                * 0.065
                * math.sin(progress * math.pi * 3.0)
                * damping
            )
            self.move(base.x() + offset_x, base.y())
        elif kind == "breathe":
            amount = (1.0 - math.cos(progress * math.pi * 4.0)) / 2.0
            self._set_scaled_geometry(
                base,
                1.0 + amount * 0.022,
                1.0 - amount * 0.018,
            )
        elif kind == "squash":
            if progress < 0.42:
                amount = math.sin((progress / 0.42) * math.pi / 2.0)
                scale_x = 1.0 + 0.22 * amount
                scale_y = 1.0 - 0.37 * amount
            elif progress < 0.72:
                amount = smoothstep((progress - 0.42) / 0.30)
                scale_x = 1.22 + (0.95 - 1.22) * amount
                scale_y = 0.63 + (1.08 - 0.63) * amount
            else:
                amount = smoothstep((progress - 0.72) / 0.28)
                scale_x = 0.95 + (1.0 - 0.95) * amount
                scale_y = 1.08 + (1.0 - 1.08) * amount

            self._set_scaled_geometry(base, scale_x, scale_y)

    def _set_scaled_geometry(self, base, scale_x, scale_y):
        width = max(1, round(base.width() * scale_x))
        height = max(1, round(base.height() * scale_y))
        center_x = base.center().x()
        bottom = base.bottom()
        self.setGeometry(center_x - width // 2, bottom - height + 1, width, height)

    def _finish_animation(self):
        if self._animation_base_rect is not None:
            self.setGeometry(self._animation_base_rect)
        self._animation = None
        self._animation_base_rect = None

    def _stop_animation(self):
        if self._animation is not None:
            self._animation.stop()
            self._finish_animation()

    def save_settings(self):
        self._stop_animation()
        self._stop_pose_sequence()
        self.settings.setValue("position", self.pos())
        self.settings.setValue("pet_height", self._pet_height)
        self.settings.setValue("topmost", self._topmost)
        self.settings.setValue("input_echo_enabled", self._input_echo_enabled)
        self.settings.setValue("idle_enabled", self._idle_enabled)
        self.settings.setValue(
            "idle_interval_seconds", self._idle_interval_seconds
        )
        self.settings.setValue(
            "idle_actions", ",".join(sorted(self._enabled_idle_actions))
        )
        self.settings.sync()
        self.statistics.flush()

    def shutdown(self):
        self.input_watcher.set_enabled(False)
        self._idle_timer.stop()
        self._typing_timer.stop()
        self._pose_timer.stop()
        self._stop_overlay_animation()
        self.save_settings()
        self.statistics.close_store()

    def closeEvent(self, event):
        self.shutdown()
        if self._statistics_dialog is not None:
            self._statistics_dialog.close()
        self.bubble.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Codex")
    app.setQuitOnLastWindowClosed(True)
    smoke_test = "--smoke-test" in sys.argv

    icon_path = resource_path("assets/pet.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    instance_guard = None
    if not smoke_test:
        instance_guard = create_single_instance_guard(parent=app)
        if instance_guard is None:
            QMessageBox.information(
                None,
                APP_NAME,
                "豆豆桌宠已经在运行了，请不要重复启动。",
            )
            return 0

    temporary_settings_dir = QTemporaryDir() if smoke_test else None
    settings = (
        file_settings(Path(temporary_settings_dir.path()) / CONFIG_FILENAME)
        if temporary_settings_dir is not None
        else file_settings()
    )
    pet = DesktopPet(
        enable_system_input=not smoke_test,
        settings=settings,
    )
    app.aboutToQuit.connect(pet.shutdown)
    pet.show()
    pet.raise_()

    if smoke_test:
        QTimer.singleShot(120, lambda: pet.react_to_mouse_click("left"))
        QTimer.singleShot(550, pet.react_to_keyboard_press)
        QTimer.singleShot(680, pet.react_to_keyboard_press)
        QTimer.singleShot(950, pet.trigger_interaction)
        QTimer.singleShot(1700, pet.trigger_interaction)
        QTimer.singleShot(2550, pet.trigger_interaction)
        QTimer.singleShot(3300, lambda: pet.preview_idle_action("yawn"))
        QTimer.singleShot(5000, lambda: pet.preview_idle_action("stretch_pose"))
        QTimer.singleShot(6900, lambda: pet.preview_idle_action("look"))
        QTimer.singleShot(8600, lambda: pet.preview_idle_action("wave"))
        QTimer.singleShot(10100, app.quit)

    exit_code = app.exec()
    del instance_guard
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
