import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from input_statistics import (
    DAILY_RETENTION_DAYS,
    InputStatisticsDialog,
    InputStatisticsStore,
    KEYBOARD_SPECS,
    VISIBLE_KEY_IDS,
    normalize_windows_key,
)


class InputStatisticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_windows_key_mapping_distinguishes_sides_and_keypads(self):
        self.assertEqual(normalize_windows_key(0x10, 0x2A), "lshift")
        self.assertEqual(normalize_windows_key(0x10, 0x36), "rshift")
        self.assertEqual(normalize_windows_key(0x11, flags=0), "lctrl")
        self.assertEqual(normalize_windows_key(0x11, flags=1), "rctrl")
        self.assertEqual(normalize_windows_key(0x12, flags=0), "lalt")
        self.assertEqual(normalize_windows_key(0x12, flags=1), "ralt")
        self.assertEqual(normalize_windows_key(0x0D, flags=0), "enter")
        self.assertEqual(normalize_windows_key(0x0D, flags=1), "num_enter")
        self.assertEqual(normalize_windows_key(0xA2), "lctrl")
        self.assertEqual(normalize_windows_key(0xA3), "rctrl")

    def test_full_size_keyboard_has_unique_visible_keys(self):
        key_ids = [spec[0] for spec in KEYBOARD_SPECS]
        self.assertEqual(len(key_ids), len(set(key_ids)))
        self.assertEqual(set(key_ids), set(VISIBLE_KEY_IDS))
        self.assertGreaterEqual(len(key_ids), 100)
        for key_id in (
            "lctrl",
            "rctrl",
            "lshift",
            "rshift",
            "lalt",
            "ralt",
            "enter",
            "num_enter",
        ):
            self.assertIn(key_id, VISIBLE_KEY_IDS)

    def test_daily_total_and_atomic_persistence(self):
        current_day = [date(2026, 8, 12)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.json"
            store = InputStatisticsStore(
                path, date_provider=lambda: current_day[0]
            )
            store.record_key("lctrl")
            store.record_key("a")
            store.record_mouse("left")
            self.assertEqual(store.snapshot("today")["keys"]["lctrl"], 1)

            current_day[0] = date(2026, 8, 13)
            store.record_key("rctrl")
            store.record_mouse("middle")
            today = store.snapshot("today")
            total = store.snapshot("total")
            self.assertNotIn("lctrl", today["keys"])
            self.assertEqual(today["keys"]["rctrl"], 1)
            self.assertEqual(total["keys"], {"lctrl": 1, "a": 1, "rctrl": 1})
            self.assertEqual(total["mouse"], {"left": 1, "middle": 1})
            self.assertTrue(store.flush())
            self.assertTrue(path.exists())
            self.assertFalse(path.with_name(path.name + ".tmp").exists())
            store.close_store()

            with path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
            self.assertEqual(payload["version"], 1)
            self.assertIn("2026-08-12", payload["days"])
            self.assertIn("2026-08-13", payload["days"])

            reloaded = InputStatisticsStore(
                path, date_provider=lambda: current_day[0]
            )
            try:
                self.assertEqual(reloaded.snapshot("today"), today)
                self.assertEqual(reloaded.snapshot("total"), total)
            finally:
                reloaded.close_store()

    def test_daily_history_rolls_over_after_365_days_without_reducing_total(self):
        current_day = [date(2025, 1, 1)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rolling-stats.json"
            store = InputStatisticsStore(
                path, date_provider=lambda: current_day[0]
            )
            first_day = current_day[0]
            for offset in range(370):
                current_day[0] = first_day + timedelta(days=offset)
                store.record_key("a")

            earliest_retained = current_day[0] - timedelta(
                days=DAILY_RETENTION_DAYS - 1
            )
            self.assertEqual(len(store._days), DAILY_RETENTION_DAYS)
            self.assertEqual(
                store.snapshot("total")["keys"]["a"], 370
            )
            self.assertEqual(
                store.snapshot("day", first_day)["keys"], {}
            )
            self.assertEqual(
                store.snapshot("day", earliest_retained)["keys"]["a"], 1
            )
            self.assertTrue(store.flush())
            store.close_store()

            with path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
            self.assertEqual(len(payload["days"]), DAILY_RETENTION_DAYS)
            self.assertNotIn(first_day.isoformat(), payload["days"])
            self.assertEqual(payload["total"]["keys"]["a"], 370)

    def test_dialog_can_view_a_previous_day_and_defaults_to_today(self):
        current_day = [date.today() - timedelta(days=1)]
        with tempfile.TemporaryDirectory() as directory:
            store = InputStatisticsStore(
                Path(directory) / "history-stats.json",
                date_provider=lambda: current_day[0],
            )
            store.record_key("a")
            store.record_key("a")
            previous_day = current_day[0]
            current_day[0] = date.today()
            store.record_key("b")

            dialog = InputStatisticsDialog(store)
            try:
                dialog.date_edit.setDate(
                    QDate(
                        previous_day.year,
                        previous_day.month,
                        previous_day.day,
                    )
                )
                dialog._set_mode("day")
                self.assertEqual(dialog.keyboard_metric.value_label.text(), "2")
                self.assertIn("历史记录", dialog.subtitle.text())

                dialog._set_mode("total")
                self.assertEqual(dialog.keyboard_metric.value_label.text(), "3")

                dialog.show()
                self.app.processEvents()
                self.assertEqual(dialog._mode, "day")
                self.assertEqual(dialog.date_edit.date(), QDate.currentDate())
            finally:
                dialog.close()
                store.close_store()


if __name__ == "__main__":
    unittest.main()
