from __future__ import annotations

import json
import logging

from blockchain.anchors.backends.stub import StubAnchorBackend
from blockchain.anchors.models import AlertAnchorRequest, AnchorReceipt

logger = logging.getLogger(__name__)


class LogJsonAnchorBackend:
    """Logs the anchoring intent as JSON and returns a deterministic (stub-like) receipt."""

    def __init__(self) -> None:
        self._stub = StubAnchorBackend()

    def anchor(self, request: AlertAnchorRequest) -> AnchorReceipt:
        receipt = self._stub.anchor(request)
        payload = {
            "alert_id": request.alert_id,
            "content_hash_hex": request.content_hash.hex(),
            "receipt": {
                "backend": receipt.backend,
                "chain_id": receipt.chain_id,
                "tx_reference": receipt.tx_reference,
                "block_number": receipt.block_number,
                "explorer_url": receipt.explorer_url,
                "extra": receipt.extra,
            },
        }
        logger.info("anchor %s", json.dumps(payload, ensure_ascii=False))
        return AnchorReceipt(
            backend="log+json",
            chain_id=receipt.chain_id,
            tx_reference=receipt.tx_reference,
            block_number=receipt.block_number,
            explorer_url=receipt.explorer_url,
            extra={**receipt.extra, "logged": True},
        )
