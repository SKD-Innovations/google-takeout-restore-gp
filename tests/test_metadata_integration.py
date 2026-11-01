import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock
import pytest
from PIL import Image
from photorestore.errors import AppError
from photorestore.metadata import apply_metadata, normalize, run_exiftool

DESCRIPTION = "Multilingual café 東京 हिंदी العربية 😀"
MULTILINE = (
    '  Multilingual café 東京\t"quoted" $HOME @person\r\n'
    "-execute\n-FileName=unexpected.jpg\n#[CSTR]-XMP:Description=overridden\n"
    "Literal backslashes: C:\\photos\\new and \\n; trailing spaces  "
)


@pytest.fixture
def tool_path():
    tool = os.environ.get("TAKEOUT_DEV_EXIFTOOL") or shutil.which("exiftool")
    if not tool:
        pytest.skip("ExifTool not installed in test environment")
    assert Path(tool).is_file(), "Configured ExifTool executable is missing"
    return Path(tool)


@pytest.mark.parametrize("suffix", [".jpg", ".png", ".tif"])
@pytest.mark.parametrize("description", [DESCRIPTION, MULTILINE], ids=["unicode", "multiline-argument-like"])
@pytest.mark.parametrize("unicode_path", [False, True], ids=["ascii-path", "unicode-path"])
def test_exiftool_readback_dates_description_gps(tool_path, tmp_path, suffix, description, unicode_path):
    directory = tmp_path / ("café 東京" if unicode_path else "photos")
    directory.mkdir()
    photo = directory / (("été 東京" if unicode_path else "test") + suffix)
    Image.new("RGB", (8, 8), "white").save(photo)
    data = normalize(
        {
            "photoTakenTime": {"timestamp": "946684800"},
            "description": description,
            "geoData": {"latitude": 0, "longitude": -12.5, "altitude": -20},
        }
    )
    apply_metadata(tool_path, photo, data)
    result = run_exiftool(tool_path, ["-j", "-n", str(photo.resolve())])
    meta = json.loads(result.stdout)[0]
    assert meta["DateTimeOriginal"].startswith("2000:01:01")
    assert meta["Description"] == description
    assert meta["GPSLatitude"] == 0
    assert meta["GPSLongitude"] == -12.5
    assert meta["GPSAltitude"] == -20
    assert photo.exists() and not (directory / "unexpected.jpg").exists()
    assert not (directory / (photo.name + "_original")).exists()
    assert not list(directory.glob(".takeout-metadata-*"))


def test_unicode_survives_windows_style_argv_code_page(tool_path, tmp_path, monkeypatch):
    """Reproduce legacy Windows argv loss while leaving UTF-8 stdin untouched."""
    actual_run = subprocess.run

    def legacy_argv(command, **kwargs):
        command = [
            command[0],
            *(arg.encode("cp1252", errors="replace").decode("cp1252") for arg in command[1:]),
        ]
        return actual_run(command, **kwargs)

    monkeypatch.setattr("photorestore.metadata.subprocess.run", legacy_argv)
    photo = tmp_path / "test.jpg"
    Image.new("RGB", (8, 8), "white").save(photo)
    apply_metadata(tool_path, photo, normalize({"description": DESCRIPTION}))
    result = run_exiftool(tool_path, ["-j", "-Description", str(photo.resolve())])
    assert json.loads(result.stdout)[0]["Description"] == DESCRIPTION


def test_description_uses_private_utf8_file_not_command_line(tmp_path, monkeypatch):
    tool, photo = tmp_path / "exiftool.exe", tmp_path / "test.jpg"
    tool.touch()
    value_files = []
    calls = []

    def process(command, **options):
        calls.append(command)
        assert command[1:3] == ["-config", ""]
        assert all(arg.isascii() for arg in command[1:])
        assert command[-2:] == ["-@", "-"]
        assert options["capture_output"] is True and "shell" not in options
        arguments = options["input"].decode("utf-8").splitlines()
        if "-j" not in arguments:
            value = next(arg.split("<=", 1)[1] for arg in arguments if arg.startswith("-XMP:Description<="))
            value_file = Path(value)
            value_files.append(value_file)
            assert value_file.read_bytes() == MULTILINE.encode("utf-8")
            assert b"\n-execute\n" not in options["input"]
            assert MULTILINE.encode("utf-8") not in options["input"]
            stdout = b"1 image files updated"
        else:
            stdout = json.dumps([{"Description": MULTILINE}]).encode("utf-8")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr("photorestore.metadata.subprocess.run", process)
    apply_metadata(tool, photo, normalize({"description": MULTILINE}))
    assert len(calls) == 2
    assert value_files and all(not path.exists() for path in value_files)
    assert not list(tmp_path.glob(".takeout-metadata-*"))


def test_description_mismatch_is_still_an_error(tmp_path, monkeypatch):
    tool, photo = tmp_path / "exiftool.exe", tmp_path / "test.jpg"
    tool.touch()
    runner = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 0, stdout=b"1 image files updated", stderr=b""),
            subprocess.CompletedProcess([], 0, stdout=b'[{"Description":"corrupted"}]', stderr=b""),
        ]
    )
    monkeypatch.setattr("photorestore.metadata.subprocess.run", runner)
    with pytest.raises(AppError, match="GPP-302"):
        apply_metadata(tool, photo, normalize({"description": DESCRIPTION}))
    assert not list(tmp_path.glob(".takeout-metadata-*"))


def test_description_larger_than_windows_command_line(tool_path, tmp_path):
    description = "café 東京 " * 5000
    assert len(description) > 32767
    photo = tmp_path / "long-description.png"
    Image.new("RGB", (8, 8), "white").save(photo)
    apply_metadata(tool_path, photo, normalize({"description": description}))
    result = run_exiftool(tool_path, ["-j", "-Description", str(photo.resolve())])
    assert json.loads(result.stdout)[0]["Description"] == description


@pytest.mark.skipif(os.name == "nt", reason="Windows filenames cannot contain newlines")
def test_posix_newline_filename_remains_one_argument(tool_path, tmp_path):
    photo = tmp_path / "café 東京\n$HOME @photo.jpg"
    Image.new("RGB", (8, 8), "white").save(photo)
    apply_metadata(tool_path, photo, normalize({"description": MULTILINE}))
    result = run_exiftool(tool_path, ["-j", "-Description", str(photo.resolve())])
    assert json.loads(result.stdout)[0]["Description"] == MULTILINE
