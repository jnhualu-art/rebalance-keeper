/**
 * Diagnostic: recover the signer from a KNOWN-GOOD facilitator settlement.
 *
 * This is the control that pins down whether our model of the token's EIP-712
 * digest is correct at all. We pull a settlement the facilitator actually
 * landed on-chain, decode its exact authorization fields and signature, and
 * run them through the same recovery path used for our own payments.
 *
 * If it recovers to the payer the token accepted -> the domain and types are
 * right, so whatever is wrong with our own payment lives in the parameters,
 * not in the signing.
 * If it does not -> our digest model is wrong and every signature we build
 * rests on a faulty premise.
 *
 * Diagnostic only - delete once the happy path is green.
 */

import { recoverTypedDataAddress, concat, toHex, getAddress } from 'viem';

import { loadConfig } from '../src/config.js';

const config = loadConfig();
const USDC = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';
const RPC = config.evm.rpcUrl;

// A settlement the official facilitator landed successfully.
const TX = '0xe81b5a7ff3e5ecefcff6296692f3ee8ebd509bed82df85ada314145217469a74';

const res = await fetch(RPC, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_getTransactionByHash', params: [TX] }),
}).then((r) => r.json());

const tx = res.result;
const input = tx.input;
const selector = input.slice(0, 10);
const words = [];
for (let i = 10; i < input.length; i += 64) words.push(input.slice(i, i + 64));

console.log('settlement tx      :', TX);
console.log('submitted by       :', tx.from);
console.log('token             :', tx.to);
console.log('selector          :', selector, selector === '0xe3ee160e' ? '(transferWithAuthorization v,r,s)' : '(UNEXPECTED)');

const [fromW, toW, valueW, validAfterW, validBeforeW, nonceW, vW, rW, sW] = words;

const message = {
  from: getAddress('0x' + fromW.slice(-40)),
  to: getAddress('0x' + toW.slice(-40)),
  value: BigInt('0x' + valueW),
  validAfter: BigInt('0x' + validAfterW),
  validBefore: BigInt('0x' + validBeforeW),
  nonce: '0x' + nonceW,
};
const v = Number(BigInt('0x' + vW));
const signature = concat(['0x' + rW, '0x' + sW, toHex(v)]);

console.log('\ndecoded authorization');
console.log('  from        :', message.from);
console.log('  to          :', message.to);
console.log('  value       :', message.value.toString());
console.log('  validAfter  :', message.validAfter.toString());
console.log('  validBefore :', message.validBefore.toString());
console.log('  validBefore - validAfter :', (message.validBefore - message.validAfter).toString(), 'seconds');
console.log('  nonce       :', message.nonce);
console.log('  v           :', v);

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

console.log('\nrecovery check');
for (const [name, version] of [
  ['USDC', '2'],
  ['USD Coin', '2'],
]) {
  const recovered = await recoverTypedDataAddress({
    domain: { name, version, chainId: 84532, verifyingContract: USDC },
    types,
    primaryType: 'TransferWithAuthorization',
    message,
    signature,
  });
  const ok = recovered.toLowerCase() === message.from.toLowerCase();
  console.log(`  name="${name}" ver="${version}" -> ${recovered}`);
  console.log(`    ${ok ? '*** MATCHES the payer the token accepted ***' : 'no match'}`);
}
