import ctypes
import math
import os
import random
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSettings,
    Signal,
    QTimer,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QAction,
    QColor,
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
from PySide6.QtWidgets import QApplication, QMenu, QWidget


APP_NAME = "小白桌宠"
APP_VERSION = "1.1.0"
DEFAULT_PET_HEIGHT = 340
MIN_PET_HEIGHT = 150
MAX_PET_HEIGHT = 680


def resource_path(relative_path):
    """Return a resource path that works both in source and PyInstaller builds."""
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def smoothstep(value):
    value = clamp(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


class GlobalInputWatcher(QObject):
    """Observe input transitions without recording text or injecting input."""

    mouse_clicked = Signal(str)
    key_pressed = Signal()

    KEYBOARD_KEYS = tuple(
        list(range(0x30, 0x5B))
        + list(range(0x70, 0x7C))
        + [
            0x08,  # Backspace
            0x09,  # Tab
            0x0D,  # Enter
            0x1B,  # Escape
            0x20,  # Space
            0x21,  # Page Up
            0x22,  # Page Down
            0x23,  # End
            0x24,  # Home
            0x25,  # Left
            0x26,  # Up
            0x27,  # Right
            0x28,  # Down
            0x2D,  # Insert
            0x2E,  # Delete
            0xBA,
            0xBB,
            0xBC,
            0xBD,
            0xBE,
            0xBF,
            0xC0,
            0xDB,
            0xDC,
            0xDD,
            0xDE,
        ]
    )
    MOUSE_BUTTONS = {"left": 0x01, "right": 0x02, "middle": 0x04}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._supported = sys.platform == "win32"
        self._enabled = False
        self._user32 = ctypes.windll.user32 if self._supported else None
        self._key_states = {}
        self._mouse_states = {}
        self._timer = QTimer(self)
        self._timer.setInterval(28)
        self._timer.timeout.connect(self._poll)

    def _is_down(self, virtual_key):
        return bool(self._user32.GetAsyncKeyState(virtual_key) & 0x8000)

    def _snapshot(self):
        if not self._supported:
            return
        self._key_states = {
            virtual_key: self._is_down(virtual_key)
            for virtual_key in self.KEYBOARD_KEYS
        }
        self._mouse_states = {
            name: self._is_down(virtual_key)
            for name, virtual_key in self.MOUSE_BUTTONS.items()
        }

    def set_enabled(self, enabled):
        enabled = bool(enabled and self._supported)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled:
            self._snapshot()
            self._timer.start()
        else:
            self._timer.stop()
            self._key_states.clear()
            self._mouse_states.clear()

    def _poll(self):
        if not self._enabled:
            return

        for name, virtual_key in self.MOUSE_BUTTONS.items():
            is_down = self._is_down(virtual_key)
            if is_down and not self._mouse_states.get(name, False):
                self.mouse_clicked.emit(name)
            self._mouse_states[name] = is_down

        any_new_key = False
        for virtual_key in self.KEYBOARD_KEYS:
            is_down = self._is_down(virtual_key)
            if is_down and not self._key_states.get(virtual_key, False):
                any_new_key = True
            self._key_states[virtual_key] = is_down
        if any_new_key:
            self.key_pressed.emit()


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


class DesktopPet(QWidget):
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
            "你点一下，我也点一下！",
            "咔哒！这个我也会。",
            "鼠标交给我，效率汪汪涨！",
            "点到哪里，快乐跟到哪里。",
        ],
        "keyboard": [
            "你敲字，我负责加速！",
            "噼里啪啦，灵感来啦！",
            "键盘搭子已上线。",
            "这段代码一定很厉害！",
            "继续敲，我在旁边伴奏～",
        ],
        "idle": [
            "忙完记得摸摸我。",
            "我在认真帮你看桌面。",
            "休息十秒，也算充电。",
            "今天也要对自己好一点。",
        ],
    }

    def __init__(self, enable_system_input=True):
        super().__init__(None)
        self.settings = QSettings("Codex", "XiaobaiDesktopPet")
        self._topmost = self.settings.value("topmost", True, type=bool)
        self._input_echo_enabled = self.settings.value(
            "input_echo_enabled", True, type=bool
        )
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

        self.pet_pixmap = QPixmap(str(resource_path("assets/pet_cropped.png")))
        if self.pet_pixmap.isNull():
            raise RuntimeError("无法加载桌宠图片资源 assets/pet_cropped.png")
        self.pet_image = self.pet_pixmap.toImage()

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
        self.input_watcher = GlobalInputWatcher(self)
        self.input_watcher.mouse_clicked.connect(self.react_to_mouse_click)
        self.input_watcher.key_pressed.connect(self.react_to_keyboard_press)

        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(72)
        self._typing_timer.timeout.connect(self._tick_typing)

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._idle_reaction)

        self._resize_to_pet_height(self._pet_height, preserve_anchor=False)
        self._restore_or_place_window()
        self.input_watcher.set_enabled(
            self._input_echo_enabled and self._enable_system_input
        )
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

    def _resize_to_pet_height(self, height, preserve_anchor=True):
        self._stop_animation()
        height = int(clamp(height, MIN_PET_HEIGHT, MAX_PET_HEIGHT))
        width = max(1, round(height * self.pet_pixmap.width() / self.pet_pixmap.height()))
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
        self._resize_to_pet_height(height)
        self.settings.setValue("pet_height", self._pet_height)

    def _alpha_hit(self, point):
        if not self.rect().contains(point):
            return False
        source_x = int(point.x() * self.pet_image.width() / max(1, self.width()))
        source_y = int(point.y() * self.pet_image.height() / max(1, self.height()))
        source_x = clamp(source_x, 0, self.pet_image.width() - 1)
        source_y = clamp(source_y, 0, self.pet_image.height() - 1)
        return self.pet_image.pixelColor(source_x, source_y).alpha() > 24

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(self.rect(), self.pet_pixmap)
        if self._overlay_kind and self._overlay_kind.startswith("mouse_"):
            self._draw_mouse_mimic(painter)
        elif self._overlay_kind == "keyboard":
            self._draw_keyboard_mimic(painter)

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
        painter.setBrush(QColor(250, 244, 232, 245))
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
        painter.restore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._alpha_hit(event.position().toPoint()):
            self._stop_animation()
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
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
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
            ("迷你（220）", 220),
            ("小巧（280）", 280),
            ("标准（340）", 340),
            ("大号（430）", 430),
            ("超大（540）", 540),
        ]
        for label, height in size_options:
            action = QAction(label, size_menu)
            action.setCheckable(True)
            action.setChecked(abs(self._pet_height - height) < 8)
            action.triggered.connect(
                lambda checked=False, selected_height=height: self.set_pet_height(selected_height)
            )
            size_menu.addAction(action)

        input_echo_action = QAction("跟随鼠标和键盘", menu)
        input_echo_action.setCheckable(True)
        input_echo_action.setChecked(self._input_echo_enabled)
        input_echo_action.toggled.connect(self.set_input_echo)
        menu.addAction(input_echo_action)

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

    def set_input_echo(self, enabled):
        self._input_echo_enabled = bool(enabled)
        self.input_watcher.set_enabled(
            self._input_echo_enabled and self._enable_system_input
        )
        if not self._input_echo_enabled:
            self._typing_timer.stop()
            self._typing_deadline = 0.0
            self._stop_overlay_animation()
            self._overlay_kind = None
            self.update()
        else:
            self._show_bubble("收到！我来模仿你的操作～")
        self.settings.setValue("input_echo_enabled", self._input_echo_enabled)

    def _show_bubble(self, message):
        self.bubble.show_message(
            message,
            self.frameGeometry(),
            self._screen_geometry(),
            self._topmost,
        )

    def _maybe_show_input_bubble(self, kind, minimum_interval=5.5):
        now = time.monotonic()
        if now - self._last_input_bubble < minimum_interval:
            return
        self._last_input_bubble = now
        self._show_bubble(random.choice(self.DIALOGUES[kind]))

    def react_to_mouse_click(self, button):
        if not self._input_echo_enabled or self._dragging:
            return
        self._reset_idle_timer()
        self._start_overlay("mouse_" + button, 440)
        if self._animation is None:
            self._start_animation("mouse_click")
        self._maybe_show_input_bubble("mouse", 5.0)

    def react_to_keyboard_press(self):
        if not self._input_echo_enabled or self._dragging:
            return
        now = time.monotonic()
        new_burst = now >= self._typing_deadline
        self._typing_deadline = now + 0.78
        self._typing_phase = (self._typing_phase + 1) % 10000
        self._reset_idle_timer()

        if self._overlay_animation is not None:
            self._stop_overlay_animation()
        self._overlay_kind = "keyboard"
        self._overlay_progress = 1.0
        if not self._typing_timer.isActive():
            self._typing_timer.start()
        self.update()

        if self._animation is None and now - self._last_key_bob > 0.24:
            self._last_key_bob = now
            self._start_animation("type")
        if new_burst:
            self._maybe_show_input_bubble("keyboard", 5.5)

    def _tick_typing(self):
        if time.monotonic() >= self._typing_deadline:
            self._typing_timer.stop()
            if not (self._overlay_kind or "").startswith("mouse_"):
                self._overlay_kind = None
                self._overlay_progress = 0.0
                self.update()
            return
        self._typing_phase = (self._typing_phase + 1) % 10000
        self.update()

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
        if self._enable_system_input:
            self._idle_timer.start(random.randint(9000, 16000))

    def _idle_reaction(self):
        if self._dragging or self._animation is not None:
            self._reset_idle_timer()
            return
        kind = random.choice(("nod", "stretch", "shake"))
        if random.random() < 0.42:
            self._show_bubble(random.choice(self.DIALOGUES["idle"]))
        self._start_animation(kind)
        self._reset_idle_timer()

    def trigger_interaction(self):
        if self._animation is not None:
            return
        self._reset_idle_timer()
        kinds = ("jump", "squash", "shake")
        kind = kinds[self._interaction_index % len(kinds)]
        self._interaction_index += 1
        message = random.choice(self.DIALOGUES[kind])
        self._show_bubble(message)
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
            offset_x = round(base.width() * 0.012 * math.sin(progress * math.pi * 4.0))
            offset_y = round(base.height() * 0.018 * math.sin(progress * math.pi))
            self.move(base.x() + offset_x, base.y() + offset_y)
        elif kind == "nod":
            amount = math.sin(math.pi * progress)
            self._set_scaled_geometry(
                base,
                1.0 + amount * 0.018,
                1.0 - amount * 0.045,
            )
        elif kind == "stretch":
            amount = math.sin(math.pi * progress)
            self._set_scaled_geometry(
                base,
                1.0 + amount * 0.11,
                1.0 - amount * 0.075,
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
        self.settings.setValue("position", self.pos())
        self.settings.setValue("pet_height", self._pet_height)
        self.settings.setValue("topmost", self._topmost)
        self.settings.setValue("input_echo_enabled", self._input_echo_enabled)
        self.settings.sync()

    def closeEvent(self, event):
        self.input_watcher.set_enabled(False)
        self._idle_timer.stop()
        self._typing_timer.stop()
        self._stop_overlay_animation()
        self.save_settings()
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

    pet = DesktopPet(enable_system_input=not smoke_test)
    app.aboutToQuit.connect(pet.save_settings)
    pet.show()
    pet.raise_()

    if smoke_test:
        QTimer.singleShot(120, lambda: pet.react_to_mouse_click("left"))
        QTimer.singleShot(580, pet.react_to_keyboard_press)
        QTimer.singleShot(700, pet.react_to_keyboard_press)
        QTimer.singleShot(1080, pet.trigger_interaction)
        QTimer.singleShot(1860, pet.trigger_interaction)
        QTimer.singleShot(2700, pet.trigger_interaction)
        QTimer.singleShot(3500, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
