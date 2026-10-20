import tkinter as tk
import unittest
from unittest.mock import patch
from main import Launcher


class LaunchIntegrationTests(unittest.TestCase):
    def test_setup_starts_browser_kiosk_and_closes_worker(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        launcher = None
        try:
            launcher = Launcher(root)
            with patch("web_kiosk.webbrowser.open", return_value=True) as opened:
                launcher.start()
                root.update()
                self.assertTrue(launcher.app.server.thread.is_alive())
                opened.assert_called_once_with(launcher.app.server.url)
                first_worker = launcher.worker
                launcher.start()
                self.assertIs(launcher.worker, first_worker)
            launcher.shutdown()
            self.assertFalse(launcher.worker.thread.is_alive())
            launcher.app.close()
            self.assertFalse(launcher.app.server.thread.is_alive())
        finally:
            if launcher:
                launcher.shutdown()
                if launcher.app and not launcher.app.closing:
                    launcher.app.server.close()
            try:
                root.destroy()
            except tk.TclError:
                pass
