"""Keep desktop acceptance tests away from real user preferences and recovery."""
import pytest


@pytest.fixture(autouse=True)
def isolated_application_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACERTOOL_STATE_DIR", str(tmp_path / "application-state"))
