// SPDX-License-Identifier: MIT
pragma solidity ^0.8.27;

// TODO: Replace local interfaces with imports from flare-smart-contracts-v2 once published as a package.
import { ITeeExtensionRegistry } from "./interfaces/ITeeExtensionRegistry.sol";
import { ITeeMachineRegistry } from "./interfaces/ITeeMachineRegistry.sol";

/// @title HelloWorldInstructionSender
/// @author FlareKeeper
/// @notice Flare Compute Extension entry point for FlareKeeper's confidential
///         rebalancer. Sends a REBALANCE/COMPUTE instruction to the TEE; the
///         enclave runs the (private) strategy and returns a signed decision
///         that is verified on-chain by FlareKeeperVerifier.
///
/// NOTE: The contract is named HelloWorldInstructionSender only because the
///       official fce-extension-scaffold tooling (generate-bindings.sh /
///       tools/cmd/deploy-contract) hardcodes that name + the helloworld Go
///       bindings package. The on-chain OP_TYPE/OP_COMMAND below are FlareKeeper's
///       own (REBALANCE / COMPUTE); the rebalance logic is what runs inside the TEE.
///
/// DO NOT MODIFY: constructor, setExtensionId(), _getExtensionId()
contract HelloWorldInstructionSender {
    /// @notice Operation type for rebalancer actions.
    // forge-lint: disable-next-line(unsafe-typecast)
    bytes32 public constant OP_TYPE_REBALANCE = bytes32("REBALANCE");

    /// @notice Command: compute an attested rebalance decision.
    // forge-lint: disable-next-line(unsafe-typecast)
    bytes32 public constant OP_COMMAND_COMPUTE = bytes32("COMPUTE");

    /// @notice Reference to the TEE extension registry contract.
    ITeeExtensionRegistry public immutable TEE_EXTENSION_REGISTRY;
    /// @notice Reference to the TEE machine registry contract.
    ITeeMachineRegistry public immutable TEE_MACHINE_REGISTRY;

    /// @notice First public extension ID. The registry reserves IDs below this
    /// for system/reserved extensions; public extensions are assigned from here up.
    uint256 private constant FIRST_PUBLIC_EXTENSION_ID = 0x10000; // 65536

    uint256 private _extensionId;

    /// @notice Initializes the contract with registry addresses.
    constructor(
        ITeeExtensionRegistry _teeExtensionRegistry,
        ITeeMachineRegistry _teeMachineRegistry
    ) {
        require(address(_teeExtensionRegistry) != address(0), "TeeExtensionRegistry cannot be zero address");
        require(address(_teeMachineRegistry) != address(0), "TeeMachineRegistry cannot be zero address");
        require(address(_teeExtensionRegistry).code.length > 0, "TeeExtensionRegistry has no code");
        require(address(_teeMachineRegistry).code.length > 0, "TeeMachineRegistry has no code");
        TEE_EXTENSION_REGISTRY = _teeExtensionRegistry;
        TEE_MACHINE_REGISTRY = _teeMachineRegistry;
    }

    /// @notice Finds and sets this contract's extension id. Can only be set once.
    function setExtensionId() external {
        require(_extensionId == 0, "Extension ID already set.");

        uint256 c = TEE_EXTENSION_REGISTRY.nextPublicExtensionId();
        for (uint256 i = FIRST_PUBLIC_EXTENSION_ID; i < c; ++i) {
            if (TEE_EXTENSION_REGISTRY.getTeeExtensionInstructionsSender(i) == address(this)) {
                _extensionId = i;
                return;
            }
        }
        revert("Extension ID not found.");
    }

    /// @notice Sends a COMPUTE instruction to the TEE with a treasury snapshot.
    /// @param _message JSON-encoded treasury snapshot
    ///        {"treasury_balance":float,"treasury_health":float,"floor":float,"ceiling":float}
    function sendRebalance(bytes calldata _message) external payable {
        address[] memory teeIds = TEE_MACHINE_REGISTRY.getRandomTeeIds(_getExtensionId(), 1);
        address[] memory cosigners = new address[](0);

        ITeeExtensionRegistry.TeeInstructionParams memory params = ITeeExtensionRegistry.TeeInstructionParams({
            opType: OP_TYPE_REBALANCE,
            opCommand: OP_COMMAND_COMPUTE,
            message: _message,
            cosigners: cosigners,
            cosignersThreshold: 0,
            claimBackAddress: msg.sender
        });

        TEE_EXTENSION_REGISTRY.sendInstructions{value: msg.value}(teeIds, params);
    }

    /// @notice Returns the cached extension ID, reverting if not yet set.
    function _getExtensionId() internal view returns (uint256) {
        require(_extensionId != 0, "Extension ID is not set.");
        return _extensionId;
    }
}
