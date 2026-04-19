from __future__ import annotations

import os
from dataclasses import dataclass

from blockchain.anchors.models import AlertAnchorRequest, AnchorReceipt

# Minimalny ABI: kontrakt `contracts/AlertAnchor.sol`
ANCHOR_ABI = [
    {
        "inputs": [
            {"internalType": "bytes32", "name": "contentHash", "type": "bytes32"},
            {"internalType": "string", "name": "alertId", "type": "string"},
        ],
        "name": "anchor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


def _require_evm_contract_address(addr: str) -> None:
    """Czytelny błąd zamiast ValueError z eth_utils przy placeholderze typu 0x..."""
    v = addr.strip()
    if "..." in v or not v.startswith("0x") or len(v) != 42:
        raise ValueError(
            "EVM_CONTRACT_ADDRESS must be a full address (0x + 40 hex characters), "
            "not the example text \"0x...\". With `npm run node` running in the hardhat folder, "
            "execute `npm run deploy:local` and copy the printed AlertAnchor address "
            "(e.g. 0x5FbDB2315678afecb367f032d93F642f64180aa3)."
        )
    try:
        int(v[2:], 16)
    except ValueError as e:
        raise ValueError(f"EVM_CONTRACT_ADDRESS nie jest poprawnym hex: {addr!r}") from e


@dataclass
class EvmAnchorBackend:
    """Store via EVM contract (Hardhat locally, Polygon Amoy, Base Sepolia, …)."""

    rpc_url: str
    private_key: str
    contract_address: str
    chain_id: int
    explorer_tx_template: str | None

    @classmethod
    def from_env(cls) -> EvmAnchorBackend:
        rpc = os.environ["EVM_RPC_URL"].strip()
        pk = os.environ["EVM_PRIVATE_KEY"].strip()
        if pk.startswith("0x"):
            pk = pk[2:]
        contract = os.environ["EVM_CONTRACT_ADDRESS"].strip()
        _require_evm_contract_address(contract)
        chain_id = int(os.environ.get("EVM_CHAIN_ID", "31337").strip())
        tpl = os.environ.get("EVM_EXPLORER_TX_URL", "").strip() or None
        return cls(
            rpc_url=rpc,
            private_key=pk,
            contract_address=contract,
            chain_id=chain_id,
            explorer_tx_template=tpl,
        )

    def anchor(self, request: AlertAnchorRequest) -> AnchorReceipt:
        from web3 import Web3
        from web3.middleware import ExtraDataToPOAMiddleware

        w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        if os.environ.get("EVM_POA", "").strip() in ("1", "true", "yes"):
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        account = w3.eth.account.from_key("0x" + self.private_key)
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(self.contract_address),
            abi=ANCHOR_ABI,
        )
        content_hash = request.content_hash
        alert_id = request.alert_id

        tx: dict = contract.functions.anchor(content_hash, alert_id).build_transaction(
            {
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address, "pending"),
                "chainId": self.chain_id,
            }
        )

        block = w3.eth.get_block("latest")
        base_fee = block.get("baseFeePerGas")
        if base_fee is not None:
            priority = w3.to_wei(2, "gwei")
            tx["maxPriorityFeePerGas"] = priority
            tx["maxFeePerGas"] = base_fee * 2 + priority
        else:
            tx["gasPrice"] = w3.eth.gas_price

        try:
            est = int(w3.eth.estimate_gas(tx))
            tx["gas"] = min(int(est * 1.25) + 20_000, 600_000)
        except Exception:
            tx["gas"] = 250_000

        signed = account.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = w3.eth.send_raw_transaction(raw)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

        tx_hex = Web3.to_hex(tx_hash)
        explorer = None
        if self.explorer_tx_template:
            explorer = self.explorer_tx_template.format(tx_hash=tx_hex)

        return AnchorReceipt(
            backend="evm",
            chain_id=str(self.chain_id),
            tx_reference=tx_hex,
            block_number=int(receipt.blockNumber),
            explorer_url=explorer,
            extra={"contract": self.contract_address},
        )
