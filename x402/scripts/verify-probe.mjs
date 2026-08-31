/**
 * Diagnostic probe: ask the facilitator exactly why it rejects a payment.
 *
 * The server only surfaces a generic "invalid_exact_evm_signature". This walks
 * the protocol by hand so the facilitator's own invalidReason is visible.
 *
 * Usage: node scripts/verify-probe.mjs [serviceUrl]
 *
 * Not part of the shipped surface - delete once the happy path is green.
 */

import { x402Client, x402HTTPClient } from '@x402/core/client';
import { registerExactEvmScheme } from '@x402/evm/exact/client';
import { HTTPFacilitatorClient } from '@x402/core/server';
import { privateKeyToAccount } from 'viem/accounts';

import { loadConfig } from '../src/config.js';

const config = loadConfig();
const serviceUrl = process.argv[2] ?? `http://localhost:${config.service.port}/signal`;

const account = privateKeyToAccount(config.evm.privateKey);
const client = new x402Client();
registerExactEvmScheme(client, {
  signer: account,
  networks: [config.evm.network],
  schemeOptions: { rpcUrl: config.evm.rpcUrl },
});
const httpClient = new x402HTTPClient(client);

console.log('payer       :', account.address);
console.log('facilitator :', config.service.facilitatorUrl);

// 1. Ask the service what it wants.
const initial = await fetch(serviceUrl);
const paymentRequired = httpClient.getPaymentRequiredResponse((n) => initial.headers.get(n));
console.log('\n[1] paymentRequired:', JSON.stringify(paymentRequired, null, 2));

// 2. Pick the requirement we intend to satisfy. The service quotes exactly
//    one option here, so the selector is not needed.
const requirements = paymentRequired.accepts[0];
console.log('\n[2] selected:', JSON.stringify(requirements, null, 2));

// 3. Sign it. The HTTP wrapper resolves the requirement and version itself.
const payload = await httpClient.createPaymentPayload(paymentRequired, {
  url: serviceUrl,
  method: 'GET',
});
console.log('\n[3] payload:', JSON.stringify(payload, null, 2));

// 4. Ask the facilitator to verify, and print whatever it says back.
const facilitator = new HTTPFacilitatorClient({ url: config.service.facilitatorUrl });
const verified = await facilitator.verify(payload, requirements);
console.log('\n[4] verify result:', JSON.stringify(verified, null, 2));

if (!verified?.isValid) {
  console.log('\n>>> facilitator refused: ' + (verified?.invalidReason ?? '(no reason given)'));
  process.exit(1);
}

console.log('\n>>> signature accepted; settlement would proceed.');
