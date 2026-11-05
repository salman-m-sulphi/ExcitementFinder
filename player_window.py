"""Desktop player windows: fixed local origin, anonymous channel, one owner."""
import json
import re
import uuid
import threading
from urllib.parse import urlencode


class PlayerAPI:
    def __init__(self, controller):
        self._controller = controller
        self._window = None
        self._fullscreen = False

    def open_player_window(self, job, channel):
        return self._controller.open(job, channel)

    def close_player_window(self):
        if self._window is not None and self._window is not self._controller.main:
            self._window.destroy()
        return True

    def set_player_fullscreen(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Fullscreen state must be boolean')
        if enabled != self._fullscreen:
            self._window.toggle_fullscreen()
            self._fullscreen = enabled
        return self._fullscreen


class PlayerWindows:
    def __init__(self, url):
        self._url = url
        self._child = None
        self._identity = None
        self._lock = threading.RLock()
        self.main = None

    def open(self, job, channel):
        import webview
        if not isinstance(job, str) or not re.fullmatch('[a-f0-9]{32}', job):
            raise ValueError('Invalid analysis')
        if not isinstance(channel, str) or str(uuid.UUID(channel)) != channel:
            raise ValueError('Invalid player channel')
        with self._lock:
            if self._child is not None and self._identity == (job, channel):
                self._child.restore()
                self._child.show()
                return True
            if self._child is not None:
                self._child.destroy()
            api = PlayerAPI(self)
            window = webview.create_window('Floating player — Excitement Finder',
                self._url + '/?' + urlencode({'player':'window','channel':channel}) + '#' + job,
                js_api=api, width=660, height=480, min_size=(360,260),
                x=self.main.x + max(0,self.main.width-684),
                y=self.main.y + max(0,self.main.height-504),
                on_top=True, background_color='#101413', text_select=True)
            api._window = window
            self._child, self._identity = window, (job, channel)

            def closed():
                with self._lock:
                    if self._child is window:
                        self._child = None
                        self._identity = None
                # Recover using the last reported position if a window closes
                # before its final BroadcastChannel message can be delivered.
                try:
                    self.main.evaluate_js('setTimeout(() => window.ExcitementPlayer?.windowClosed(' + json.dumps(job) + ',' + json.dumps(channel) + '), 300)')
                except Exception:
                    pass

            # A synchronous Windows closing handler must never wait for JS:
            # WebView2 needs that same UI thread to complete the evaluation.
            # beforeunload sends the exact state; closed provides recovery.
            window.events.closed += closed
            return True

    def close_all(self):
        with self._lock:
            child = self._child
            self._child = None
        if child is not None:
            child.destroy()
