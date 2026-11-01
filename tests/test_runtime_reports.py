import json
import zipfile
import pytest
from photorestore.errors import AppError
from photorestore.runtime import safe_extract, validate_url
from photorestore.diagnostics import diagnostics_bundle, export_report, logger_for, log_event


@pytest.mark.parametrize(
    "filename", ["../escape", "/absolute", "C:/escape", "nested/../../escape", "dir\\escape"]
)
def test_zip_traversal_rejected(tmp_path, filename):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(filename, "bad")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(AppError, match="GPP-406"):
        safe_extract(archive, dest)


def test_zip_symlink_escape_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        info = zipfile.ZipInfo("link")
        info.external_attr = 0o120777 << 16
        z.writestr(info, "../outside")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(AppError, match="GPP-406"):
        safe_extract(archive, dest)


@pytest.mark.parametrize(
    "url",
    ["http://cdn.playwright.dev/test", "https://evil.test/test", "https://cdn.playwright.dev.evil.test/test"],
)
def test_download_allowlist(url):
    with pytest.raises(AppError):
        validate_url(url)


def test_reports_redact_diagnostics_and_escape_csv(source, scan, store, tmp_path):
    (source / "=HYPERLINK(evil).jpg").write_bytes(b"one")
    scan(source)
    profile = store.path.parent
    logger = logger_for(profile / "logs")
    try:
        raise ValueError("SECRET COOKIE AND PRIVATE PATH")
    except ValueError as e:
        log_event(logger, "failure", "GPP-901", e)
    report = tmp_path / "report.csv"
    export_report(report, store)
    assert "'=HYPERLINK" in report.read_text("utf-8-sig")
    bundle = tmp_path / "bundle.zip"
    diagnostics_bundle(bundle, store, profile)
    with zipfile.ZipFile(bundle) as z:
        all_text = "".join(z.read(n).decode() for n in z.namelist())
    assert "SECRET COOKIE" not in all_text
    assert str(source) not in all_text
    assert "HYPERLINK" not in all_text
