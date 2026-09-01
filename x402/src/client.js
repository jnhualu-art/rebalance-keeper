/**
 * ArcKeeper x402 — paying agent (buyer side).
 *
 * Fetches a paid resource and settles automatically.
 *
 * Audit properties:
 *   - The spend ceiling is enforced by the SDK's own SpendControls, not by
 *     homegrown checks. An autonomous payer must structurally be unable to
 *     honour an arbitrary price quoted by a remote service.
 *   - Every request carries a timeout; a stalled service cannot wedge the agent.
 *   - The private key is loaded into a signer and never logged. Only the
 *     derived address is printed.
 */

import { fileURLToPath } from 'node:url';

import { x402Client, x402HTTPClient } from '@x402/core/client';
import { wrapFetchWithPayment } from '@x402/fetch';
import { registerExactEvmScheme } from '@x402/evm/exact/client';
import { privateKeyToAccount } from 'viem/accounts';

import { loadConfig } from './config.js';

export function createAgent(config) {
  // A viem account (address + signTypedData) already satisfies ClientEvmSigner.
  // Passing a WalletClient here instead is silently accepted by the types but
  // fails at signing time with "Address undefined is invalid".
  const account = privateKeyToAccount(config.evm.privateKey);

  const client = new x402Client().setSpendControls({
    maxAmountPerPayment: `$${config.client.maxPaymentUsdc}`,
  });

  registerExactEvmScheme(client, {
    signer: account,
    // Restrict registration to the one chain we operate on. A wildcard
    // registration would let a malicious service quote any EVM chain.
    networks: [config.evm.network],
    schemeOptions: { rpcUrl: config.evm.rpcUrl },
  });

  return {
    account,
    client,
    httpClient: new x402HTTPClient(client),
    fetchWithPayment: wrapFetchWithPayment(fetch, client),
    payerAddress: account.address,
  };
}

/**
 * Buy one paid response.
 *
 * Returns a plain result object instead of throwing on a non-2xx, so a
 * caller deciding autonomously can branch rather than crash.
 */
export async function buyResource(agent, url, timeoutMs) {
  const response = await agent.fetchWithPayment(url, {
    method: 'GET',
    signal: AbortSignal.timeout(timeoutMs),
  });

  if (!response.ok) {
    return { ok: false, status: response.status, error: await response.text() };
  }

  const settlement = agent.httpClient.getPaymentSettleResponse(
    (name) => response.headers.get(name),
  );

  return {
    ok: true,
    status: response.status,
    data: await response.json(),
    settlement: settlement
      ? { transaction: settlement.transaction, network: settlement.network }
      : null,
  };
}

const isCli = process.argv[1] === fileURLToPath(import.meta.url);

if (isCli) {
  const config = loadConfig();

  if (!config.evm) {
    console.error(
      'EVM_PAY_TO is not set. Copy .env.example to .env and fill in an EVM payout address.',
    );
    process.exit(1);
  }

  const agent = createAgent(config);
  // Accept either a bare tier name ("treasury") or a full URL.
  const target = process.argv[2] ?? '/signal';
  const url = /^https?:\/\//.test(target)
    ? target
    : `http://localhost:${config.service.port}${target.startsWith('/') ? target : `/${target}`}`;

  console.log('payer:  ', agent.payerAddress);
  console.log('ceiling: $' + config.client.maxPaymentUsdc);
  console.log('target:  ' + url);

  try {
    const result = await buyResource(agent, url, config.client.timeoutMs);
    console.log(JSON.stringify(result, null, 2));
    if (result.status === 503) {
      // Not a payment failure: the seller had nothing to sell, so nothing was
      // spent. Say so, otherwise a 503 looks like a burned payment.
      console.error(
        '\nnote: 503 means the seller refused before quoting a price. ' +
          'No payment was settled. Refresh the snapshot and retry.',
      );
    }
    if (!result.ok) process.exitCode = 1;
  } catch (err) {
    // Never echo the key: print the message only.
    console.error('request failed:', err?.message ?? err);
    process.exit(1);
  }
}
