from dataclasses import asdict, dataclass
from .errors import AppError

CHOICES = {
    "edited": ("both", "skip", "only_edited"),
    "duplicates": ("hash", "name_size", "all"),
    "pairs": ("together", "separate"),
    "albums": ("recreate", "ignore"),
    "favorites": ("carry", "ignore"),
    "archive": ("carry", "ignore"),
    "descriptions": ("carry", "ignore"),
    "oversize": ("skip", "try"),
}


@dataclass(frozen=True)
class Settings:
    edited: str = "both"
    duplicates: str = "hash"
    pairs: str = "together"
    albums: str = "recreate"
    favorites: str = "carry"
    archive: str = "carry"
    descriptions: str = "carry"
    oversize: str = "skip"
    scratch_gb: int = 32
    retry_limit: int = 3
    upload_timeout_minutes: int = 180
    auto_lock_minutes: int = 15
    advanced: bool = False

    @classmethod
    def parse(cls, values):
        if not isinstance(values, dict) or set(values) - set(asdict(cls())):
            raise AppError("GPP-101")
        s = cls(**values)
        for name, allowed in CHOICES.items():
            if getattr(s, name) not in allowed:
                raise AppError("GPP-101")
        for name, low, high in (
            ("scratch_gb", 1, 1024),
            ("retry_limit", 1, 10),
            ("upload_timeout_minutes", 5, 1440),
            ("auto_lock_minutes", 1, 240),
        ):
            if type(getattr(s, name)) is not int or not low <= getattr(s, name) <= high:
                raise AppError("GPP-101")
        if type(s.advanced) is not bool:
            raise AppError("GPP-101")
        return s
