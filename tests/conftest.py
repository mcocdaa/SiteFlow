import os
import shutil
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="siteflow-test-data-"))
os.environ.setdefault("COOKIE_SECURE", "false")


@pytest.fixture(autouse=True)
def clean_data():
    from app import auth, store
    from app.main import app

    auth._failed.clear()

    data = Path(os.environ["DATA_DIR"])
    store._engine = None
    store._factory = None
    store._current = None
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True, exist_ok=True)
    store.init(app.state.config)
    yield
