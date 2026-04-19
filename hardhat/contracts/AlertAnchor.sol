// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title AlertAnchor — immutable proof (on-chain event) for alert compliance hash.
contract AlertAnchor {
    event AlertAnchored(
        bytes32 indexed contentHash,
        bytes32 indexed alertIdHash,
        string alertId,
        uint256 blockNumber,
        uint256 blockTimestamp
    );

    /// @notice Records a proof: hash of alert content + identifier (e.g. UUID from backend).
    function anchor(bytes32 contentHash, string calldata alertId) external {
        bytes32 aid = keccak256(bytes(alertId));
        emit AlertAnchored(contentHash, aid, alertId, block.number, block.timestamp);
    }
}
