"""
Minimal "hello Solana" in Python: connect to devnet and read the RPC node version.
Run (with active venv hackatonkato):
  python blockchain/solana_hello.py
"""
from __future__ import annotations

from solana.rpc.api import Client

DEVNET_RPC = "https://api.devnet.solana.com"


def main() -> None:
    client = Client(DEVNET_RPC)
    version = client.get_version()
    print("Connected to Solana devnet.")
    print("RPC node version:", version.value)


if __name__ == "__main__":
    main()
