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
    from app.extensions.mascot_chat import reset_chat_rate_limits
    from app.extensions.packs import invalidate_pack_cache
    from app.main import app
    from app.submissions import reset_submission_rate_limits

    auth._failed.clear()
    reset_chat_rate_limits()
    reset_submission_rate_limits()
    invalidate_pack_cache()

    data = Path(os.environ["DATA_DIR"])
    store._engine = None
    store._factory = None
    store._current = None
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True, exist_ok=True)
    store.init(app.state.config)
    yield
    reset_chat_rate_limits()
    reset_submission_rate_limits()
    invalidate_pack_cache()
