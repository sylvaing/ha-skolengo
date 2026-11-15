"""Tiny JSON:API document helper: resources and their side-loaded relationships."""

from __future__ import annotations

from typing import Any


class Document:
    """A JSON:API document with an index of the ``included`` resources."""

    def __init__(self, raw: dict[str, Any]) -> None:
        """Index the included resources by (type, id)."""
        self.raw = raw
        self._index: dict[tuple[str, str], dict[str, Any]] = {}
        for res in raw.get("included") or []:
            self._index[(res.get("type", ""), res.get("id", ""))] = res

    @property
    def data(self) -> list[dict[str, Any]]:
        """Primary data, always as a list."""
        data = self.raw.get("data")
        if data is None:
            return []
        return data if isinstance(data, list) else [data]

    @property
    def meta(self) -> dict[str, Any]:
        """Top-level meta."""
        return self.raw.get("meta") or {}

    @property
    def included(self) -> list[dict[str, Any]]:
        """Side-loaded resources."""
        return self.raw.get("included") or []

    def resolve(self, ref: dict[str, Any] | None) -> dict[str, Any] | None:
        """Resource of a ``{type, id}`` reference, from ``included`` (or the reference itself)."""
        if not ref:
            return None
        return self._index.get((ref.get("type", ""), ref.get("id", "")), ref)

    def related(self, resource: dict[str, Any], name: str) -> list[dict[str, Any]]:
        """Resolved resources of a relationship (empty when absent)."""
        rel = (resource.get("relationships") or {}).get(name) or {}
        data = rel.get("data")
        if data is None:
            return []
        refs = data if isinstance(data, list) else [data]
        return [r for r in (self.resolve(ref) for ref in refs) if r is not None]

    def related_one(self, resource: dict[str, Any], name: str) -> dict[str, Any] | None:
        """First resolved resource of a relationship."""
        found = self.related(resource, name)
        return found[0] if found else None


def attrs(resource: dict[str, Any] | None) -> dict[str, Any]:
    """Attributes of a resource (empty dict when missing)."""
    return (resource or {}).get("attributes") or {}
