import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import Job  # noqa: E402

TODAY = date(2026, 10, 18)


def make_job(**kw) -> Job:
    base = dict(source="test", external_id="1", title="Senior .NET Developer", company="XYZ Fintech",
                location="İstanbul", work_model="hibrit", url="https://example.com/ilan/1")
    base.update(kw)
    return Job(**base)


@pytest.fixture
def today() -> date:
    return TODAY


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (str(json_data) if json_data is not None else "")
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


@pytest.fixture(autouse=True)
def _not_in_github_actions(monkeypatch):
    """CI sets GITHUB_ACTIONS=true, which turns on ::notice/::warning output; keep tests hermetic."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
