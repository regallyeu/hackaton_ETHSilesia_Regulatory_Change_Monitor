// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title AlertAnchor — niezmienialny dowód (event on-chain) dla hasha alertu compliance.
contract AlertAnchor {
    event AlertAnchored(
        bytes32 indexed contentHash,
        bytes32 indexed alertIdHash,
        string alertId,
        uint256 blockNumber,
        uint256 blockTimestamp
    );

    /// @notice Zapisuje dowód: hash treści alertu + identyfikator (np. UUID z backendu).
    function anchor(bytes32 contentHash, string calldata alertId) external {
        bytes32 aid = keccak256(bytes(alertId));
        emit AlertAnchored(contentHash, aid, alertId, block.number, block.timestamp);
    }
}
