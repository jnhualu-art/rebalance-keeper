/**
 * Control experiment: sign an EIP-3009 authorization with viem directly,
 * skipping the x402 SDK entirely, and hand it to the token contract.
 *
 * If the contract accepts the hand-rolled signature but rejected the SDK's,
 * the SDK is signing something subtly different and we can diff the two.
 * If the contract rejects both, our model of this token's EIP-712 domain is
 * wrong and no amount of SDK fiddling will help.
 *
 * Diagnostic only - delete once the happy path is green.
 */

import { createPublicClient, http, encodeFunctionData, parseSignature, getAddress, formatUnits, keccak256, toHex } from 'viem';
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

const decodeString = (hex) => {
  const raw = hex.startsWith('0x') ? hex.slice(2) : hex;
  const len = parseInt(raw.slice(64, 128), 16);
  return Buffer.from(raw.slice(128, 128 + len * 2), 'hex').toString('utf8');
};

// ---- What does the token actually claim about itself? ----
const nameRaw = await rpc('eth_call', [{ to: USDC, data: '0x06fdde03' }, 'latest']);
const versionRaw = await rpc('eth_call', [{ to: USDC, data: '0x54fd4d50' }, 'latest']);
const sepRaw = await rpc('eth_call', [{ to: USDC, data: '0x3644e515' }, 'latest']);
const block = await rpc('eth_getBlockByNumber', ['latest', false]);

const tokenName = decodeString(nameRaw.result);
const tokenVersion = decodeString(versionRaw.result);

console.log('token name()          :', JSON.stringify(tokenName));
console.log('token version()       :', JSON.stringify(tokenVersion));
console.log('on-chain DOMAIN_SEP   :', sepRaw.result);
console.log('chain block.timestamp :', BigInt(block.result.timestamp).toString());
console.log('local now             :', Math.floor(Date.now() / 1000).toString());

// ---- Hand-rolled signature, standard EIP-3009, nothing x402-specific ----
const nonce = keccak256(toHex('arckeeper-probe-' + Date.now()));
const nowSec = BigInt(block.result.timestamp);
const authorization = {
  from: getAddress(account.address),
  to: getAddress(config.evm.payTo),
  value: 1000n,
  validAfter: 0n,
  validBefore: nowSec + 600n,
  nonce,
};

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

console.log('\n-- signature A: domain name/version read from the token --');
for (const [name, version] of [
  [tokenName, tokenVersion],
  ['USD Coin', '2'],
  ['USDC', '2'],
]) {
  const domain = { name, version, chainId: 84532, verifyingContract: USDC };
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
  const verdict = res.error ? 'REJECTED: ' + res.error.message : 'ACCEPTED';
  console.log(`  name="${name}" version="${version}" -> ${verdict}`);
}
