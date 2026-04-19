"""
Demo: anchor hash of alert via chain-agnostic AnchorBackend.

Run from hackaton_ETHSilesia directory:
  python -m blockchain.anchor_alert --alert-id demo-1 --text "alert content"
  ANCHOR_BACKEND=log python -m blockchain.anchor_alert --alert-id demo-1 --text "x"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging


def _payload_hash(text: str | None, file_path: str | None) -> bytes:
    if text is not None and file_path is not None:
        raise SystemExit("Provide either --text or --file, not both.")
    if text is not None:
        data = text.encode("utf-8")
    elif file_path is not None:
        with open(file_path, "rb") as f:
            data = f.read()
    else:
        raise SystemExit("Required: --text or --file")
    return hashlib.sha256(data).digest()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    p = argparse.ArgumentParser(description="Anchor hash of alert (chain-agnostic).")
    p.add_argument("--alert-id", required=True, help="Unique alert ID from backend")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="Content to hash (UTF-8)")
    g.add_argument("--file", help="Path to file to hash")
    args = p.parse_args()

    from blockchain.anchors import AlertAnchorRequest, get_anchor_backend

    content_hash = _payload_hash(args.text, args.file)
    req = AlertAnchorRequest(alert_id=args.alert_id, content_hash=content_hash)
    backend = get_anchor_backend()
    receipt = backend.anchor(req)
    print(json.dumps(receipt.__dict__, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
