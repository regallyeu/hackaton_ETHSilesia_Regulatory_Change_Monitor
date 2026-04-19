from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AlertAnchorRequest:
    """Request to store proof of alert integrity (hash of content/payload)."""

    alert_id: str
    content_hash: bytes

    def __post_init__(self) -> None:
        if not self.alert_id.strip():
            raise ValueError("alert_id cannot be empty")
        if len(self.content_hash) != 32:
            raise ValueError("content_hash must be 32 bytes (e.g. SHA-256)")


@dataclass(frozen=True)
class AnchorReceipt:
    """Normalized anchor result — independent of specific blockchain."""

    backend: str
    chain_id: str
    tx_reference: str
    block_number: int | None
    explorer_url: str | None
    extra: dict[str, Any]
