/**
 * Diagnostic: byte-for-byte comparison of our calldata against a settlement
 * the facilitator landed successfully.
 *
 * digest recovery already proved the domain and types are right, so the
 * remaining suspect is the calldata we submit. Both encodings are printed side
 * by side, word by word, so a field in the wrong slot is visible immediately.
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
const TX = '0xe81b5a7ff3e5ecefcff6296692f3ee8ebd509bed82df85ada314145217469a74';

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

// ---- The known-good settlement ----
const goodTx = (await rpc('eth_getTransactionByHash', [TX])).result;
const goodInput = goodTx.input;
const goodWords = [];
for (let i = 10; i < goodInput.length; i += 64) goodWords.push(goodInput.slice(i, i + 64));

// ---- Ours, mirroring the good one's shape ----
const nowSec = Number((await publicClient.getBlock({ blockTag: 'latest' })).timestamp);
const authorization = {
  from: getAddress(account.address),
  to: getAddress('0x2E0c37B721124e2558bAf75F6F8E6Cc9f14aec29'), // same recipient as the good tx
  value: 10000n,
  validAfter: BigInt(nowSec - 60),
  validBefore: BigInt(nowSec + 840),
  nonce: keccak256(toHex('arckeeper-diff-' + Date.now() + Math.random())),
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
const ourInput = encodeFunctionData({
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

const ourWords = [];
for (let i = 10; i < ourInput.length; i += 64) ourWords.push(ourInput.slice(i, i + 64));

const names = ['from', 'to', 'value', 'validAfter', 'validBefore', 'nonce', 'v', 'r', 's'];

console.log('selector  good:', goodInput.slice(0, 10), ' ours:', ourInput.slice(0, 10));
console.log('wordcount good:', goodWords.length, ' ours:', ourWords.length, '\n');
console.log('slot  field        known-good                                ours');
console.log('-'.repeat(96));
for (let i = 0; i < Math.max(goodWords.length, ourWords.length); i += 1) {
  const g = (goodWords[i] ?? '').slice(0, 34) + '…';
  const o = (ourWords[i] ?? '').slice(0, 34) + '…';
  console.log(`${String(i).padEnd(6)}${(names[i] ?? '?').padEnd(13)}${g.padEnd(36)}${o}`);
}

// ---- Submit ours with the good tx's relayer as caller ----
const sim = await rpc('eth_call', [{ to: USDC, data: ourInput, from: goodTx.from }, 'latest']);
console.log('\nour calldata, submitted as', goodTx.from);
console.log('  verdict:', sim.error ? 'REJECT ' + sim.error.message : 'ACCEPT');

// ---- And the good calldata replayed now, as a sanity check ----
const replay = await rpc('eth_call', [{ to: USDC, data: goodInput, from: goodTx.from }, 'latest']);
console.log('\nthe known-good calldata replayed now (nonce already used, so it must fail)');
console.log('  verdict:', replay.error ? 'REJECT ' + replay.error.message : 'ACCEPT');
