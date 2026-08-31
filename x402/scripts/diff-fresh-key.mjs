/**
 * Diagnostic: is it the key, or the way we sign?
 *
 * Everything structural has been eliminated: the calldata layout matches a
 * known-good facilitator settlement word for word, and digest recovery on that
 * settlement succeeds, so the domain and types are right.
 *
 * The token checks the signature BEFORE it looks at the balance, so a fresh
 * key with no USDC at all still exercises signature verification:
 *   - "invalid signature"        -> our signing is wrong
 *   - "exceeds balance" or ok    -> signing is fine, the funded key's address
 *                                   is the problem
 *
 * Diagnostic only - delete once the happy path is green.
 */

import { createPublicClient, http, encodeFunctionData, parseSignature, getAddress, keccak256, toHex } from 'viem';
import { baseSepolia } from 'viem/chains';
import { privateKeyToAccount, generatePrivateKey } from 'viem/accounts';

import { loadConfig } from '../src/config.js';

const config = loadConfig();
const USDC = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';
const RPC = config.evm.rpcUrl;

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

async function submit(account) {
  const authorization = {
    from: getAddress(account.address),
    to: getAddress(config.evm.payTo),
    value: 10000n,
    validAfter: BigInt(nowSec - 60),
    validBefore: BigInt(nowSec + 840),
    nonce: keccak256(toHex('arckeeper-fresh-' + Date.now() + Math.random())),
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
  return {
    address: account.address,
    v: Number(sig.v),
    verdict: res.error ? res.error.message : 'ACCEPT',
  };
}

const funded = privateKeyToAccount(config.evm.privateKey);
const fresh = privateKeyToAccount(generatePrivateKey());

for (const [label, account] of [
  ['funded key (0xabab…) ', funded],
  ['fresh random key     ', fresh],
]) {
  const out = await submit(account);
  console.log(`${label} ${out.address}  v=${out.v}`);
  console.log(`   -> ${out.verdict}\n`);
}

console.log('reading:');
console.log('  both "invalid signature"      -> our signing is wrong');
console.log('  fresh key says balance/ok     -> signing is fine; the funded address is the problem');
