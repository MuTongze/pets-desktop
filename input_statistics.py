import json
import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, QObject, QRectF, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


STATISTICS_FILENAME = "豆豆桌宠输入统计.json"
STATISTICS_VERSION = 1
IDLE_FLUSH_MILLISECONDS = 8_000
MAX_FLUSH_MILLISECONDS = 60_000
DAILY_RETENTION_DAYS = 365


KEY_LABELS = {
    "esc": "Esc",
    "print_screen": "PrtSc",
    "scroll_lock": "ScrLk",
    "pause": "Pause",
    "grave": "`",
    "minus": "-",
    "equals": "=",
    "backspace": "Backspace",
    "tab": "Tab",
    "bracket_left": "[",
    "bracket_right": "]",
    "backslash": "\\",
    "caps_lock": "Caps Lock",
    "semicolon": ";",
    "quote": "'",
    "enter": "Enter",
    "lshift": "左 Shift",
    "rshift": "右 Shift",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "lctrl": "左 Ctrl",
    "rctrl": "右 Ctrl",
    "lwin": "左 Win",
    "rwin": "右 Win",
    "lalt": "左 Alt",
    "ralt": "右 Alt",
    "space": "Space",
    "menu": "Menu",
    "insert": "Ins",
    "home": "Home",
    "page_up": "PgUp",
    "delete": "Del",
    "end": "End",
    "page_down": "PgDn",
    "left": "←",
    "up": "↑",
    "right": "→",
    "down": "↓",
    "num_lock": "Num",
    "num_divide": "/",
    "num_multiply": "×",
    "num_subtract": "−",
    "num_add": "+",
    "num_enter": "Enter",
    "num_decimal": ".",
    "oem_102": "OEM",
    "volume_mute": "静音",
    "volume_down": "音量−",
    "volume_up": "音量+",
    "media_next": "下一首",
    "media_previous": "上一首",
    "media_stop": "停止",
    "media_play_pause": "播放/暂停",
    "browser_back": "浏览器后退",
    "browser_forward": "浏览器前进",
    "browser_refresh": "浏览器刷新",
    "browser_stop": "浏览器停止",
    "browser_search": "浏览器搜索",
    "browser_favorites": "浏览器收藏",
    "browser_home": "浏览器主页",
    "launch_mail": "邮件",
    "launch_media": "媒体",
    "launch_app1": "应用 1",
    "launch_app2": "应用 2",
}
for _digit in range(10):
    KEY_LABELS[str(_digit)] = str(_digit)
    KEY_LABELS["num{}".format(_digit)] = str(_digit)
for _letter in "abcdefghijklmnopqrstuvwxyz":
    KEY_LABELS[_letter] = _letter.upper()
for _number in range(1, 25):
    KEY_LABELS["f{}".format(_number)] = "F{}".format(_number)


_WINDOWS_KEY_MAP = {
    0x08: "backspace",
    0x09: "tab",
    0x13: "pause",
    0x14: "caps_lock",
    0x1B: "esc",
    0x20: "space",
    0x21: "page_up",
    0x22: "page_down",
    0x23: "end",
    0x24: "home",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0x2C: "print_screen",
    0x2D: "insert",
    0x2E: "delete",
    0x5B: "lwin",
    0x5C: "rwin",
    0x5D: "menu",
    0x6A: "num_multiply",
    0x6B: "num_add",
    0x6D: "num_subtract",
    0x6E: "num_decimal",
    0x6F: "num_divide",
    0x90: "num_lock",
    0x91: "scroll_lock",
    0xA0: "lshift",
    0xA1: "rshift",
    0xA2: "lctrl",
    0xA3: "rctrl",
    0xA4: "lalt",
    0xA5: "ralt",
    0xA6: "browser_back",
    0xA7: "browser_forward",
    0xA8: "browser_refresh",
    0xA9: "browser_stop",
    0xAA: "browser_search",
    0xAB: "browser_favorites",
    0xAC: "browser_home",
    0xAD: "volume_mute",
    0xAE: "volume_down",
    0xAF: "volume_up",
    0xB0: "media_next",
    0xB1: "media_previous",
    0xB2: "media_stop",
    0xB3: "media_play_pause",
    0xB4: "launch_mail",
    0xB5: "launch_media",
    0xB6: "launch_app1",
    0xB7: "launch_app2",
    0xBA: "semicolon",
    0xBB: "equals",
    0xBC: "comma",
    0xBD: "minus",
    0xBE: "period",
    0xBF: "slash",
    0xC0: "grave",
    0xDB: "bracket_left",
    0xDC: "backslash",
    0xDD: "bracket_right",
    0xDE: "quote",
    0xE2: "oem_102",
}


def normalize_windows_key(vk_code, scan_code=0, flags=0):
    """Map a Windows virtual key to a stable, non-text key identifier."""
    vk_code = int(vk_code)
    scan_code = int(scan_code)
    flags = int(flags)
    extended = bool(flags & 0x01)

    if vk_code == 0x10:  # VK_SHIFT is sometimes not side-specific in hooks.
        return "rshift" if scan_code == 0x36 else "lshift"
    if vk_code == 0x11:
        return "rctrl" if extended else "lctrl"
    if vk_code == 0x12:
        return "ralt" if extended else "lalt"
    if vk_code == 0x0D:
        return "num_enter" if extended else "enter"
    if 0x30 <= vk_code <= 0x39:
        return chr(vk_code)
    if 0x41 <= vk_code <= 0x5A:
        return chr(vk_code).lower()
    if 0x60 <= vk_code <= 0x69:
        return "num{}".format(vk_code - 0x60)
    if 0x70 <= vk_code <= 0x87:
        return "f{}".format(vk_code - 0x6F)
    return _WINDOWS_KEY_MAP.get(vk_code, "vk_{:02x}".format(vk_code))


POLL_KEY_CODES = tuple(
    sorted(
        set(_WINDOWS_KEY_MAP)
        | {0x0D}
        | set(range(0x30, 0x5B))
        | set(range(0x60, 0x70))
        | set(range(0x70, 0x88))
    )
)


def _clean_counts(value):
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for key, count in value.items():
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        if count > 0:
            cleaned[str(key)] = count
    return cleaned


def _clean_bucket(value):
    if not isinstance(value, dict):
        value = {}
    return {
        "keys": _clean_counts(value.get("keys")),
        "mouse": _clean_counts(value.get("mouse")),
    }


class InputStatisticsStore(QObject):
    """Sparse in-memory counters with debounced and atomic persistence."""

    flushed = Signal()

    def __init__(self, path, parent=None, date_provider=None):
        super().__init__(parent)
        self.path = Path(path)
        self._date_provider = date_provider or date.today
        self._days = {}
        self._total = {"keys": {}, "mouse": {}}
        self._dirty = False
        self._last_prune_day = None
        self.last_error = None
        self.last_flush_at = None

        self._idle_flush_timer = QTimer(self)
        self._idle_flush_timer.setSingleShot(True)
        self._idle_flush_timer.setInterval(IDLE_FLUSH_MILLISECONDS)
        self._idle_flush_timer.timeout.connect(self.flush)

        self._max_flush_timer = QTimer(self)
        self._max_flush_timer.setInterval(MAX_FLUSH_MILLISECONDS)
        self._max_flush_timer.timeout.connect(self.flush)
        self._max_flush_timer.start()
        self._load()

    def _current_date(self):
        value = self._date_provider()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    def _today_key(self):
        return self._current_date().isoformat()

    def _prune_old_days(self):
        current_date = self._current_date()
        current_day = current_date.isoformat()
        if self._last_prune_day == current_day:
            return 0
        self._last_prune_day = current_day
        cutoff = current_date - timedelta(days=DAILY_RETENTION_DAYS - 1)
        expired = []
        for day_key in self._days:
            try:
                stored_date = date.fromisoformat(day_key)
            except ValueError:
                expired.append(day_key)
                continue
            if stored_date < cutoff:
                expired.append(day_key)
        for day_key in expired:
            del self._days[day_key]
        if expired:
            self._dirty = True
            self._idle_flush_timer.start()
        return len(expired)

    def _load(self):
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, TypeError, ValueError):
            return
        if not isinstance(payload, dict):
            return

        raw_days = payload.get("days", {})
        if isinstance(raw_days, dict):
            for day_key, bucket in raw_days.items():
                cleaned = _clean_bucket(bucket)
                if cleaned["keys"] or cleaned["mouse"]:
                    self._days[str(day_key)] = cleaned

        raw_total = payload.get("total")
        if isinstance(raw_total, dict):
            self._total = _clean_bucket(raw_total)
        else:
            total = {"keys": defaultdict(int), "mouse": defaultdict(int)}
            for bucket in self._days.values():
                for kind in ("keys", "mouse"):
                    for item, count in bucket[kind].items():
                        total[kind][item] += count
            self._total = {
                "keys": dict(total["keys"]),
                "mouse": dict(total["mouse"]),
            }
        self._prune_old_days()

    def _increment(self, kind, item):
        self._prune_old_days()
        day_key = self._today_key()
        day = self._days.setdefault(day_key, {"keys": {}, "mouse": {}})
        day[kind][item] = day[kind].get(item, 0) + 1
        self._total[kind][item] = self._total[kind].get(item, 0) + 1
        self._dirty = True
        self._idle_flush_timer.start()

    @Slot(str)
    def record_key(self, key_id):
        if key_id:
            self._increment("keys", str(key_id))

    @Slot(str)
    def record_mouse(self, button):
        if button in ("left", "middle", "right"):
            self._increment("mouse", button)

    def snapshot(self, mode="today", day=None):
        self._prune_old_days()
        if mode == "total":
            source = self._total
        else:
            if day is None:
                day_key = self._today_key()
            elif hasattr(day, "isoformat"):
                day_key = day.isoformat()
            else:
                day_key = str(day)
            source = self._days.get(day_key, {"keys": {}, "mouse": {}})
        return {
            "keys": dict(source["keys"]),
            "mouse": dict(source["mouse"]),
        }

    def flush(self):
        self._prune_old_days()
        if not self._dirty:
            return True
        payload = {
            "version": STATISTICS_VERSION,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "days": self._days,
            "total": self._total,
        }
        temporary_path = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("w", encoding="utf-8", newline="\n") as target:
                json.dump(
                    payload,
                    target,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                target.flush()
                os.fsync(target.fileno())
            os.replace(str(temporary_path), str(self.path))
        except OSError as error:
            self.last_error = str(error)
            try:
                temporary_path.unlink()
            except OSError:
                pass
            return False
        self._dirty = False
        self.last_error = None
        self.last_flush_at = datetime.now()
        self.flushed.emit()
        return True

    def close_store(self):
        self._idle_flush_timer.stop()
        self._max_flush_timer.stop()
        self.flush()


def _keyboard_specs():
    specs = []

    def add(key_id, label, x, y, width=1.0, height=1.0):
        specs.append((key_id, label, float(x), float(y), float(width), float(height)))

    add("esc", "Esc", 0, 0)
    for offset, number in enumerate(range(1, 5)):
        add("f{}".format(number), "F{}".format(number), 2 + offset, 0)
    for offset, number in enumerate(range(5, 9)):
        add("f{}".format(number), "F{}".format(number), 6.5 + offset, 0)
    for offset, number in enumerate(range(9, 13)):
        add("f{}".format(number), "F{}".format(number), 11 + offset, 0)
    add("print_screen", "PrtSc", 15.5, 0)
    add("scroll_lock", "ScrLk", 16.5, 0)
    add("pause", "Pause", 17.5, 0)

    row_y = 1.4
    top_row = [
        ("grave", "`"),
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
        ("6", "6"),
        ("7", "7"),
        ("8", "8"),
        ("9", "9"),
        ("0", "0"),
        ("minus", "-"),
        ("equals", "="),
    ]
    for x, (key_id, label) in enumerate(top_row):
        add(key_id, label, x, row_y)
    add("backspace", "Backspace", 13, row_y, 2)
    add("insert", "Ins", 15.5, row_y)
    add("home", "Home", 16.5, row_y)
    add("page_up", "PgUp", 17.5, row_y)
    add("num_lock", "Num", 19, row_y)
    add("num_divide", "/", 20, row_y)
    add("num_multiply", "×", 21, row_y)
    add("num_subtract", "−", 22, row_y)

    row_y = 2.4
    add("tab", "Tab", 0, row_y, 1.5)
    for offset, letter in enumerate("qwertyuiop"):
        add(letter, letter.upper(), 1.5 + offset, row_y)
    add("bracket_left", "[", 11.5, row_y)
    add("bracket_right", "]", 12.5, row_y)
    add("backslash", "\\", 13.5, row_y, 1.5)
    add("delete", "Del", 15.5, row_y)
    add("end", "End", 16.5, row_y)
    add("page_down", "PgDn", 17.5, row_y)
    for offset, number in enumerate((7, 8, 9)):
        add("num{}".format(number), str(number), 19 + offset, row_y)
    add("num_add", "+", 22, row_y, 1, 2)

    row_y = 3.4
    add("caps_lock", "Caps", 0, row_y, 1.8)
    for offset, letter in enumerate("asdfghjkl"):
        add(letter, letter.upper(), 1.8 + offset, row_y)
    add("semicolon", ";", 10.8, row_y)
    add("quote", "'", 11.8, row_y)
    add("enter", "Enter", 12.8, row_y, 2.2)
    for offset, number in enumerate((4, 5, 6)):
        add("num{}".format(number), str(number), 19 + offset, row_y)

    row_y = 4.4
    add("lshift", "L Shift", 0, row_y, 2.3)
    for offset, (key_id, label) in enumerate(
        zip("zxcvbnm", "ZXCVBNM")
    ):
        add(key_id, label, 2.3 + offset, row_y)
    add("comma", ",", 9.3, row_y)
    add("period", ".", 10.3, row_y)
    add("slash", "/", 11.3, row_y)
    add("rshift", "R Shift", 12.3, row_y, 2.7)
    add("up", "↑", 16.5, row_y)
    for offset, number in enumerate((1, 2, 3)):
        add("num{}".format(number), str(number), 19 + offset, row_y)
    add("num_enter", "Enter", 22, row_y, 1, 2)

    row_y = 5.4
    add("lctrl", "L Ctrl", 0, row_y, 1.4)
    add("lwin", "L Win", 1.4, row_y, 1.2)
    add("lalt", "L Alt", 2.6, row_y, 1.3)
    add("space", "Space", 3.9, row_y, 6.2)
    add("ralt", "R Alt", 10.1, row_y, 1.3)
    add("rwin", "R Win", 11.4, row_y, 1.2)
    add("menu", "Menu", 12.6, row_y, 1.1)
    add("rctrl", "R Ctrl", 13.7, row_y, 1.3)
    add("left", "←", 15.5, row_y)
    add("down", "↓", 16.5, row_y)
    add("right", "→", 17.5, row_y)
    add("num0", "0", 19, row_y, 2)
    add("num_decimal", ".", 21, row_y)
    return tuple(specs)


KEYBOARD_SPECS = _keyboard_specs()
VISIBLE_KEY_IDS = frozenset(spec[0] for spec in KEYBOARD_SPECS)


def format_count(count):
    count = int(count)
    if count < 1_000:
        return "{:,}".format(count)
    if count < 1_000_000:
        return "{:.1f}k".format(count / 1_000).replace(".0k", "k")
    return "{:.1f}m".format(count / 1_000_000).replace(".0m", "m")


def _mix_color(start, end, amount):
    amount = max(0.0, min(float(amount), 1.0))
    return QColor(
        round(start.red() + (end.red() - start.red()) * amount),
        round(start.green() + (end.green() - start.green()) * amount),
        round(start.blue() + (end.blue() - start.blue()) * amount),
    )


class KeyboardHeatmapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts = {}
        self._hit_rects = []
        self._hovered_key = None
        self.setMouseTracking(True)
        self.setMinimumHeight(310)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_counts(self, counts):
        self._counts = dict(counts)
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(14, 8, -14, -8)
        scale = min(area.width() / 23.0, area.height() / 6.4)
        origin_x = area.x() + (area.width() - 23.0 * scale) / 2.0
        origin_y = area.y() + (area.height() - 6.4 * scale) / 2.0
        gap = max(3.0, scale * 0.10)
        highest = max(self._counts.values(), default=0)
        denominator = math.log1p(highest) if highest else 1.0
        self._hit_rects = []

        for key_id, label, x, y, width, height in KEYBOARD_SPECS:
            rect = QRectF(
                origin_x + x * scale + gap / 2,
                origin_y + y * scale + gap / 2,
                width * scale - gap,
                height * scale - gap,
            )
            count = self._counts.get(key_id, 0)
            heat = math.log1p(count) / denominator if count else 0.0
            if count:
                fill = _mix_color(QColor("#ffe0bd"), QColor("#f26443"), heat)
                border = _mix_color(QColor("#f1b276"), QColor("#c9452f"), heat)
            else:
                fill = QColor("#fffaf2")
                border = QColor("#eadfce")

            shadow = QRectF(rect)
            shadow.translate(0, max(1.5, scale * 0.055))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(76, 52, 39, 30))
            painter.drawRoundedRect(shadow, 7, 7)
            painter.setPen(QPen(border, 1.0))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 7, 7)

            text_color = QColor("#ffffff") if heat > 0.70 else QColor("#4b382d")
            painter.setPen(text_color)
            label_font = QFont("Microsoft YaHei UI")
            label_font.setPointSizeF(max(5.8, min(8.2, rect.width() / 8.0)))
            label_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(label_font)
            label_rect = rect.adjusted(3, 3, -3, -rect.height() * 0.42)
            painter.drawText(
                label_rect,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                label,
            )

            count_font = QFont("Microsoft YaHei UI")
            count_font.setPointSizeF(max(6.2, min(9.0, rect.width() / 7.2)))
            count_font.setWeight(QFont.Weight.Bold)
            painter.setFont(count_font)
            count_rect = rect.adjusted(2, rect.height() * 0.48, -2, -2)
            painter.drawText(
                count_rect,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                format_count(count),
            )
            self._hit_rects.append((rect, key_id, label, count))

    def mouseMoveEvent(self, event):
        hovered = None
        for rect, key_id, label, count in self._hit_rects:
            if rect.contains(event.position()):
                hovered = key_id
                if hovered != self._hovered_key:
                    QToolTip.showText(
                        event.globalPosition().toPoint(),
                        "{}：{:,} 次".format(KEY_LABELS.get(key_id, label), count),
                        self,
                    )
                break
        if hovered is None and self._hovered_key is not None:
            QToolTip.hideText()
        self._hovered_key = hovered
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hovered_key = None
        QToolTip.hideText()
        super().leaveEvent(event)


class MetricCard(QFrame):
    def __init__(self, title, accent=False, parent=None):
        super().__init__(parent)
        self.setObjectName("accentCard" if accent else "metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        self.value_label = QLabel("0")
        self.value_label.setObjectName("metricValue")
        self.note_label = QLabel("")
        self.note_label.setObjectName("metricNote")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.note_label)

    def set_value(self, value, note=""):
        self.value_label.setText(str(value))
        self.note_label.setText(str(note))


class MouseButtonCard(QFrame):
    def __init__(self, symbol, title, parent=None):
        super().__init__(parent)
        self.setObjectName("mouseCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 11, 16, 11)
        layout.setSpacing(12)
        symbol_label = QLabel(symbol)
        symbol_label.setObjectName("mouseSymbol")
        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)
        title_label = QLabel(title)
        title_label.setObjectName("mouseTitle")
        self.count_label = QLabel("0 次")
        self.count_label.setObjectName("mouseCount")
        text_layout.addWidget(title_label)
        text_layout.addWidget(self.count_label)
        layout.addWidget(symbol_label)
        layout.addLayout(text_layout)
        layout.addStretch()

    def set_count(self, count):
        self.count_label.setText("{:,} 次".format(int(count)))


class InputStatisticsDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._mode = "day"
        self.setWindowTitle("输入足迹 · 豆豆桌宠")
        self.setMinimumSize(980, 650)
        self.resize(1180, 735)
        self.setModal(False)
        self.setStyleSheet(
            """
            QDialog { background: #f6efe5; color: #46352c; }
            QLabel { font-family: "Microsoft YaHei UI"; color: #46352c; }
            QLabel#title { font-size: 22pt; font-weight: 700; }
            QLabel#subtitle { color: #8b7465; font-size: 9.5pt; }
            QLabel#sectionTitle { font-size: 12pt; font-weight: 700; }
            QLabel#sectionHint, QLabel#footer, QLabel#extraKeys {
                color: #927d70; font-size: 8.5pt;
            }
            QPushButton#segment {
                background: transparent; border: none; border-radius: 9px;
                padding: 8px 18px; color: #7c675a; font: 600 9.5pt "Microsoft YaHei UI";
            }
            QPushButton#segment:checked { background: #4c3a30; color: #fffaf3; }
            QFrame#dateSelector {
                background: #fffaf3; border: 1px solid #e4d5c4; border-radius: 11px;
            }
            QPushButton#dateNav {
                background: transparent; border: none; border-radius: 7px;
                min-width: 26px; max-width: 26px; min-height: 28px;
                color: #6e584a; font: 700 14pt "Segoe UI";
            }
            QPushButton#dateNav:hover { background: #f1dfcc; }
            QPushButton#dateNav:disabled { color: #cbbcaf; }
            QDateEdit#dateEdit {
                background: transparent; border: none; padding: 5px 4px;
                color: #4c3a30; font: 600 9.5pt "Microsoft YaHei UI";
                selection-background-color: #e98562;
            }
            QDateEdit#dateEdit::drop-down { border: none; width: 20px; }
            QFrame#metricCard, QFrame#accentCard, QFrame#mouseCard {
                background: #fffaf3; border: 1px solid #eadbca; border-radius: 14px;
            }
            QFrame#accentCard { background: #4d3a30; border-color: #4d3a30; }
            QFrame#accentCard QLabel { color: #fff9f2; }
            QLabel#metricTitle { color: #9b8374; font-size: 8.5pt; }
            QLabel#metricValue { font-size: 18pt; font-weight: 700; }
            QLabel#metricNote { color: #a78f80; font-size: 8pt; }
            QLabel#mouseSymbol {
                background: #f5dfc7; border-radius: 14px; min-width: 28px; min-height: 28px;
                max-width: 28px; max-height: 28px; qproperty-alignment: AlignCenter;
                color: #c85b3f; font-weight: 700;
            }
            QLabel#mouseTitle { color: #8e7769; font-size: 8.5pt; }
            QLabel#mouseCount { font-size: 12pt; font-weight: 700; }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(12)

        header = QHBoxLayout()
        title_layout = QVBoxLayout()
        title_layout.setSpacing(1)
        title = QLabel("输入足迹")
        title.setObjectName("title")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("subtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(self.subtitle)
        header.addLayout(title_layout)
        header.addStretch()

        self.date_controls = QFrame()
        self.date_controls.setObjectName("dateSelector")
        date_layout = QHBoxLayout(self.date_controls)
        date_layout.setContentsMargins(4, 2, 5, 2)
        date_layout.setSpacing(1)
        self.previous_date_button = QPushButton("‹")
        self.previous_date_button.setObjectName("dateNav")
        self.previous_date_button.setToolTip("前一天")
        self.date_edit = QDateEdit()
        self.date_edit.setObjectName("dateEdit")
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setMinimumWidth(126)
        self.next_date_button = QPushButton("›")
        self.next_date_button.setObjectName("dateNav")
        self.next_date_button.setToolTip("后一天")
        date_layout.addWidget(self.previous_date_button)
        date_layout.addWidget(self.date_edit)
        date_layout.addWidget(self.next_date_button)
        self.previous_date_button.clicked.connect(lambda: self._shift_date(-1))
        self.next_date_button.clicked.connect(lambda: self._shift_date(1))
        self.date_edit.dateChanged.connect(self._date_changed)
        self._sync_date_limits(reset_to_today=True)
        header.addWidget(self.date_controls)
        header.addSpacing(8)

        segment_frame = QFrame()
        segment_frame.setStyleSheet(
            "QFrame { background: #eadfd2; border-radius: 11px; padding: 2px; }"
        )
        segment_layout = QHBoxLayout(segment_frame)
        segment_layout.setContentsMargins(2, 2, 2, 2)
        segment_layout.setSpacing(1)
        self.daily_button = QPushButton("每日")
        self.total_button = QPushButton("累计")
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for button in (self.daily_button, self.total_button):
            button.setObjectName("segment")
            button.setCheckable(True)
            self._mode_group.addButton(button)
            segment_layout.addWidget(button)
        self.daily_button.setChecked(True)
        self.daily_button.clicked.connect(lambda: self._set_mode("day"))
        self.total_button.clicked.connect(lambda: self._set_mode("total"))
        header.addWidget(segment_frame)
        root.addLayout(header)

        metric_layout = QHBoxLayout()
        metric_layout.setSpacing(10)
        self.keyboard_metric = MetricCard("键盘按键", accent=True)
        self.mouse_metric = MetricCard("鼠标点击")
        self.favorite_metric = MetricCard("最常按键")
        self.active_metric = MetricCard("使用过的按键")
        for card in (
            self.keyboard_metric,
            self.mouse_metric,
            self.favorite_metric,
            self.active_metric,
        ):
            metric_layout.addWidget(card, 1)
        root.addLayout(metric_layout)

        keyboard_header = QHBoxLayout()
        keyboard_title = QLabel("全键盘热力图")
        keyboard_title.setObjectName("sectionTitle")
        keyboard_hint = QLabel("颜色越深，按下次数越多 · 悬停可看精确数字")
        keyboard_hint.setObjectName("sectionHint")
        keyboard_header.addWidget(keyboard_title)
        keyboard_header.addStretch()
        keyboard_header.addWidget(keyboard_hint)
        root.addLayout(keyboard_header)
        self.keyboard = KeyboardHeatmapWidget()
        root.addWidget(self.keyboard, 1)
        self.extra_keys = QLabel("")
        self.extra_keys.setObjectName("extraKeys")
        self.extra_keys.setWordWrap(True)
        root.addWidget(self.extra_keys)

        mouse_header = QHBoxLayout()
        mouse_title = QLabel("鼠标按键")
        mouse_title.setObjectName("sectionTitle")
        mouse_header.addWidget(mouse_title)
        mouse_header.addStretch()
        root.addLayout(mouse_header)
        mouse_layout = QHBoxLayout()
        mouse_layout.setSpacing(10)
        self.mouse_cards = {
            "left": MouseButtonCard("L", "鼠标左键"),
            "middle": MouseButtonCard("●", "滚轮点击"),
            "right": MouseButtonCard("R", "鼠标右键"),
        }
        for card in self.mouse_cards.values():
            mouse_layout.addWidget(card, 1)
        root.addLayout(mouse_layout)

        self.footer = QLabel(
            "只统计按键标识与次数，不记录输入内容；每日明细滚动保留最近 365 天。"
        )
        self.footer.setObjectName("footer")
        root.addWidget(self.footer)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self.refresh)
        self.store.flushed.connect(self.refresh)
        self.refresh()

    def _set_mode(self, mode):
        self._mode = mode
        self.date_controls.setVisible(mode != "total")
        self.refresh()

    def _sync_date_limits(self, reset_to_today=False):
        today = QDate.currentDate()
        earliest = today.addDays(-(DAILY_RETENTION_DAYS - 1))
        signals_were_blocked = self.date_edit.blockSignals(True)
        try:
            self.date_edit.setDateRange(earliest, today)
            if (
                reset_to_today
                or self.date_edit.date() < earliest
                or self.date_edit.date() > today
            ):
                self.date_edit.setDate(today)
        finally:
            self.date_edit.blockSignals(signals_were_blocked)
        self.previous_date_button.setEnabled(self.date_edit.date() > earliest)
        self.next_date_button.setEnabled(self.date_edit.date() < today)

    def _shift_date(self, days):
        self.date_edit.setDate(self.date_edit.date().addDays(int(days)))

    def _date_changed(self, selected_date):
        del selected_date
        self._sync_date_limits()
        self.refresh()

    def refresh(self):
        self._sync_date_limits()
        selected_day = self.date_edit.date().toString(Qt.DateFormat.ISODate)
        snapshot = self.store.snapshot(self._mode, selected_day)
        keys = snapshot["keys"]
        mouse = snapshot["mouse"]
        keyboard_total = sum(keys.values())
        mouse_total = sum(mouse.values())
        favorite_key = max(keys, key=keys.get) if keys else None
        favorite_label = KEY_LABELS.get(favorite_key, favorite_key or "暂无")
        favorite_count = keys.get(favorite_key, 0) if favorite_key else 0
        active_keys = sum(
            1
            for key_id, count in keys.items()
            if key_id in VISIBLE_KEY_IDS and count > 0
        )

        if self._mode == "day":
            if selected_day == self.store._today_key():
                self.subtitle.setText("{} · 今日".format(selected_day))
            else:
                self.subtitle.setText("{} · 历史记录".format(selected_day))
        else:
            self.subtitle.setText("从开始使用统计功能至今")
        self.keyboard_metric.set_value("{:,}".format(keyboard_total), "次按下")
        self.mouse_metric.set_value("{:,}".format(mouse_total), "次点击")
        self.favorite_metric.set_value(
            favorite_label,
            "{:,} 次".format(favorite_count) if favorite_count else "还没有数据",
        )
        self.active_metric.set_value("{} / {}".format(active_keys, len(VISIBLE_KEY_IDS)), "种按键")
        self.keyboard.set_counts(keys)
        for button, card in self.mouse_cards.items():
            card.set_count(mouse.get(button, 0))

        extras = [
            (key_id, count)
            for key_id, count in keys.items()
            if key_id not in VISIBLE_KEY_IDS and count > 0
        ]
        extras.sort(key=lambda item: item[1], reverse=True)
        if extras:
            text = "扩展按键：" + "  ·  ".join(
                "{} {:,}".format(KEY_LABELS.get(key_id, key_id), count)
                for key_id, count in extras
            )
            self.extra_keys.setText(text)
            self.extra_keys.show()
        else:
            self.extra_keys.hide()

        if self.store.last_error:
            self.footer.setText("统计仍保留在内存中，但暂时无法写入本机文件：{}".format(self.store.last_error))
        else:
            self.footer.setText(
                "只统计按键标识与次数，不记录输入内容；每日明细滚动保留最近 365 天。"
            )

    def showEvent(self, event):
        self._mode = "day"
        self.daily_button.setChecked(True)
        self.date_controls.show()
        self._sync_date_limits(reset_to_today=True)
        self.refresh()
        self._refresh_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._refresh_timer.stop()
        super().hideEvent(event)
