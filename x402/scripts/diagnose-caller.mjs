/**
 * Diagnostic: does this token's transferWithAuthorization restrict the caller?
 *
 * Every settlement we found on-chain is submitted by one address (the x402
 * facilitator, 0xd407e4...). Our simulations run with an anonymous caller.
 * Sign once, then submit the identical calldata from several callers - if the
 * token only accepts the known relayer, our signature was never the problem.
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
const FACILITATOR_RELAYER = '0xd407e409E34E0b9afb99EcCeb609bDbcD5e7f1bf';

const account = privateKeyToAccount(config.evm.privateKey);
const publicClient = createPublicClient({ chain: baseSepolia, transport: http(RPC) });

const nowSec = Number((await publicClient.getBlock({ blockTag: 'latest' })).timestamp);

const authorization = {
  from: getAddress(account.address),
  to: getAddress(config.evm.payTo),
  value: 10000n,
  validAfter: BigInt(nowSec - 60),
  validBefore: BigInt(nowSec + 900),
  nonce: keccak256(toHex('arckeeper-caller-' + Date.now() + Math.random())),
};

const signature = await account.signTypedData({
  domain: { name: 'USDC', version: '2', chainId: 84532, verifyingContract: USDC },
  types: {
    TransferWithAuthorization: [
      { name: 'from', type: 'address' },
      { name: 'to', type: 'address' },
      { name: 'value', type: 'uint256' },
      { name: 'validAfter', type: 'uint256' },
      { name: 'validBefore', type: 'uint256' },
      { name: 'nonce', type: 'bytes32' },
    ],
  },
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

const callers = [
  ['(no caller)', undefined],
  ['zero address', '0x0000000000000000000000000000000000000000'],
  ['payer itself', account.address],
  ['facilitator relayer', FACILITATOR_RELAYER],
];

console.log('payer:', account.address);
console.log('nonce:', authorization.nonce, '\n');

for (const [label, from] of callers) {
  const params = from ? [{ to: USDC, data, from }, 'latest'] : [{ to: USDC, data }, 'latest'];
  const res = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_call', params }),
  }).then((r) => r.json());
  const verdict = res.error ? 'REJECT ' + (res.error.message ?? '').slice(0, 55) : 'ACCEPT';
  console.log(`  ${label.padEnd(22)} ${verdict}`);
}
