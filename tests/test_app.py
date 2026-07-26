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

    def test_pet_size_stays_in_bounds(self):
        self.pet.set_pet_height(1)
        self.assertEqual(self.pet.height(), 150)
        self.pet.set_pet_height(9999)
        self.assertEqual(self.pet.height(), 680)
        self.pet.set_pet_height(340)
        self.assertEqual(self.pet.height(), 340)

    def test_all_animation_frames_restore_geometry(self):
        for kind in (
            "jump",
            "squash",
            "shake",
            "mouse_click",
            "type",
            "nod",
            "stretch",
        ):
            base = QRect(self.pet.geometry())
            self.pet._animation_base_rect = QRect(base)
            for progress in (0.0, 0.25, 0.5, 0.75, 1.0):
                self.pet._apply_animation(kind, progress)
            self.pet._finish_animation()
            self.assertEqual(self.pet.geometry(), base)

    def test_mouse_and_keyboard_reactions_show_props(self):
        self.pet._input_echo_enabled = True
        self.pet.react_to_mouse_click("left")
        self.assertEqual(self.pet._overlay_kind, "mouse_left")
        self.pet._stop_overlay_animation()
        self.pet._stop_animation()

        self.pet.react_to_keyboard_press()
        self.assertEqual(self.pet._overlay_kind, "keyboard")
        self.assertTrue(self.pet._typing_timer.isActive())
        self.pet._typing_timer.stop()
        self.pet._typing_deadline = 0.0
        self.pet._overlay_kind = None
        self.pet._stop_animation()

    def test_bubble_does_not_cover_pet_when_space_is_available(self):
        pet_rect = QRect(800, 600, 210, 340)
        screen_rect = QRect(0, 0, 1920, 1080)
        self.pet.bubble.show_message("测试气泡", pet_rect, screen_rect)
        self.assertFalse(self.pet.bubble.geometry().intersects(pet_rect))
        self.pet.bubble.hide()


if __name__ == "__main__":
    unittest.main()
