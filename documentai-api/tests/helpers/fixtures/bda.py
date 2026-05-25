import json

import pytest

_TEST_PROJECT_ARNS = json.dumps(
    {
        "income": "arn:aws:bedrock:us-east-1:123:project/a",
        "expenses": "arn:aws:bedrock:us-east-1:123:project/b",
        "identity": "arn:aws:bedrock:us-east-1:123:project/c",
        "employment": "arn:aws:bedrock:us-east-1:123:project/d",
        "training": "arn:aws:bedrock:us-east-1:123:project/e",
    }
)


@pytest.fixture
def bda_project_arns(monkeypatch):
    """Set BDA_PROJECT_ARNS env var for tests that need document categories."""
    monkeypatch.setenv("BDA_PROJECT_ARNS", _TEST_PROJECT_ARNS)
