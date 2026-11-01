"""Real DOM tests for the backup-quality prompt, including native and custom radios."""

import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from photorestore.browser import GoogleBrowser
from photorestore.chrome import installed_chrome
from photorestore.errors import AppError


@pytest.fixture(scope="module")
def chrome():
    with sync_playwright() as pw:
        executable = installed_chrome() or Path(pw.chromium.executable_path)
        if not executable.is_file():
            pytest.skip("Install Chrome or the Playwright browser to run DOM tests")
        browser = pw.chromium.launch(executable_path=str(executable), headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(chrome):
    context = chrome.new_context()
    page = context.new_page()
    page.route(
        "**/*", lambda route: route.fulfill(status=200, content_type="text/html", body="<body></body>")
    )
    page.goto("https://photos.google.com/")
    yield page
    context.close()


def adapter(page):
    browser = GoogleBrowser(None, Path("."), None, None, threading.Event())
    browser.page = page
    return browser


def dialog(selected="saver", title="Choose your backup quality", original="Original quality"):
    return f"""<div role="dialog"><h2>{title}</h2>
      <label><input type="radio" name="quality" value="original" {"checked" if selected == "original" else ""}>{original}</label>
      <label><input type="radio" name="quality" value="saver" {"checked" if selected == "saver" else ""}>Storage saver</label>
      <button onclick="window.saved=document.querySelector('input:checked').value; this.parentElement.remove()">Continue</button>
    </div>"""


@pytest.mark.parametrize("selected", ["saver", "original"])
def test_native_radio_always_confirms_original(page, selected):
    page.set_content(dialog(selected))
    assert adapter(page).handle_quality_prompt()
    assert page.evaluate("window.saved") == "original"
    assert page.get_by_role("dialog").count() == 0


def test_custom_aria_radio_is_selected_before_continue(page):
    page.set_content("""<section aria-modal="true"><h2>Choose your backup quality</h2>
      <div role="radio" aria-checked="false" tabindex="0" onclick="this.setAttribute('aria-checked','true');document.querySelector('#saver').setAttribute('aria-checked','false')">Original quality<br>Store photos &amp; videos with no change to their quality</div>
      <div role="radio" aria-checked="true" id="saver">Storage saver</div>
      <button onclick="window.saved=document.querySelector('[role=radio]').getAttribute('aria-checked');this.parentElement.remove()">Continue</button>
    </section>""")
    assert adapter(page).handle_quality_prompt()
    assert page.evaluate("window.saved") == "true"


def test_other_continue_dialog_is_not_accepted(page):
    page.set_content(dialog(title="Delete your photos?"))
    assert not adapter(page).handle_quality_prompt()
    assert page.get_by_role("dialog").is_visible()
    assert page.evaluate("window.saved") is None


def test_missing_original_option_stops_without_continuing(page):
    page.set_content(dialog(original="Compressed quality"))
    with pytest.raises(AppError, match="GPP-414"):
        adapter(page).handle_quality_prompt()
    assert page.evaluate("window.saved") is None


def test_radio_that_does_not_keep_selection_stops_without_continuing(page):
    page.set_content(dialog().replace('value="original"', 'value="original" onclick="this.checked=false"'))
    with pytest.raises(AppError, match="GPP-414"):
        adapter(page).handle_quality_prompt()
    assert page.evaluate("window.saved") is None


def test_hidden_stale_quality_dialog_is_ignored(page):
    page.set_content(dialog().replace('role="dialog"', 'role="dialog" hidden'))
    assert not adapter(page).handle_quality_prompt()
    assert page.evaluate("window.saved") is None


def test_repeated_dialogs_are_handled_on_later_uploads(page):
    browser = adapter(page)
    for _ in range(2):
        page.set_content(dialog())
        assert browser.handle_quality_prompt()
        assert page.evaluate("window.saved") == "original"


@pytest.mark.parametrize("delay_ms", [0, 150])
def test_upload_loop_handles_quality_dialog_before_completion(page, tmp_path, delay_ms):

    prompt = dialog().replace(
        "this.parentElement.remove()",
        "this.parentElement.remove();document.body.insertAdjacentHTML('beforeend','<div role=status>1 item backed up</div>')",
    )
    page.set_content("""<button aria-label="Upload" onclick="document.querySelector('input').click()">Upload</button>
      <input type="file" hidden>""")
    page.evaluate(
        """({prompt,delay}) => {
        document.querySelector('input').onchange=()=>setTimeout(
          ()=>document.body.insertAdjacentHTML('beforeend',prompt),delay);
    }""",
        {"prompt": prompt, "delay": delay_ms},
    )
    source = tmp_path / "fixture.jpg"
    source.write_bytes(b"Offline test fixture; never uploaded to a server")
    browser = adapter(page)
    browser.self_test = lambda: None
    submitted = []
    receipt = browser.upload(source, 5, lambda: submitted.append(True))
    assert submitted == [True]
    assert receipt["kind"] == "browser_confirmation"
    assert page.evaluate("window.saved") == "original"


def test_google_confirmation_card_commits_and_advances_two_items(page, tmp_path, store):
    from photorestore.scanner import Scanner
    from photorestore.settings import Settings
    from photorestore.engine import UploadEngine

    source = tmp_path / "source"
    source.mkdir()
    (source / "a.jpg").write_bytes(b"first fixture")
    (source / "b.jpg").write_bytes(b"second fixture")
    Scanner(store, "test", Settings()).scan(source)
    page.set_content("""<button aria-label="Upload" onclick="document.querySelector('input').click()">Upload</button>
      <input type="file" hidden>
      <script>
      window.closedCards=0;
      document.querySelector('input').onchange=()=>{
        document.body.insertAdjacentHTML('beforeend',`<div data-card>
          <h2>You backed up 1 <span>item</span></h2>
          <button>Add to album</button>
          <button aria-label="Close" onclick="window.closedCards++;setTimeout(()=>this.parentElement.remove(),40)">×</button>
        </div>`);
      };
      </script>""")
    browser = adapter(page)
    browser.self_test = lambda: None
    dismiss = browser.dismiss_confirmation
    commits = []

    def after_commit():
        with store.connect() as con:
            commits.append(con.execute("SELECT COUNT(*) FROM items WHERE status='uploaded'").fetchone()[0])
        dismiss()

    browser.dismiss_confirmation = after_commit
    engine = UploadEngine(
        store,
        "test",
        Settings(),
        store.path.parent,
        tmp_path / "unused-tool",
        threading.Event(),
        lambda *a: None,
    )
    assert engine.run(browser) == 2
    assert commits == [1, 2]
    assert page.evaluate("window.closedCards") == 2
    with store.connect() as con:
        rows = con.execute("SELECT status,receipt FROM items ORDER BY id").fetchall()
    assert all(row["status"] == "uploaded" for row in rows)
    import json

    assert all(json.loads(row["receipt"])["evidence"] == "You backed up 1 item" for row in rows)


def test_confirmation_close_never_clicks_unrelated_global_close(page):
    page.set_content("""<button aria-label="Close" onclick="window.wrongClose=true">Unrelated close</button>
        <div><h2>You backed up 1 item</h2><button>Add to album</button></div>""")
    browser = adapter(page)
    browser._confirmation = page.get_by_text("You backed up 1 item", exact=True)
    browser.dismiss_confirmation()
    assert page.evaluate("window.wrongClose") is None
