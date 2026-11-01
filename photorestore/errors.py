"""Stable public errors. Raw exceptions, URLs and source paths never enter logs."""

CATALOG = {
    "GPP-101": ("Check your settings", "One or more settings is invalid. Review the values and try again."),
    "GPP-102": ("Sign in required", "Sign in to your local account to continue."),
    "GPP-103": ("Access denied", "This action requires an administrator account."),
    "GPP-104": ("Sign-in failed", "Check your username and password, or ask your administrator for a reset."),
    "GPP-105": ("Please wait", "Too many sign-in attempts. Wait before trying again."),
    "GPP-106": ("Action unavailable", "Pause the current operation and wait for it to finish first."),
    "GPP-107": ("Account cannot be changed", "Keep an active administrator. Usernames must be unique."),
    "GPP-108": ("Password too short", "Use a password of 12 to 256 characters."),
    "GPP-109": (
        "Recovery failed",
        "Check the username and recovery key. Disabled accounts need an administrator.",
    ),
    "GPP-110": (
        "Device verification required",
        "Device verification was cancelled or unavailable. Nothing was removed.",
    ),
    "GPP-111": (
        "Cleanup incomplete",
        "Some local files could not be removed. Close the dedicated Chrome window and retry. Your source files and Google Photos were not changed.",
    ),
    "GPP-112": (
        "Uninstall unavailable",
        "Run the installed app from Applications to uninstall it. On Windows or Linux, clear app data here, then use your operating system’s app manager.",
    ),
    "GPP-201": ("Source unavailable", "Reconnect the source drive and check that the folder is readable."),
    "GPP-202": (
        "Source changed",
        "This file changed after scanning. Scan the folder again before uploading.",
    ),
    "GPP-203": ("File exceeds limits", "This item exceeds the configured Google Photos size or pixel limit."),
    "GPP-204": (
        "Not enough working space",
        "Free disk space. Staging needs up to three times the file size plus 512 MB.",
    ),
    "GPP-205": (
        "Unsafe source path",
        "Symbolic links and files outside the selected folder are not followed.",
    ),
    "GPP-206": (
        "Duplicate content",
        "An identical item is already recorded in this account. No upload was attempted.",
    ),
    "GPP-207": ("Skipped by your rules", "This item was excluded by your edited-copy preference."),
    "GPP-208": (
        "Scan incomplete",
        "Some source files could not be read. Reconnect the drive and scan again.",
    ),
    "GPP-301": (
        "Metadata needs review",
        "A sidecar is malformed or ambiguous. Correct it and rescan this folder.",
    ),
    "GPP-302": (
        "Metadata could not be written",
        "ExifTool could not safely write the requested tags. The original is unchanged.",
    ),
    "GPP-303": (
        "ExifTool unavailable",
        "The bundled metadata component is missing or damaged. Reinstall the application.",
    ),
    "GPP-304": (
        "Additional restoration needed",
        "Album, favorite, archive or paired-photo intent was saved in the report; Google restoration needs review.",
    ),
    "GPP-401": ("Google sign-in required", "Open the Google sign-in window and complete sign-in there."),
    "GPP-402": (
        "Google Photos changed",
        "The expected upload controls were not found. Run the connection check; no upload was confirmed.",
    ),
    "GPP-403": (
        "Upload outcome unknown",
        "Check Google Photos before retrying. Retrying may create a duplicate.",
    ),
    "GPP-404": (
        "Google rejected this item",
        "Review the file type, available Google storage and the message in the browser.",
    ),
    "GPP-405": ("Browser component unavailable", "Install the browser component in Setup, then try again."),
    "GPP-406": (
        "Download verification failed",
        "The downloaded component did not match the release checksum. Nothing was installed.",
    ),
    "GPP-407": (
        "Connection interrupted",
        "Check your connection. Uploads with uncertain outcomes require review.",
    ),
    "GPP-408": (
        "Google session damaged",
        "The saved session could not be decrypted. Disconnect Google and sign in again.",
    ),
    "GPP-409": (
        "Wrong Google account",
        "The Google account does not match this queue. Reconnect the original account.",
    ),
    "GPP-410": (
        "Google blocked automated sign-in",
        "Google rejected this app-controlled browser. Repeating sign-in may give the same result. "
        "Close this connection and sign in manually in the dedicated Chrome window before clicking Continue. "
        "If Google still blocks that window, this browser flow cannot authorize your account.",
    ),
    "GPP-411": (
        "Chrome connection unavailable",
        "Install or update Google Chrome, close the dedicated restore browser window and try again.",
    ),
    "GPP-412": (
        "Chrome profile could not be saved",
        "Your queue is preserved, but you may need to sign in again. Check free disk space.",
    ),
    "GPP-413": (
        "Previous Chrome window is still open",
        "Close the dedicated Takeout Restore Chrome window left by the previous app session, then reopen the app.",
    ),
    "GPP-414": (
        "Original quality could not be confirmed",
        "The backup-quality dialog could not be safely set to Original quality. "
        "The operation stopped. Select Original quality in Google Photos and review the current item before retrying.",
    ),
    "GPP-415": (
        "No items ready to upload",
        "Open Queue to review unresolved items or retry failed items. Nothing was submitted by this attempt. Items with uncertain outcomes are held for review.",
    ),
    "GPP-501": (
        "Local database unavailable",
        "Close other copies of the app and check disk space. Do not delete the database.",
    ),
    "GPP-502": (
        "Audit integrity check failed",
        "The audit chain has changed. Preserve the data folder and investigate before continuing.",
    ),
    "GPP-503": ("Unsupported database version", "Use a newer application version to open this data folder."),
    "GPP-901": (
        "Unexpected application error",
        "The operation stopped safely. Export a diagnostic bundle from Logs.",
    ),
}


class AppError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

    def public(self):
        title, message = CATALOG[self.code]
        return {"code": self.code, "title": title, "message": message}
