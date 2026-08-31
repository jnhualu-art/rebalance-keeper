/**
 * Balance probe for a Base Sepolia payer wallet.
 *
 * Answers one question before spending real (testnet) money: does this wallet
 * actually hold gas and USDC on the chain we are about to pay on?
 *
 * Usage:  node src/balance.js [address ...]
 *         node src/balance.js            # no address -> derives from .env key
 *
 * Exit codes: 0 = at least one address is ready, 1 = something is missing.
 */

import { createPublicClient, http, formatUnits, isAddress } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { baseSepolia } from 'viem/chains';

import { loadConfig } from './config.js';

const USDC_BASE_SEPOLIA = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';
const ERC20_BALANCE_OF = '0x70a08231'; // balanceOf(address)

const config = loadConfig();
const rpcUrl = config.evm?.rpcUrl ?? 'https://sepolia.base.org';

const publicClient = createPublicClient({ chain: baseSepolia, transport: http(rpcUrl) });

function addressesFromArgv(argv) {
  const given = argv.slice(2);
  if (given.length === 0) return null;
  for (const a of given) {
    if (!isAddress(a)) {
      console.error(`not a valid address: ${a}`);
      process.exit(1);
    }
  }
  return given;
}

function deriveFromKey() {
  if (!config.evm?.privateKey) {
    console.error('No address given and no private key in .env.');
    process.exit(1);
  }
  return [privateKeyToAccount(config.evm.privateKey).address];
}

const addresses = addressesFromArgv(process.argv) ?? deriveFromKey();

/** Raw JSON-RPC call so we do not depend on a bundled ABI for a test token. */
async function readUsdc(address) {
  const data = ERC20_BALANCE_OF + address.slice(2).toLowerCase().padStart(64, '0');
  const raw = await publicClient.request({ method: 'eth_call', params: [{ to: USDC_BASE_SEPOLIA, data }, 'latest'] });
  if (!raw || raw === '0x') return 0n;
  return BigInt(raw);
}

console.log(`rpc: ${rpcUrl}`);
console.log(`chain: base-sepolia (${baseSepolia.id})`);
console.log(`usdc: ${USDC_BASE_SEPOLIA}\n`);

let anyReady = false;

for (const address of addresses) {
  const [eth, usdc] = await Promise.all([
    publicClient.getBalance({ address }),
    readUsdc(address).catch(() => 0n),
  ]);

  const hasGas = eth > 0n;
  const hasUsdc = usdc > 0n;

  // Under the exact scheme the payer signs an EIP-3009 authorization and the
  // facilitator submits it, paying the gas. A payer with zero ETH can still
  // pay, so gas is reported but does not gate readiness.
  const ready = hasUsdc;
  if (ready) anyReady = true;

  console.log(`address : ${address}`);
  console.log(`  ETH    : ${formatUnits(eth, 18)}   ${hasGas ? 'ok' : 'none - not needed, settlement is gasless'}`);
  console.log(`  USDC   : ${formatUnits(usdc, 6)}   ${hasUsdc ? 'ok' : 'MISSING - payment'}`);
  console.log(`  status : ${ready ? 'READY' : 'needs USDC'}\n`);
}

if (!anyReady) {
  console.log('Top up before running the client:');
  console.log('  ETH  : https://portal.cdp.coinbase.com/products/faucet');
  console.log('  USDC : https://faucet.circle.com/  (choose Base Sepolia + USDC)');
  process.exit(1);
}
