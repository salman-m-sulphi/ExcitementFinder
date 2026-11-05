import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from player_window import PlayerAPI, PlayerWindows


class PlayerWindowTests(unittest.TestCase):
    def test_fullscreen_is_explicit_and_repeat_calls_do_not_toggle_back(self):
        api=PlayerAPI(Mock());api._window=Mock()
        self.assertTrue(api.set_player_fullscreen(True))
        self.assertTrue(api.set_player_fullscreen(True))
        api._window.toggle_fullscreen.assert_called_once()
        self.assertFalse(api.set_player_fullscreen(False))
        self.assertEqual(api._window.toggle_fullscreen.call_count,2)
        with self.assertRaises(ValueError):api.set_player_fullscreen('true')

    def test_window_request_cannot_navigate_to_external_or_arbitrary_urls(self):
        players=PlayerWindows('http://127.0.0.1:1234')
        with self.assertRaises(ValueError):players.open('https://example.com','e2f90c1d-752d-457d-bb39-bda3958c3503')
        with self.assertRaises(ValueError):players.open('a'*32,'not-a-channel')

    def test_closing_popout_api_cannot_destroy_main_window(self):
        controller=Mock();controller.main=Mock()
        api=PlayerAPI(controller);api._window=controller.main
        api.close_player_window();controller.main.destroy.assert_not_called()


if __name__=='__main__':unittest.main()
