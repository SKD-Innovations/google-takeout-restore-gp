import threading
import pytest
from photorestore.store import Store
from photorestore.settings import Settings
from photorestore.scanner import Scanner


@pytest.fixture
def store(tmp_path):
    db = Store(tmp_path / "profile" / "library.sqlite")
    db.initialize(profile=True)
    return db


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    return folder


@pytest.fixture
def scan(store):
    def run(source, **kwargs):
        return Scanner(store, "test-user", Settings(**kwargs), threading.Event()).scan(source)

    return run
