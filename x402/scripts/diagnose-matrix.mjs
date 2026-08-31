/**
 * Diagnostic: which authorization field makes the token reject our signature?
 *
 * A working facilitator settlement on this same token (tx 0xe81b5a7f...) uses
 * validAfter = current timestamp and value = 10000, where we use validAfter = 0
 * and value = 1000. Sign each combination and let the contract judge, so the
 * deciding field is identified rather than guessed at.
 *
 * Diagnostic only - delete once the happy path is green.
 */

import { createPublicClient, http, encodeFunctionData, parseSignature, getAddress, keccak256, toHex } from 'viem';
import { baseSepolia } from 'viem/chains';
import { privateKeyToAccount } from 'viem/accounts';

import { loadConfig } from '../src/config.js';

const config = loadConfig();
const USDC = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';
const RPC = config.evm.rpcUrl;

const account = privateKeyToAccount(config.evm.privateKey);
const publicClient = createPublicClient({ chain: baseSepolia, transport: http(RPC) });

const rpc = async (method, params) => {
  const r = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  return r.json();
};

const nowSec = Number((await publicClient.getBlock({ blockTag: 'latest' })).timestamp);

const types = {
  TransferWithAuthorization: [
    { name: 'from', type: 'address' },
    { name: 'to', type: 'address' },
    { name: 'value', type: 'uint256' },
    { name: 'validAfter', type: 'uint256' },
    { name: 'validBefore', type: 'uint256' },
    { name: 'nonce', type: 'bytes32' },
  ],
};

const domain = { name: 'USDC', version: '2', chainId: 84532, verifyingContract: USDC };

async function attempt({ label, validAfter, value, window }) {
  const validBefore = Number(validAfter) + window;
  const authorization = {
    from: getAddress(account.address),
    to: getAddress(config.evm.payTo),
    value: BigInt(value),
    validAfter: BigInt(validAfter),
    validBefore: BigInt(validBefore),
    nonce: keccak256(toHex('arckeeper-matrix-' + label + '-' + Date.now() + Math.random())),
  };

  const signature = await account.signTypedData({
    domain,
    types,
    primaryType: 'TransferWithAuthorization',
    message: authorization,
  });
  const sig = parseSignature(signature);

  const data = encodeFunctionData({
    abi: [
      {
        name: 'transferWithAuthorization',
        type: 'function',
        stateMutability: 'nonpayable',
        inputs: [
          { name: 'from', type: 'address' },
          { name: 'to', type: 'address' },
          { name: 'value', type: 'uint256' },
          { name: 'validAfter', type: 'uint256' },
          { name: 'validBefore', type: 'uint256' },
          { name: 'nonce', type: 'bytes32' },
          { name: 'v', type: 'uint8' },
          { name: 'r', type: 'bytes32' },
          { name: 's', type: 'bytes32' },
        ],
        outputs: [],
      },
    ],
    functionName: 'transferWithAuthorization',
    args: [
      authorization.from,
      authorization.to,
      authorization.value,
      authorization.validAfter,
      authorization.validBefore,
      authorization.nonce,
      Number(sig.v),
      sig.r,
      sig.s,
    ],
  });

  const res = await rpc('eth_call', [{ to: USDC, data }, 'latest']);
  const verdict = res.error ? 'REJECT ' + (res.error.message ?? '').slice(0, 60) : 'ACCEPT';
  console.log(`  ${label.padEnd(38)} ${verdict}`);
  return !res.error;
}

console.log('payer:', account.address, ' payTo:', config.evm.payTo);
console.log('now  :', nowSec, '\n');

await attempt({ label: 'validAfter=0        value=1000', validAfter: 0, value: 1000, window: 600 });
await attempt({ label: 'validAfter=0        value=10000', validAfter: 0, value: 10000, window: 600 });
await attempt({ label: `validAfter=now      value=1000`, validAfter: nowSec, value: 1000, window: 600 });
await attempt({ label: `validAfter=now      value=10000`, validAfter: nowSec, value: 10000, window: 900 });
await attempt({ label: 'validAfter=now-60   value=1000', validAfter: nowSec - 60, value: 1000, window: 600 });
