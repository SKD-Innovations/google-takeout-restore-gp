import os
import shutil
from pathlib import Path
import subprocess
import json
import pytest
from PIL import Image
from photorestore.metadata import apply_metadata, normalize


@pytest.mark.parametrize("suffix", [".jpg", ".png", ".tif"])
def test_exiftool_readback_dates_description_gps(tmp_path, suffix):
    tool = os.environ.get("TAKEOUT_DEV_EXIFTOOL") or shutil.which("exiftool")
    if not tool:
        pytest.skip("ExifTool not installed in test environment")
    photo = tmp_path / ("test" + suffix)
    Image.new("RGB", (8, 8), "white").save(photo)
    data = normalize(
        {
            "photoTakenTime": {"timestamp": "946684800"},
            "description": "Multilingual café 東京",
            "geoData": {"latitude": 0, "longitude": -12.5, "altitude": -20},
        }
    )
    apply_metadata(Path(tool), photo, data)
    result = subprocess.run([tool, "-config", "", "-j", "-n", str(photo)], capture_output=True, check=True)
    meta = json.loads(result.stdout)[0]
    assert meta["DateTimeOriginal"].startswith("2000:01:01")
    assert meta["Description"] == "Multilingual café 東京"
    assert meta["GPSLongitude"] == -12.5
    assert meta["GPSAltitude"] == -20
