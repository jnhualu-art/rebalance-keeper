"""★ Configuration: version and operation identifiers for the FlareKeeper FCE.

Mirrors the scaffold's app/config.py. The op-type and op-command strings MUST
match the bytes32 constants in fce/contracts/InstructionSender.sol
(contract is named HelloWorldInstructionSender for scaffold tooling compat)
exactly, or actions fall through to "unsupported op type".
"""

VERSION = "0.1.0"

# Operation type for rebalancer actions.
OP_TYPE_REBALANCE = "REBALANCE"

# Command: compute an attested rebalance decision from a treasury snapshot.
OP_COMMAND_COMPUTE = "COMPUTE"
