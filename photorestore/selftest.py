"""Offline packaged-app smoke check. Uses disposable data; never contacts Google."""

import tempfile
import threading
from pathlib import Path


def run():
    import webview
    from PIL import Image
    from .app import build_html
    from .metadata import apply_metadata, normalize
    from .runtime import Runtime, exiftool_path
    from .service import Service

    with tempfile.TemporaryDirectory(prefix="takeout-selftest-") as tmp:
        folder = Path(tmp)
        Runtime(folder).manifest()
        photo = folder / "metadata-test.jpg"
        Image.new("RGB", (8, 8), "white").save(photo)
        apply_metadata(
            exiftool_path(),
            photo,
            normalize(
                {
                    "photoTakenTime": {"timestamp": "946684800"},
                    "description": "Offline self-test café 東京",
                    "geoData": {"latitude": 0, "longitude": -12.5, "altitude": -20},
                }
            ),
        )
        service = Service(folder / "app-data")
        result = []

        class Bridge:
            def request(self, action, params=None, token=None):
                return service.call(action, params, token)

        window = webview.create_window(
            "Takeout Restore — offline self-test",
            html=build_html(),
            js_api=Bridge(),
            hidden=True,
            width=820,
            height=620,
        )

        def test():
            try:
                window.events.loaded.wait(20)
                done = threading.Event()

                def callback(value):
                    result.append(value)
                    done.set()

                window.evaluate_js(
                    "pywebview.api.request('register', {username:'Offline Test',"
                    " password:'temporary self-test passphrase'}, null).then(r => {token=r.data?.token; return {ok:r.ok, role:r.data?.user.role}})",
                    callback,
                )
                if not done.wait(20):
                    result.append({"error": "Native callback timed out"})
                else:
                    with service.store.connect() as con:
                        service.store.audit(
                            con, service.session.user_id, "layout.test", {"detail": "x" * 2000}
                        )
                    done.clear()
                    window.evaluate_js(
                        "page='logs';refresh().then(()=>({layout:document.documentElement.scrollWidth"
                        "<=document.documentElement.clientWidth && [...document.querySelectorAll('.audit-detail')]"
                        ".every(el=>el.scrollWidth<=el.clientWidth)}))",
                        callback,
                    )
                    if not done.wait(20):
                        result.append({"error": "Layout callback timed out"})
            except Exception as exc:
                result.append({"error_type": type(exc).__name__})
            finally:
                window.destroy()

        webview.start(test, debug=False, private_mode=True)
        service.logout()
        if not result or result[0].get("ok") is not True or result[0].get("role") != "admin":
            raise RuntimeError("Packaged native bridge self-test failed")
        if len(result) != 2 or result[1].get("layout") is not True:
            raise RuntimeError("Packaged native layout self-test failed")
    return {
        "native_bridge": "passed",
        "accounts": "passed",
        "bundled_exiftool": "passed",
        "native_layout": "passed",
    }
