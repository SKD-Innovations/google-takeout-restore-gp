"""Strict sidecar parsing and copy-only ExifTool edits."""

import json
import math
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from .errors import AppError

PHOTOS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".gif", ".tif", ".tiff", ".dng", ".avif"}
VIDEOS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".3gp",
    ".3g2",
    ".mkv",
    ".mts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".wmv",
    ".webm",
}
SUPPORTED = PHOTOS | VIDEOS
MAX_JSON = 4 * 1024 * 1024
EDITED = re.compile(r"(?:-edited| - edited|_edited)$", re.I)


def read_sidecar(path):
    if path.is_symlink():
        raise AppError("GPP-205")
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise ValueError()
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (OSError, ValueError, UnicodeError) as exc:
        raise AppError("GPP-301") from exc


def normalize(data):
    """Preserve cloud-only intent separately; never invent a date from export time."""
    result = {}
    try:
        title = data.get("title")
        if title is not None:
            if not isinstance(title, str) or len(title) > 4096:
                raise ValueError()
            result["title"] = title
        stamp = data.get("photoTakenTime", {}).get("timestamp")
        if stamp is not None:
            if isinstance(stamp, bool) or not isinstance(stamp, (str, int)):
                raise ValueError()
            result["taken"] = datetime.fromtimestamp(int(stamp), timezone.utc).isoformat()
        desc = data.get("description", "")
        if not isinstance(desc, str) or len(desc) > 100000 or "\x00" in desc:
            raise ValueError()
        if desc:
            result["description"] = desc
        for candidate in ("geoDataExif", "geoData"):
            geo = data.get(candidate) or {}
            if not isinstance(geo, dict):
                raise ValueError()
            if "latitude" in geo and "longitude" in geo:
                lat, lon, alt = (float(geo.get(k, 0)) for k in ("latitude", "longitude", "altitude"))
                if (
                    not all(math.isfinite(x) for x in (lat, lon, alt))
                    or not -90 <= lat <= 90
                    or not -180 <= lon <= 180
                ):
                    raise ValueError()
                # Takeout commonly emits (0,0,0) for missing coordinates.
                if lat != 0 or lon != 0 or alt != 0:
                    result["geo"] = {"lat": lat, "lon": lon, "alt": alt}
                    break
        for key in ("favorited", "archived"):
            if key in data:
                if not isinstance(data[key], bool):
                    raise ValueError()
                result[key] = data[key]
        return result
    except (ValueError, TypeError, OverflowError, OSError, AttributeError) as exc:
        raise AppError("GPP-301") from exc


def candidates(media):
    name, stem, suffix = media.name, media.stem, media.suffix
    names = [
        name + ".supplemental-metadata.json",
        name + ".json",
        stem + ".supplemental-metadata.json",
        stem + ".json",
    ]
    match = re.fullmatch(r"(.*?)\s*\((\d+)\)", stem)
    if match:
        base, number = match.groups()
        for gap in ("", " "):
            names.extend(
                [
                    f"{base}{suffix}.supplemental-metadata{gap}({number}).json",
                    f"{base}{suffix}{gap}({number}).json",
                ]
            )
    return [str(media.parent / n) for n in names]


def resolve_metadata(con, media):
    # Exact naming beats title lookup. Never use a heuristic common-prefix match.
    for name in candidates(media):
        row = con.execute("SELECT * FROM sidecars WHERE path=?", (name,)).fetchone()
        if row:
            if row["invalid"]:
                raise AppError("GPP-301")
            return json.loads(row["data"])
    rows = con.execute(
        "SELECT data,invalid FROM sidecars WHERE directory=? AND title=? LIMIT 2",
        (str(media.parent), media.name),
    ).fetchall()
    if len(rows) > 1 or (rows and rows[0]["invalid"]):
        raise AppError("GPP-301")
    return json.loads(rows[0]["data"]) if rows else None


def clean_environment():
    return {k: v for k, v in os.environ.items() if not k.startswith("PERL")}


def exiftool_command(tool):
    interpreter = tool.parent / "perl" / "bin" / "perl"
    if interpreter.is_file():
        lib = interpreter.parent.parent / "lib"
        includes = []
        for version in sorted(lib.iterdir()):
            if version.is_dir():
                includes += ["-I", str(version)]
                includes += [
                    part
                    for sub in sorted(version.iterdir())
                    if sub.is_dir() and (sub / "Config.pm").is_file()
                    for part in ["-I", str(sub)]
                ]
        return [str(interpreter), *includes, str(tool)]
    return [str(tool)]


def apply_metadata(tool: Path, staged: Path, meta, descriptions=True):
    if not meta:
        return
    if not tool.is_file():
        raise AppError("GPP-303")
    # -config must be first: do not execute a user-provided ExifTool config.
    args = [*exiftool_command(tool), "-config", "", "-overwrite_original", "-P", "-api", "QuickTimeUTC=1"]
    tags = []
    if meta.get("taken"):
        dt = datetime.fromisoformat(meta["taken"]).astimezone(timezone.utc)
        date = dt.strftime("%Y:%m:%d %H:%M:%S")
        tags += [
            f"-EXIF:DateTimeOriginal={date}",
            f"-EXIF:CreateDate={date}",
            "-EXIF:OffsetTimeOriginal=+00:00",
            "-EXIF:OffsetTimeDigitized=+00:00",
            f"-XMP:DateCreated={date}+00:00",
            f"-XMP:CreateDate={date}+00:00",
        ]
        if staged.suffix.lower() in VIDEOS:
            tags += [
                f"-QuickTime:CreateDate={date}",
                f"-QuickTime:ModifyDate={date}",
                f"-QuickTime:TrackCreateDate={date}",
                f"-QuickTime:MediaCreateDate={date}",
                f"-Keys:CreationDate={date}+00:00",
            ]
    geo = meta.get("geo")
    if geo:
        lat, lon, alt = geo["lat"], geo["lon"], geo["alt"]
        tags += [
            f"-GPSLatitude={abs(lat)}",
            f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
            f"-GPSLongitude={abs(lon)}",
            f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
            f"-GPSAltitude={abs(alt)}",
            f"-GPSAltitudeRef#={0 if alt >= 0 else 1}",
        ]
        if staged.suffix.lower() in VIDEOS:
            tags += [f"-Keys:GPSCoordinates={lat:+.7f}{lon:+.7f}{alt:+.2f}/"]
    if descriptions and meta.get("description"):
        tags += [f"-XMP:Description={meta['description']}"]
        if staged.suffix.lower() in {".jpg", ".jpeg", ".tif", ".tiff"}:
            tags += [f"-EXIF:ImageDescription={meta['description']}"]
    if not tags:
        return
    try:
        result = subprocess.run(  # noqa: S603 -- trusted bundled executable, argument vector
            args + tags + [str(staged.resolve())],
            capture_output=True,  # noqa: S603 -- trusted bundled executable, argument vector
            timeout=600,
            check=False,
            env=clean_environment(),
        )  # noqa: S603
        if result.returncode or b"1 image files updated" not in result.stdout:
            raise AppError("GPP-302")
        # Read back requested dates/descriptions. A successful subprocess alone is insufficient.
        readback = subprocess.run(  # noqa: S603 -- trusted bundled executable, argument vector
            [
                *exiftool_command(tool),
                "-config",
                "",
                "-j",
                "-n",
                "-api",
                "QuickTimeUTC=1",  # noqa: S603
                "-DateTimeOriginal",
                "-CreateDate",
                "-Description",
                "-GPSLatitude",
                "-GPSLongitude",
                "-GPSAltitude",
                "-GPSCoordinates",
                str(staged.resolve()),
            ],
            capture_output=True,
            timeout=60,
            check=True,
            env=clean_environment(),
        )  # noqa: S603
        actual = json.loads(readback.stdout)[0]
        if meta.get("taken") and not any(
            str(actual.get(k, "")).startswith(date) for k in ("DateTimeOriginal", "CreateDate")
        ):
            raise AppError("GPP-302")
        if geo and staged.suffix.lower() not in VIDEOS:
            if any(
                abs(float(actual.get(tag, 999)) - geo[key]) > 0.0001
                for tag, key in [("GPSLatitude", "lat"), ("GPSLongitude", "lon"), ("GPSAltitude", "alt")]
            ):
                raise AppError("GPP-302")
        if descriptions and meta.get("description") and actual.get("Description") != meta["description"]:
            raise AppError("GPP-302")
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, AttributeError, KeyError) as exc:
        raise AppError("GPP-302") from exc
