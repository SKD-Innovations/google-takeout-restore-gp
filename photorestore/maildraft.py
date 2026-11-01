"""Open a mail composer for user review; never send mail programmatically."""

import sys
import threading
import webbrowser
from urllib.parse import urlencode, quote
from .support import SUPPORT_EMAIL

_composers = []


def native_mac_draft(subject, body, attachment):
    from AppKit import NSSharingService, NSSharingServiceNameComposeEmail
    from Foundation import NSURL, NSThread
    from PyObjCTools import AppHelper

    done, cancelled = threading.Event(), threading.Event()
    result = {"opened": False}

    def compose():
        if cancelled.is_set():
            done.set()
            return
        try:
            service = NSSharingService.sharingServiceNamed_(NSSharingServiceNameComposeEmail)
            items = [body, NSURL.fileURLWithPath_(str(attachment))]
            if service and service.canPerformWithItems_(items):
                service.setRecipients_([SUPPORT_EMAIL])
                service.setSubject_(subject)
                # Retain the asynchronous sharing service for the life of the app.
                _composers.append(service)
                service.performWithItems_(items)
                result["opened"] = True
        except Exception:
            result["opened"] = False
        finally:
            done.set()

    if NSThread.isMainThread():
        compose()
    else:
        AppHelper.callAfter(compose)
        if not done.wait(10):
            cancelled.set()
    return result["opened"]


def open_report_draft(subject, body, attachment):
    if sys.platform == "darwin":
        try:
            opened = native_mac_draft(subject, body, attachment)
        except Exception:
            opened = False
        if opened:
            return {"opened": True, "attachment_requested": True, "method": "macos-sharing"}
    # RFC mailto has no interoperable attachment parameter. Never pretend it does.
    uri = "mailto:" + SUPPORT_EMAIL + "?" + urlencode({"subject": subject, "body": body}, quote_via=quote)
    try:
        opened = bool(webbrowser.open(uri))
    except Exception:
        opened = False
    return {"opened": opened, "attachment_requested": False, "method": "mailto"}
