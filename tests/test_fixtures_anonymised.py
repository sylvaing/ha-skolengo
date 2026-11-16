"""Guard: the recorded fixtures must stay anonymised."""

from __future__ import annotations

import re

import pytest

from .helpers import FIXTURES

# Real values seen while recording the fixtures must never come back (case-insensitive, word match).
FORBIDDEN = re.compile(
    r"\b(garcia|gabin|owen|sylvain|billeres|billères|monentoccitanie|toulo)\b|@(?!example\.)[a-z0-9-]+\.[a-z]{2,}",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", sorted(p for p in FIXTURES.iterdir() if p.is_file()), ids=lambda p: p.name)
def test_fixture_is_anonymised(path) -> None:
    """No real name, school, ENT or e-mail address in the fixture."""
    match = FORBIDDEN.search(path.read_text(encoding="utf-8"))
    assert match is None, f"{path.name}: {match.group(0)!r}"
