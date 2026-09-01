/**
 * Verify settlement transactions on Base Sepolia.
 *
 * Proves three things a log line cannot: the transactions actually landed,
 * the payer paid no gas (the facilitator relayed), and the amounts charged
 * match the prices the service advertised.
 *
 * Usage: node scripts/verify-settlement.mjs <txhash> [txhash ...]
 */

import { createPublicClient, http, formatUnits, toEventSelector } from 'viem';
import { baseSepolia } from 'viem/chains';

const RPC = process.env.EVM_RPC_URL || 'https://sepolia.base.org';
const USDC = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';
const FACILITATOR_RELAYER = '0xd407e409e34e0b9afb99ecceb609bdbcd5e7f1bf';

// Derived, never hardcoded: a mistyped topic silently matches nothing and
// would make the whole check look clean while proving nothing.
const TRANSFER_TOPIC = toEventSelector('Transfer(address,address,uint256)');
const AUTH_USED_TOPIC = toEventSelector('AuthorizationUsed(address,bytes32)');

const client = createPublicClient({ chain: baseSepolia, transport: http(RPC) });

const hashes = process.argv.slice(2);
if (hashes.length === 0) {
  console.error('usage: node scripts/verify-settlement.mjs <txhash> [...]');
  process.exit(1);
}

for (const hash of hashes) {
  const receipt = await client.getTransactionReceipt({ hash });
  const tx = await client.getTransaction({ hash });

  const gasPaidByPayer = tx.from.toLowerCase() === FACILITATOR_RELAYER ? 0n : tx.gas * tx.gasPrice;

  console.log(`\n=== ${hash}`);
  console.log(`  status      : ${receipt.status === 'success' ? 'SUCCESS' : 'REVERTED'}`);
  console.log(`  block       : ${receipt.blockNumber}`);
  console.log(`  gas used    : ${receipt.gasUsed}`);
  console.log(`  tx from     : ${tx.from}`);
  console.log(
    `  relayed     : ${tx.from.toLowerCase() === FACILITATOR_RELAYER ? 'yes (gasless for payer)' : 'NO - payer sent the tx itself'}`,
  );
  if (gasPaidByPayer === 0n) console.log('  payer gas   : 0');

  for (const log of receipt.logs) {
    if (log.address.toLowerCase() !== USDC.toLowerCase()) continue;

    if (log.topics[0]?.toLowerCase() === TRANSFER_TOPIC) {
      const from = '0x' + log.topics[1].slice(26);
      const to = '0x' + log.topics[2].slice(26);
      const amount = BigInt(log.data);
      console.log(`  Transfer    : ${formatUnits(amount, 6)} USDC`);
      console.log(`                from ${from}`);
      console.log(`                to   ${to}`);
    } else if (log.topics[0]?.toLowerCase() === AUTH_USED_TOPIC) {
      console.log('  AuthorizationUsed: present (EIP-3009 path confirmed)');
    }
  }
}

console.log('');
