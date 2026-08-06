// SPDX-License-Identifier: MIT
pragma solidity ^0.8.27;

/// @title FlareKeeperVerifier
/// @author FlareKeeper
/// @notice Bounty 2 (Confidential Compute) on-chain gate for FlareKeeper.
///
///   The FlareKeeper rebalance decision is computed INSIDE a TEE (Flare
///   Confidential Compute). The tee-node signs the result with the TEE identity
///   key. This contract re-verifies that signature ON-CHAIN before any funds
///   move, so execution can only follow a decision that provably came from the
///   registered enclave build. This is what makes the agent "confidential AND
///   verifiable" rather than merely "off-chain and trusted".
///
///   Verification scheme mirrors the tee-node's TEE_ACTION_RESULT signing:
///     resultHash  = keccak256(opaqueResultPacking)
///     payloadHash = keccak256(abi.encode(TEE_ACTION_RESULT, chainid, resultHash))
///     ethSigned   = keccak256("\x19Ethereum Signed Message:\n32" ‖ payloadHash)
///     signer      = ecrecover(ethSigned, v, r, s)  // must == teeAddress
interface ITeeVerifier {
    function isDecisionVerified(bytes32 decisionHash) external view returns (bool);
}

contract FlareKeeperVerifier is ITeeVerifier {
    // Domain separator string used by the tee-node when signing results
    // (go-flare-common signing.TEEActionResult). Fixed by the FCC spec.
    bytes32 private constant TEE_ACTION_RESULT = bytes32("TEE_ACTION_RESULT");

    address public owner;
    /// @notice The TEE identity key registered for FlareKeeper's extension.
    /// Set by the owner; a decision is accepted only if signed by this key.
    address public teeAddress;

    /// @notice decisionHash -> verified? Prevents re-execution of a replayed decision.
    mapping(bytes32 => bool) public verifiedDecisions;

    event TeeAddressSet(address indexed tee);
    event DecisionVerified(
        bytes32 indexed decisionHash,
        bytes32 indexed actionId,
        address indexed signer,
        uint8 status
    );

    error NotOwner();
    error BadTeeSignature();
    error ZeroTeeAddress();

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    /// @notice Owner registers the TEE identity key for the FlareKeeper extension.
    function setTeeAddress(address _tee) external onlyOwner {
        if (_tee == address(0)) revert ZeroTeeAddress();
        teeAddress = _tee;
        emit TeeAddressSet(_tee);
    }

    /// @notice Recompute the decisionHash the tee-node signs over.
    /// Mirrors the offline simulator and tee-node packing so callers can build
    /// the same hash that was signed.
    function computeDecisionHash(
        bytes32 actionId,
        bytes32 submissionTag,
        bytes calldata resultData,
        uint8 status
    ) public pure returns (bytes32) {
        bytes32 resultHash = keccak256(
            abi.encodePacked(keccak256(resultData), actionId, keccak256(abi.encodePacked(submissionTag)), status)
        );
        return resultHash;
    }

    /// @notice Verify a TEE-signed rebalance decision and record it as usable.
    /// @param actionId       the instruction/action id the result belongs to
    /// @param submissionTag  the submission tag from the ActionResult
    /// @param resultData     the raw result bytes (hex of the JSON decision)
    /// @param status         the ActionResult status (1 = success)
    /// @param v,r,s          the tee-node's ECDSA signature over the result
    function verifyDecision(
        bytes32 actionId,
        bytes32 submissionTag,
        bytes calldata resultData,
        uint8 status,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external returns (bytes32 decisionHash) {
        decisionHash = computeDecisionHash(actionId, submissionTag, resultData, status);

        bytes32 payloadHash = keccak256(
            abi.encode(TEE_ACTION_RESULT, block.chainid, decisionHash)
        );
        bytes32 ethSigned = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", payloadHash)
        );
        address signer = ecrecover(ethSigned, v, r, s);
        if (signer != teeAddress) revert BadTeeSignature();

        verifiedDecisions[decisionHash] = true;
        emit DecisionVerified(decisionHash, actionId, signer, status);
    }

    /// @notice True iff `decisionHash` was verified by a valid TEE signature.
    function isDecisionVerified(bytes32 decisionHash) external view returns (bool) {
        return verifiedDecisions[decisionHash];
    }
}
