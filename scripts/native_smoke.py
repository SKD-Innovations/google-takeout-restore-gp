"""Native webview bridge smoke test with a hidden window and temporary account store."""

import tempfile
import threading
from pathlib import Path
import webview
from photorestore.app import build_html
from photorestore.service import Service

with tempfile.TemporaryDirectory() as tmp:
    service = Service(Path(tmp))
    result = []

    class Bridge:
        def request(self, action, params=None, token=None):
            return service.call(action, params, token)

    window = webview.create_window(
        "Takeout Restore — native test", html=build_html(), js_api=Bridge(), hidden=True
    )

    def test():
        try:
            window.events.loaded.wait(20)
            done = threading.Event()

            def callback(value):
                result.append(value)
                done.set()

            window.evaluate_js(
                "pywebview.api.request('bootstrap',{},null).then(r => ({ok:r.ok,has_accounts:r.data.has_accounts,heading:document.querySelector('h1')?.textContent}))",
                callback,
            )
            if not done.wait(20):
                result.append({"error": "native callback timeout"})
        finally:
            window.destroy()

    webview.start(test, debug=False, private_mode=True)
    assert result and result[0].get("ok") and result[0].get("has_accounts") is False, result
    print("Native webview bridge passed:", result)
