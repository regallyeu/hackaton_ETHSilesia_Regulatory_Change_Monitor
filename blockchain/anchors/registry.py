from __future__ import annotations

import os

from blockchain.anchors.backends.log_json import LogJsonAnchorBackend
from blockchain.anchors.backends.stub import StubAnchorBackend
from blockchain.anchors.protocol import AnchorBackend


def get_anchor_backend() -> AnchorBackend:
    """
    Implementation selection via the ANCHOR_BACKEND environment variable:
      stub | log | evm  (and aliases: polygon, ethereum, hardhat → evm)

    EVM requires: EVM_RPC_URL, EVM_PRIVATE_KEY, EVM_CONTRACT_ADDRESS [, EVM_CHAIN_ID] [, EVM_EXPLORER_TX_URL]

    Fabric / Hyperledger: same AnchorBackend interface — separate class (SDK gateway), outside the scope of this file.
    """
    raw = os.environ.get("ANCHOR_BACKEND", "stub").strip().lower()
    aliases = {
        "polygon": "evm",
        "ethereum": "evm",
        "hardhat": "evm",
        "base": "evm",
    }
    kind = aliases.get(raw, raw)

    if kind in ("stub", "", "none", "off"):
        return StubAnchorBackend()
    if kind in ("log", "log_json", "logging"):
        return LogJsonAnchorBackend()
    if kind in ("fabric", "hyperledger"):
        raise ValueError(
            "ANCHOR_BACKEND=fabric: add adapter implementing AnchorBackend "
            "(Fabric Gateway); interface remains the same."
        )
    if kind == "evm":
        from blockchain.anchors.backends.evm import EvmAnchorBackend

        return EvmAnchorBackend.from_env()

    raise ValueError(
        f"Unknown ANCHOR_BACKEND={raw!r}. Allowed: stub, log, evm (or fabric with adapter)."
    )
