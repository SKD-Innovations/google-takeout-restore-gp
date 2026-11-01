import multiprocessing
import os
import secrets
import sys
from pathlib import Path
from filelock import FileLock, Timeout
from platformdirs import user_data_path
from .service import Service, StartupSupport
from .errors import AppError
from .macos import register_installed_app
from .diagnostics import log_event, logger_for
from .maintenance import close_logs


def build_html():
    ui = Path(__file__).parent / "ui"
    nonce = secrets.token_urlsafe(24)
    return (
        (ui / "index.html")
        .read_text(encoding="utf-8")
        .replace("{{NONCE}}", nonce)
        .replace("{{CSS}}", (ui / "style.css").read_text(encoding="utf-8"))
        .replace("{{JS}}", (ui / "app.js").read_text(encoding="utf-8"))
    )


def main():
    multiprocessing.freeze_support()
    if "--self-test" in sys.argv:
        from .selftest import run

        try:
            print(run())
        except Exception as exc:
            if sys.stderr:
                sys.stderr.write("Offline self-test failed: " + type(exc).__name__ + "\n")
            raise SystemExit(1) from None
        return
    os.umask(0o077)
    root = user_data_path("TakeoutRestore", appauthor=False)
    # Separate data folder is only available in an unfrozen development build.
    if not getattr(sys, "frozen", False) and os.environ.get("TAKEOUT_DEV_DATA"):
        root = Path(os.environ["TAKEOUT_DEV_DATA"])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    import webview

    lock = FileLock(root / "application.lock")
    try:
        lock.acquire(timeout=0)
    except Timeout:
        webview.create_window(
            "Takeout Restore",
            html="<h2>Takeout Restore is already open.</h2><p>Switch to the existing window.</p>",
            width=450,
            height=180,
        )
        webview.start()
        return
    try:
        startup_logger = logger_for(root / "logs")
        registered = register_installed_app(root)
        if registered is not None:
            log_event(
                startup_logger, "mac.registration.refreshed" if registered else "mac.registration.unavailable"
            )

        service = None

        def crash_hook(kind, value, tb):
            # Clear all data closes log handles; recreate the private logger if needed.
            log_event(logger_for(root / "logs"), "application.crash", "GPP-901", value)
            if isinstance(service, Service):
                service.capture_incident("GPP-901", "application_crash", value)

        sys.excepthook = crash_hook
        try:
            service = Service(root)
        except Exception as exc:
            detail = exc.public() if isinstance(exc, AppError) else AppError("GPP-501").public()
            log_event(startup_logger, "startup.error", detail["code"], exc)
            startup_support = StartupSupport(root, detail["code"], exc)

            class StartupBridge:
                def request(self, action, params=None, token=None):
                    return startup_support.call(action, params, token)

            startup_support.window = webview.create_window(
                "Takeout Restore",
                html=build_html(),
                js_api=StartupBridge(),
                width=820,
                height=620,
            )
            webview.start(debug=False, private_mode=True)
            return

        class Bridge:
            def request(self, action, params=None, token=None):
                return service.call(action, params, token)

        window = webview.create_window(
            "Takeout Restore",
            html=build_html(),
            js_api=Bridge(),
            width=1180,
            height=820,
            min_size=(820, 620),
            background_color="#f6f7f9",
        )
        service.window = window

        def closing():
            if service.job["active"]:
                service.stop.set()
                # Do not kill a submitted upload. The UI explains the pause boundary.
                service.job["phase"] = "Pausing — close again when the current item finishes"
                return False
            service.logout()
            return True

        window.events.closing += closing
        webview.settings["ALLOW_DOWNLOADS"] = False
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.start(debug=False, private_mode=True, gui="gtk" if sys.platform.startswith("linux") else None)
    finally:
        close_logs(root)
        lock.release()
        # Retain the empty lock file: unlinking it could race another app instance.


if __name__ == "__main__":
    main()
