/**
 * ArcKeeper x402 — payment-gated service (seller side).
 *
 * Serves a treasury risk signal behind an x402 paywall and settles through
 * the Blocky402 facilitator.
 *
 * Audit properties:
 *   - Price is declared by this server in the 402 response. No part of the
 *     request can influence it.
 *   - Settlement runs only after the handler produced a successful body, so
 *     a failing handler never charges the caller.
 *   - The seller needs no private key at all, only a payout address.
 *   - Unhandled errors return a generic body; internals are logged locally,
 *     never echoed to the caller.
 */

import http from 'node:http';

import {
  HTTPFacilitatorClient,
  x402HTTPResourceServer,
  x402ResourceServer,
} from '@x402/core/server';
import { registerExactEvmScheme } from '@x402/evm/exact/server';

import { loadConfig, redact } from './config.js';

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

const routes = {
  'GET /signal': {
    accepts: {
      scheme: 'exact',
      price: `$${config.service.priceUsdc}`,
      network: config.evm.network,
      payTo: config.evm.payTo,
      // How long the signed authorization stays valid. It has to cover
      // verification *and* the facilitator's on-chain settlement, not just
      // this server's handling time. A window that is too short surfaces as a
      // rejected signature rather than as an obvious timeout.
      maxTimeoutSeconds: 600,
    },
    description: 'ArcKeeper treasury risk signal',
    mimeType: 'application/json',
  },
};

const paywalled = new x402HTTPResourceServer(resourceServer, routes);
await paywalled.initialize();

/**
 * The protected payload.
 *
 * Kept pure so it can be unit-tested without a facilitator, a chain or a
 * network. Swap this for the real treasury read when wiring up ArcKeeper.
 */
export function buildSignal() {
  return {
    service: 'arckeeper-signal',
    generatedAt: new Date().toISOString(),
    treasury: {
      band: { floorUsdc: '50.00', ceilingUsdc: '75.00' },
      state: 'WARNING',
    },
    advice: 'REBALANCE',
    note: 'Served after a verified x402 payment.',
  };
}

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

async function handle(req, res) {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);

  if (req.method !== 'GET') {
    sendJson(res, 405, { error: 'method_not_allowed' }, { allow: 'GET' });
    return;
  }
  if (url.pathname !== '/signal') {
    sendJson(res, 404, { error: 'not_found' });
    return;
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

  const body = JSON.stringify(buildSignal());
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
  console.log(`[server] listening on http://localhost:${config.service.port}/signal`);
});
