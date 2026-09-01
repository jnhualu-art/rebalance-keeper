/**
 * ArcKeeper x402 — payment-gated service (seller side).
 *
 * Sells the ArcKeeper treasury position behind an x402 paywall and settles
 * through an x402 facilitator.
 *
 * Audit properties:
 *   - Price is declared by this server in the 402 response. No part of the
 *     request can influence it.
 *   - Settlement runs only after the handler produced a successful body, so
 *     a failing handler never charges the caller.
 *   - The goods are checked *before* a price is quoted. A service that has
 *     nothing to sell must not invite a payment for it.
 *   - The seller needs no private key at all, only a payout address.
 *   - Unhandled errors return a generic body; internals are logged locally,
 *     never echoed to the caller.
 *
 * The position data itself is not read here. The Python agent publishes it as
 * a snapshot file (scripts/export_snapshot.py); this service only sells it.
 */

import http from 'node:http';

import {
  HTTPFacilitatorClient,
  x402HTTPResourceServer,
  x402ResourceServer,
} from '@x402/core/server';
import { registerExactEvmScheme } from '@x402/evm/exact/server';

import { loadConfig, redact } from './config.js';
import {
  SNAPSHOT_FAULTS,
  SnapshotError,
  buildSignalPayload,
  buildTreasuryPayload,
  loadSnapshot,
} from './snapshot.js';

const config = loadConfig();

if (!config.evm) {
  throw new Error(
    'EVM_PAY_TO is not set. This service needs an EVM payout address. ' +
      'Copy .env.example to .env and fill it in.',
  );
}

const facilitator = new HTTPFacilitatorClient({ url: config.service.facilitatorUrl });
const resourceServer = new x402ResourceServer(facilitator);
registerExactEvmScheme(resourceServer);

/**
 * The catalogue.
 *
 * Price and body builder are declared together on purpose: a route table that
 * lists prices separately from the code that produces the payload will
 * eventually charge one tier for another tier's data.
 */
export const TIERS = {
  '/signal': {
    priceUsdc: config.service.priceUsdc,
    build: buildSignalPayload,
    description: 'ArcKeeper treasury risk signal (zone + recommended action)',
  },
  '/treasury': {
    priceUsdc: config.service.treasuryPriceUsdc,
    build: buildTreasuryPayload,
    description: 'ArcKeeper full treasury position (balances, band, decision)',
  },
};

const routes = {};
for (const [routePath, tier] of Object.entries(TIERS)) {
  routes[`GET ${routePath}`] = {
    accepts: {
      scheme: 'exact',
      price: `$${tier.priceUsdc}`,
      network: config.evm.network,
      payTo: config.evm.payTo,
      // How long the signed authorization stays valid. It has to cover
      // verification *and* the facilitator's on-chain settlement, not just
      // this server's handling time. A window that is too short surfaces as a
      // rejected signature rather than as an obvious timeout.
      maxTimeoutSeconds: 600,
    },
    description: tier.description,
    mimeType: 'application/json',
  };
}

const paywalled = new x402HTTPResourceServer(resourceServer, routes);
await paywalled.initialize();

/**
 * Wrap a Node IncomingMessage in the adapter the x402 HTTP layer expects.
 * Header names are case-insensitive per RFC 9110, hence the lowercasing.
 */
function createAdapter(req) {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
  const header = (name) => {
    const value = req.headers[String(name).toLowerCase()];
    return Array.isArray(value) ? value[0] : value;
  };
  return {
    getHeader: header,
    getMethod: () => req.method ?? 'GET',
    getPath: () => url.pathname,
    getUrl: () => req.url ?? '/',
    getAcceptHeader: () => header('accept') ?? '',
    getUserAgent: () => header('user-agent') ?? '',
    getQueryParams: () => Object.fromEntries(url.searchParams.entries()),
    getQueryParam: (name) => url.searchParams.get(name) ?? undefined,
  };
}

function sendJson(res, status, payload, extraHeaders = {}) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(body),
    ...extraHeaders,
  });
  res.end(body);
}

/**
 * Refuse a request because the sellable data is not there.
 *
 * The reason goes to the log; the caller gets the status and a stable code.
 * Internal paths and filesystem errors stay local.
 */
function refuseWithoutStock(res, err) {
  const fault = SNAPSHOT_FAULTS[err?.reason] ?? SNAPSHOT_FAULTS.unreadable;
  console.error(`[server] refusing request (${fault.code}): ${err?.message ?? err}`);
  sendJson(
    res,
    fault.status,
    {
      error: fault.code,
      hint:
        fault.code === 'signal_stale'
          ? 'The published snapshot is older than the configured TTL. Re-run scripts/export_snapshot.py.'
          : 'No treasury snapshot is published yet. Run scripts/export_snapshot.py.',
    },
    { 'retry-after': '30' },
  );
}

async function handle(req, res) {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);

  if (req.method !== 'GET') {
    sendJson(res, 405, { error: 'method_not_allowed' }, { allow: 'GET' });
    return;
  }

  // Free and unmetered: lets a buyer (or a demo audience) see that the service
  // is up and what it charges, without paying for the privilege.
  if (url.pathname === '/health') {
    sendJson(res, 200, {
      status: 'ok',
      network: config.evm.network,
      tiers: Object.fromEntries(
        Object.entries(TIERS).map(([p, tier]) => [p, { priceUsdc: tier.priceUsdc }]),
      ),
      snapshotTtlSeconds: config.service.snapshotTtlSeconds,
    });
    return;
  }

  const tier = TIERS[url.pathname];
  if (!tier) {
    sendJson(res, 404, { error: 'not_found' });
    return;
  }

  // Check the goods before quoting a price. Doing it in this order means a
  // missing or stale snapshot can never reach the payment path at all, so
  // there is no settlement to skip and nothing to refund.
  let loaded;
  try {
    loaded = await loadSnapshot(config.service.snapshotPath, {
      ttlSeconds: config.service.snapshotTtlSeconds,
    });
  } catch (err) {
    if (err instanceof SnapshotError) {
      refuseWithoutStock(res, err);
      return;
    }
    throw err;
  }

  const context = {
    adapter: createAdapter(req),
    path: url.pathname,
    method: req.method,
    paymentHeader: req.headers['x-payment'],
  };

  const result = await paywalled.processHTTPRequest(context);

  if (result.type === 'payment-error') {
    // Diagnostics only: the reason the protocol layer refused the payment.
    // Never sent to the caller - a caller should not learn how to tune an
    // attack against verification.
    console.error(
      '[server] payment-error:',
      JSON.stringify(result, (_k, v) => (typeof v === 'function' ? '[fn]' : v)).slice(0, 1200),
    );
    // No or invalid payment: hand back the 402 the protocol layer built.
    const { status, headers, body } = result.response;
    res.writeHead(status, headers ?? {});
    res.end(typeof body === 'string' ? body : JSON.stringify(body ?? {}));
    return;
  }

  if (result.type === 'no-payment-required') {
    // This route is configured as paid, so reaching here means the route
    // table and the paywall disagree. Fail closed instead of serving free.
    console.error('[server] paid route served without payment; check route config');
    sendJson(res, 500, { error: 'route_misconfigured' });
    return;
  }

  const body = JSON.stringify(tier.build(loaded.snapshot));
  const headers = { 'content-type': 'application/json' };

  try {
    const settled = await paywalled.processSettlement(
      result.paymentPayload,
      result.paymentRequirements,
      result.declaredExtensions,
      { request: context, responseBody: Buffer.from(body), responseHeaders: headers },
    );
    const settleResponse = settled?.settleResponse ?? settled;
    if (settleResponse) {
      Object.assign(headers, paywalled.createSettlementHeaders(settleResponse));
    }
  } catch (err) {
    // The payer already proved payment, so serve the data and log loudly.
    // Withholding it would punish them for our facilitator's failure.
    console.error('[server] settlement failed:', err?.message ?? err);
  }

  res.writeHead(200, { ...headers, 'content-length': Buffer.byteLength(body) });
  res.end(body);
}

const server = http.createServer((req, res) => {
  handle(req, res).catch((err) => {
    console.error('[server] unhandled error:', err?.message ?? err);
    if (!res.headersSent) sendJson(res, 500, { error: 'internal_error' });
    else res.end();
  });
});

server.listen(config.service.port, () => {
  console.log('[server] config:', JSON.stringify(redact(config)));
  for (const [routePath, tier] of Object.entries(TIERS)) {
    console.log(
      `[server] selling http://localhost:${config.service.port}${routePath} for $${tier.priceUsdc}`,
    );
  }
});
