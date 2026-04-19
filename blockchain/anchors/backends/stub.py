from __future__ import annotations

import hashlib

from blockchain.anchors.models import AlertAnchorRequest, AnchorReceipt


class StubAnchorBackend:
    """Deterministic "fake" anchor — for tests and CI without RPC."""

    def anchor(self, request: AlertAnchorRequest) -> AnchorReceipt:
        digest = hashlib.sha256(
            request.alert_id.encode("utf-8") + b"|" + request.content_hash
        ).hexdigest()
        tx_ref = "0x" + digest
        return AnchorReceipt(
            backend="stub",
            chain_id="0",
            tx_reference=tx_ref,
            block_number=None,
            explorer_url=None,
            extra={"note": "ANCHOR_BACKEND=stub — brak prawdziwej sieci"},
        )
