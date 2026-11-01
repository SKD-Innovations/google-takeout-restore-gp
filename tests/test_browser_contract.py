import re
import threading
from contextlib import contextmanager
from pathlib import Path
import pytest
from photorestore.browser import GoogleBrowser, SUCCESS_TEXT
from photorestore.errors import AppError


class Locator:
    def __init__(self, values):
        self.values = values

    def count(self):
        return len(self.values)

    def nth(self, index):
        return Locator([self.values[index]])

    @property
    def first(self):
        return self.nth(0)

    def is_visible(self):
        return bool(self.values)

    def inner_text(self):
        return self.values[0]

    def get_attribute(self, _):
        return "Upload"

    def click(self):
        pass


class Page:
    url = "https://photos.google.com/"

    def __init__(self, outcome, stale=False):
        self.outcome, self.submitted, self.stale = outcome, False, stale

    def get_by_text(self, pattern):
        text = self.outcome if self.submitted or self.stale else ""
        return Locator([text] if pattern.search(text) else [])

    def locator(self, selector):
        if 'role="dialog"' in selector:
            return Locator([])
        return Locator(["Upload"])

    @contextmanager
    def expect_file_chooser(self, **kwargs):
        class Chooser:
            value = self

        yield Chooser()

    def set_files(self, *args, **kwargs):
        self.submitted = True

    def wait_for_timeout(self, _):
        pass


@pytest.mark.parametrize(
    "message", ["No items uploaded", "0 items uploaded", "Add to album", "2 items uploaded"]
)
def test_non_confirmation_is_not_success(message):
    assert not SUCCESS_TEXT.fullmatch(message)


@pytest.mark.parametrize("message,code", [("Can't upload", "GPP-404"), ("No items uploaded", "GPP-403")])
def test_upload_failure_does_not_become_success(message, code):
    browser = GoogleBrowser(None, Path("."), None, None, threading.Event())
    browser.page = Page(message)
    browser.self_test = lambda: None
    marks = []
    with pytest.raises(AppError, match=code):
        browser.upload(Path("test.jpg"), 5, lambda: marks.append("submitted"))
    assert marks == ["submitted"]


def test_stale_success_prevents_submission():
    browser = GoogleBrowser(None, Path("."), None, None, threading.Event())
    browser.page = Page("Upload complete", True)
    browser.self_test = lambda: None
    marks = []
    with pytest.raises(AppError, match="GPP-402"):
        browser.upload(Path("test.jpg"), 5, lambda: marks.append("submitted"))
    assert marks == []


def test_submission_is_persisted_before_file_assignment():
    browser = GoogleBrowser(None, Path("."), None, None, threading.Event())
    browser.page = Page("1 item backed up")
    browser.self_test = lambda: None

    def mark():
        assert not browser.page.submitted

    result = browser.upload(Path("test.jpg"), 5, mark)
    assert result["kind"] == "browser_confirmation"


@pytest.mark.parametrize(
    "message",
    [
        "This browser or app may not be secure.",
        "This browser may not be secure",
        "This browser or app may\nnot be secure.",
    ],
)
def test_google_rejection_stops_login_immediately(message):
    class RejectedPage:
        url = "https://accounts.google.com/signin/rejected"

        def get_by_text(self, pattern):
            return Locator([message] if pattern.search(message) else [])

        def wait_for_timeout(self, _):
            raise AssertionError("Must not wait after a definitive rejection")

    browser = GoogleBrowser(None, Path("."), None, None, threading.Event())
    browser.page = RejectedPage()
    browser.navigate = lambda: None
    browser.save_session = lambda: pytest.fail("Rejected login must not save credentials")
    browser.bind_identity = lambda _: pytest.fail("Rejected login must not bind an account")
    with pytest.raises(AppError, match="GPP-410"):
        browser.login(lambda *args: None)


def test_photo_caption_cannot_trigger_login_rejection():
    class PhotosPage:
        url = "https://photos.google.com/"

        def get_by_text(self, _):
            pytest.fail("Must not inspect photo captions for sign-in errors")

    browser = GoogleBrowser(None, Path("."), None, None, threading.Event())
    browser.page = PhotosPage()
    browser.check_signin_block()


@pytest.mark.parametrize(
    "text",
    [
        "You backed up 1 item",
        "You backed up 1\nitem",
        "You\u00a0backed up 1 item",
        " You backed up 1 item. ",
        "1 item backed up",
        "Upload complete",
    ],
)
def test_single_item_confirmation_wording(text):
    assert SUCCESS_TEXT.fullmatch(text)


@pytest.mark.parametrize(
    "text",
    [
        "You backed up 2 items",
        "You backed up 10 items",
        "No items uploaded",
        "You backed up 0 items",
        "Not yet: You backed up 1 item",
    ],
)
def test_other_counts_and_unconfirmed_text_do_not_confirm_single_upload(text):
    assert not SUCCESS_TEXT.fullmatch(text)


@pytest.mark.parametrize("text", ["You backed up 1 item", "You backed up 1\nitem"])
def test_new_confirmation_text_cannot_be_reused_before_submission(text):
    browser = GoogleBrowser(None, Path("."), None, None, threading.Event())
    browser.page = Page(text, True)
    browser.self_test = lambda: None
    with pytest.raises(AppError, match="GPP-402"):
        browser.upload(Path("test.jpg"), 5, lambda: pytest.fail("Stale card must not submit a file"))
