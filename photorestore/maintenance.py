"""Explicit local cleanup. Never follows data-folder symlinks or touches source media."""

import logging
import shutil
from pathlib import Path
from .errors import AppError


def close_logs(root):
    root = root.resolve()
    for logger in logging.Logger.manager.loggerDict.copy().values():
        if not isinstance(logger, logging.Logger):
            continue
        for handler in list(logger.handlers):
            filename = getattr(handler, "baseFilename", None)
            if filename and Path(filename).resolve().is_relative_to(root):
                handler.close()
                logger.removeHandler(handler)


def clear_owned_data(root):
    """Caller holds application.lock for the full deletion and reinitialization."""
    if root.is_symlink():
        raise AppError("GPP-111")
    close_logs(root)
    try:
        for child in root.iterdir():
            if child.name == "application.lock":
                continue
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                shutil.rmtree(child)
    except OSError as exc:
        raise AppError("GPP-111") from exc
