import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtWidgets import QApplication

from main import (
    DialogueEditorDialog,
    DesktopPet,
    autostart_command,
    create_single_instance_guard,
)


class DesktopPetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.settings_directory = tempfile.TemporaryDirectory()
        cls.settings_path = (
            Path(cls.settings_directory.name) / "豆豆桌宠测试配置.ini"
        )
        settings = QSettings(
            str(cls.settings_path),
            QSettings.Format.IniFormat,
        )
        cls.pet = DesktopPet(
            enable_system_input=False,
            settings=settings,
        )

    @classmethod
    def tearDownClass(cls):
        cls.pet.close()
        cls.settings_directory.cleanup()

    def test_transparent_asset_is_valid(self):
        image = Image.open(ROOT / "assets" / "pet_cropped.png")
        self.assertEqual(image.mode, "RGBA")
        alpha = image.getchannel("A")
        self.assertEqual(alpha.getpixel((0, 0)), 0)
        self.assertEqual(alpha.getpixel((image.width - 1, image.height - 1)), 0)
        self.assertEqual(alpha.getextrema(), (0, 255))
        for relative_path in DesktopPet.POSE_FILES.values():
            pose = Image.open(ROOT / relative_path)
            self.assertEqual(pose.mode, "RGBA")
            pose_alpha = pose.getchannel("A")
            self.assertEqual(pose_alpha.getpixel((0, 0)), 0)
            self.assertEqual(
                pose_alpha.getpixel((pose.width - 1, pose.height - 1)),
                0,
            )
            self.assertEqual(pose_alpha.getextrema(), (0, 255))

    def test_pet_size_stays_in_bounds(self):
        self.pet.set_pet_height(1)
        self.assertEqual(self.pet.height(), 90)
        self.pet.set_pet_height(9999)
        self.assertEqual(self.pet.height(), 365)
        self.pet.set_pet_height(150)
        self.assertEqual(self.pet.height(), 150)

    def test_all_animation_frames_restore_geometry(self):
        for kind in ("jump", "squash", "shake"):
            base = QRect(self.pet.geometry())
            self.pet._animation_base_rect = QRect(base)
            for progress in (0.0, 0.25, 0.5, 0.75, 1.0):
                self.pet._apply_animation(kind, progress)
            self.pet._finish_animation()
            self.assertEqual(self.pet.geometry(), base)

    def test_mouse_and_keyboard_reactions_show_props(self):
        self.pet._input_echo_enabled = True
        self.pet.react_to_mouse_click("left")
        self.assertEqual(self.pet._pose_mode, "mouse")
        self.assertEqual(self.pet._active_pose, "mouse_ready")
        self.assertTrue(self.pet._pose_timer.isActive())
        self.pet._stop_pose_sequence()

        self.pet.react_to_keyboard_press()
        self.assertEqual(self.pet._pose_mode, "typing")
        self.assertIn(
            self.pet._active_pose,
            ("typing_left", "typing_right"),
        )
        self.assertTrue(self.pet._typing_timer.isActive())
        self.pet._typing_timer.stop()
        self.pet._typing_deadline = 0.0
        self.pet._stop_pose_sequence()

    def test_local_mouse_press_is_not_echoed_as_a_global_click(self):
        self.pet._typing_timer.stop()
        self.pet._stop_pose_sequence()
        self.pet._input_echo_enabled = True
        self.pet._dragging = False
        self.pet._press_global = self.pet.mapToGlobal(self.pet.rect().center())
        try:
            self.pet.react_to_mouse_click("left")
            self.assertIsNone(self.pet._active_pose)
            self.assertIsNone(self.pet._pose_mode)
            self.assertFalse(self.pet._pose_timer.isActive())
        finally:
            self.pet._press_global = None

    def test_drag_start_cancels_a_stale_pose_anchor(self):
        class MoveEvent:
            def __init__(self, global_position):
                self._global_position = QPointF(global_position)
                self.accepted = False

            def globalPosition(self):
                return self._global_position

            def buttons(self):
                return Qt.MouseButton.LeftButton

            def accept(self):
                self.accepted = True

        self.pet._typing_timer.stop()
        self.pet._stop_pose_sequence()
        self.pet.set_pet_height(150)
        self.pet.move(420, 300)
        drag_origin = self.pet.frameGeometry().topLeft()
        press_global = QPoint(500, 500)
        delta = QPoint(QApplication.startDragDistance() + 20, 16)
        self.pet._press_global = press_global
        self.pet._drag_origin = drag_origin
        self.pet._dragging = False

        self.pet._start_pose_sequence([("mouse_ready", 1000)], "mouse")
        event = MoveEvent(press_global + delta)
        try:
            self.pet.mouseMoveEvent(event)
            self.assertTrue(event.accepted)
            self.assertTrue(self.pet._dragging)
            self.assertIsNone(self.pet._active_pose)
            self.assertFalse(self.pet._pose_timer.isActive())
            self.assertEqual(self.pet.pos(), drag_origin + delta)
        finally:
            self.pet._press_global = None
            self.pet._drag_origin = None
            self.pet._dragging = False
            self.pet._stop_pose_sequence()

    def test_input_pose_transitions_do_not_move_pet_left(self):
        self.pet._typing_timer.stop()
        self.pet._stop_pose_sequence()
        self.pet.set_pet_height(150)
        screen = self.pet._screen_geometry()
        self.pet.move(
            screen.right() - self.pet.width() + 1,
            screen.bottom() - self.pet.height() + 1,
        )
        base_rect = QRect(self.pet.geometry())

        self.pet.react_to_mouse_click("left")
        self.assertLessEqual(
            abs(self.pet.geometry().center().x() - base_rect.center().x()),
            1,
        )
        self.pet._stop_pose_sequence()
        self.assertEqual(self.pet.geometry(), base_rect)

        self.pet.react_to_keyboard_press()
        self.pet.react_to_keyboard_press()
        self.assertLessEqual(
            abs(self.pet.geometry().center().x() - base_rect.center().x()),
            1,
        )
        self.pet._typing_timer.stop()
        self.pet._typing_deadline = 0.0
        self.pet._stop_pose_sequence()
        self.assertEqual(self.pet.geometry(), base_rect)

    def test_bubble_does_not_cover_pet_when_space_is_available(self):
        pet_rect = QRect(800, 600, 210, 340)
        screen_rect = QRect(0, 0, 1920, 1080)
        self.pet.bubble.show_message("测试气泡", pet_rect, screen_rect)
        self.assertFalse(self.pet.bubble.geometry().intersects(pet_rect))
        self.pet.bubble.hide()

    def test_complete_pose_sprites_and_idle_settings(self):
        self.assertEqual(
            set(self.pet._pose_pixmaps),
            set(DesktopPet.POSE_FILES),
        )
        self.assertTrue(
            all(not pose.isNull() for pose in self.pet._pose_pixmaps.values())
        )

        self.pet.set_idle_interval(5)
        self.assertEqual(self.pet._idle_interval_seconds, 5)
        self.pet.set_idle_action_enabled("look", False)
        self.assertNotIn("look", self.pet._enabled_idle_actions)
        self.pet.set_idle_action_enabled("look", True)
        self.assertIn("look", self.pet._enabled_idle_actions)
        self.pet.preview_idle_action("look")
        self.assertEqual(self.pet._pose_mode, "idle")
        self.assertEqual(self.pet._active_pose, "idle_look_left")
        self.assertTrue(self.pet._pose_timer.isActive())
        self.pet._stop_pose_sequence()
        self.pet.set_idle_interval(20)

    def test_dialogue_editor_supports_custom_and_empty_categories(self):
        configured = {
            key: list(values) for key, values in DesktopPet.DIALOGUES.items()
        }
        dialog = DialogueEditorDialog(configured, DesktopPet.DIALOGUES)
        changes = []
        dialog.dialogues_changed.connect(changes.append)
        try:
            self.assertEqual(dialog.category_combo.currentData(), "jump")
            dialog.dialogue_input.setText("豆豆新增的测试对话")
            dialog._add_dialogue()
            values = dialog.configured_dialogues()
            self.assertIn("豆豆新增的测试对话", values["jump"])
            self.assertIn("豆豆新增的测试对话", changes[-1]["jump"])

            dialog.dialogue_list.clear()
            dialog.dialogue_input.setText("豆豆，跳！")
            values = dialog.configured_dialogues()
            self.assertEqual(values["jump"], ["豆豆，跳！"])

            dialog.dialogue_list.clear()
            dialog.dialogue_input.clear()
            values = dialog.configured_dialogues()
            self.assertEqual(values["jump"], [])

            dialog.dialogue_input.setText("   \t  ")
            values = dialog.configured_dialogues()
            self.assertEqual(values["jump"], [])
            self.assertEqual(dialog.dialogue_list.count(), 0)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_empty_dialogue_category_is_safe(self):
        original_dialogues = self.pet._dialogues
        self.pet._dialogues = {
            key: list(values) for key, values in original_dialogues.items()
        }
        self.pet._dialogues["mouse"] = []
        try:
            self.assertIsNone(self.pet._random_dialogue("mouse"))
            self.pet._maybe_show_input_bubble("mouse", 0)
        finally:
            self.pet._dialogues = original_dialogues

    def test_jump_uses_the_configured_dialogue(self):
        self.pet._stop_animation()
        original_dialogues = self.pet._dialogues
        original_interaction_index = self.pet._interaction_index
        self.pet._dialogues = {
            key: list(values) for key, values in original_dialogues.items()
        }
        self.pet._dialogues["jump"] = ["豆豆，跳！"]
        self.pet._interaction_index = 0
        try:
            self.pet.trigger_interaction()
            self.assertEqual(self.pet.bubble._text, "豆豆，跳！")
        finally:
            self.pet._stop_animation()
            self.pet.bubble.hide()
            self.pet._dialogues = original_dialogues
            self.pet._interaction_index = original_interaction_index

    def test_settings_are_stored_in_portable_ini_file(self):
        self.pet.settings.sync()
        self.assertEqual(
            Path(self.pet.settings.fileName()).resolve(),
            self.settings_path.resolve(),
        )
        self.assertEqual(
            self.pet.settings.format(),
            QSettings.Format.IniFormat,
        )
        self.assertTrue(self.settings_path.exists())

    def test_single_instance_guard_rejects_second_instance(self):
        key = "DoudouDesktopPet.Test.{}".format(os.getpid())
        first_guard = create_single_instance_guard(key)
        self.assertIsNotNone(first_guard)
        try:
            self.assertIsNone(create_single_instance_guard(key))
        finally:
            first_guard.detach()

    def test_autostart_command_contains_current_program(self):
        command = autostart_command()
        self.assertIn(str(Path(sys.executable).resolve()), command)
        self.assertIn(str(ROOT / "main.py"), command)


if __name__ == "__main__":
    unittest.main()
