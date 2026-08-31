/**
 * Diagnostic: split "the contract rejects it" from "the facilitator rejects it".
 *
 * Signs a fresh authorization, then (a) simulates the EIP-3009 call directly
 * against the token contract and (b) hands the same payload to the facilitator.
 * If (a) succeeds and (b) fails, the problem is the facilitator's expectations,
 * not our signing.
 *
 * Also dumps the exact HTTP body sent to the facilitator, so a malformed
 * envelope is visible rather than invisible.
 *
 * Diagnostic only - delete once the happy path is green.
 */

import {
  createPublicClient,
  http,
  encodeFunctionData,
  parseSignature,
  getAddress,
  formatUnits,
} from 'viem';
import { baseSepolia } from 'viem/chains';
import { privateKeyToAccount } from 'viem/accounts';
import { x402Client, x402HTTPClient } from '@x402/core/client';
import { registerExactEvmScheme } from '@x402/evm/exact/client';

import { loadConfig } from '../src/config.js';

const config = loadConfig();
const USDC = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';
const serviceUrl = `http://localhost:${config.service.port}/signal`;

const account = privateKeyToAccount(config.evm.privateKey);
const publicClient = createPublicClient({
  chain: baseSepolia,
  transport: http(config.evm.rpcUrl),
});

const client = new x402Client();
registerExactEvmScheme(client, {
  signer: account,
  networks: [config.evm.network],
  schemeOptions: { rpcUrl: config.evm.rpcUrl },
});
const httpClient = new x402HTTPClient(client);

console.log('payer      :', account.address);
console.log('asset      :', USDC);
console.log('payTo      :', config.evm.payTo);

// Balance first: an unfunded payer would look identical to a bad signature.
const balanceOf = await publicClient.request({
  method: 'eth_call',
  params: [
    {
      to: USDC,
      data: '0x70a08231' + account.address.slice(2).toLowerCase().padStart(64, '0'),
    },
    'latest',
  ],
});
console.log('payer USDC :', formatUnits(BigInt(balanceOf), 6));

// ---- 1. Get requirements from the service ----
const initial = await fetch(serviceUrl);
const paymentRequired = httpClient.getPaymentRequiredResponse((n) => initial.headers.get(n));
const requirements = paymentRequired.accepts[0];
console.log('\n[1] requirements:', JSON.stringify(requirements));

// ---- 2. Sign ----
const payload = await httpClient.createPaymentPayload(paymentRequired, {
  url: serviceUrl,
  method: 'GET',
});
const auth = payload.payload.authorization;
console.log('\n[2] authorization:', JSON.stringify(auth, null, 2));

// ---- 3. Simulate the EIP-3009 call straight against the contract ----
const sig = parseSignature(payload.payload.signature);
console.log('\n[3] signature: v=%s', sig.v);

const callData = encodeFunctionData({
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
    getAddress(auth.from),
    getAddress(auth.to),
    BigInt(auth.value),
    BigInt(auth.validAfter),
    BigInt(auth.validBefore),
    auth.nonce,
    Number(sig.v),
    sig.r,
    sig.s,
  ],
});

console.log('\n[4] simulating transferWithAuthorization on-chain...');
// Raw JSON-RPC instead of viem, so the node's own revert payload survives.
// viem collapses it into "RPC Request failed" and hides the actual reason.
const rpcResponse = await fetch(config.evm.rpcUrl, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'eth_call',
    params: [{ to: USDC, data: callData }, 'latest'],
  }),
});
const rpcJson = await rpcResponse.json();
if (rpcJson.error) {
  console.log('    CONTRACT REJECTS');
  console.log('    code   :', rpcJson.error.code);
  console.log('    message:', rpcJson.error.message);
  console.log('    data   :', JSON.stringify(rpcJson.error.data ?? null).slice(0, 300));
} else {
  console.log('    CONTRACT ACCEPTS ->', String(rpcJson.result).slice(0, 80));
}

// A plain transfer tells us whether the token blocks the payTo address.
const transferData =
  '0xa9059cbb' +
  '1111111111111111111111111111111111111111'.padStart(64, '0') +
  (1000).toString(16).padStart(64, '0');
const transferSim = await fetch(config.evm.rpcUrl, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({
    jsonrpc: '2.0',
    id: 2,
    method: 'eth_call',
    params: [{ to: USDC, data: transferData, from: account.address }, 'latest'],
  }),
});
const transferJson = await transferSim.json();
console.log(
  '\n[4b] plain ERC-20 transfer payer -> payTo: ' +
    (transferJson.error ? 'REJECTED ' + transferJson.error.message : 'ok'),
  transferJson.error ? '\n     data: ' + JSON.stringify(transferJson.error.data ?? null).slice(0, 200) : '',
);

// ---- 5. Same payload, but through the facilitator, with the wire body shown ----
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, opts) => {
  if (String(url).includes('facilitator')) {
    console.log('\n[5] POST', String(url));
    console.log('    body:', String(opts?.body ?? '').slice(0, 600));
  }
  return realFetch(url, opts);
};

const { HTTPFacilitatorClient } = await import('@x402/core/server');
const facilitator = new HTTPFacilitatorClient({ url: config.service.facilitatorUrl });
const verified = await facilitator.verify(payload, requirements);
globalThis.fetch = realFetch;

console.log('\n[6] facilitator verdict:', JSON.stringify(verified));
