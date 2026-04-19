from __future__ import annotations

from typing import Protocol

from blockchain.anchors.models import AlertAnchorRequest, AnchorReceipt


class AnchorBackend(Protocol):
    """Business operation: store alert integrity proof (hash of content/payload) in selected blockchain."""

    def anchor(self, request: AlertAnchorRequest) -> AnchorReceipt:
        ...
