"""
In-memory SessionAsset repository.

Mirrors every other repository in this package: a dict behind the port, one
shared instance wired in the composition root. A session holds at most ONE
asset per kind — uploading a new photograph replaces the previous one — so the
key is (session_id, kind) rather than an asset id.
"""

import threading

from app.domain.form_assets import AssetKind, SessionAsset
from app.domain.repositories import SessionAssetRepository


class InMemorySessionAssetRepository(SessionAssetRepository):
    """Thread-safe dict store keyed by (session_id, kind)."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, AssetKind], SessionAsset] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str, kind: AssetKind) -> SessionAsset | None:
        with self._lock:
            return self._items.get((session_id, kind))

    def save(self, asset: SessionAsset) -> None:
        with self._lock:
            self._items[(asset.session_id, asset.kind)] = asset

    def delete(self, session_id: str, kind: AssetKind) -> SessionAsset | None:
        with self._lock:
            return self._items.pop((session_id, kind), None)

    def list_for_session(self, session_id: str) -> tuple[SessionAsset, ...]:
        with self._lock:
            return tuple(
                asset
                for (sid, _), asset in self._items.items()
                if sid == session_id
            )
