import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from main import DesktopPet


class DesktopPetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.pet = DesktopPet(enable_system_input=False)

    @classmethod
    def tearDownClass(cls):
        cls.pet.close()

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
        self.assertEqual(self.pet.height(), 150)
        self.pet.set_pet_height(9999)
        self.assertEqual(self.pet.height(), 680)
        self.pet.set_pet_height(340)
        self.assertEqual(self.pet.height(), 340)

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

    def test_input_pose_transitions_do_not_move_pet_left(self):
        self.pet._typing_timer.stop()
        self.pet._stop_pose_sequence()
        self.pet.set_pet_height(340)
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


if __name__ == "__main__":
    unittest.main()
