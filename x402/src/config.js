/**
 * ArcKeeper x402 — configuration loading, validation and amount math.
 *
 * Rules this file exists to enforce:
 *   1. Secrets come from the environment only. Nothing is hardcoded and
 *      nothing defaults to a credential that actually works.
 *   2. Validation fails loudly at startup, so a malformed account id or a
 *      placeholder key never reaches the signing path.
 *   3. Amounts are parsed with integer math, never floats.
 *   4. A redacted view is exported for logging; never log loadConfig() output.
 */

import path from 'node:path';
import { fileURLToPath } from 'node:url';

import 'dotenv/config';

const HEDERA_ACCOUNT_RE = /^\d+\.\d+\.\d+$/;
const EVM_ADDRESS_RE = /^0x[a-fA-F0-9]{40}$/;
const USDC_DECIMALS = 6;
const USDC_SCALE = 10n ** BigInt(USDC_DECIMALS);

// Default location of the snapshot published by scripts/export_snapshot.py.
// Resolved against this file so the service works from any working directory.
const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_SNAPSHOT_PATH = path.join(MODULE_DIR, '..', 'state', 'treasury-snapshot.json');

export class ConfigError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ConfigError';
  }
}

function requireEnv(name) {
  const raw = process.env[name];
  if (raw === undefined || String(raw).trim() === '') {
    throw new ConfigError(
      `Missing required environment variable: ${name}. ` +
        `Copy .env.example to .env and fill it in.`,
    );
  }
  return String(raw).trim();
}

/**
 * Parse a USDC amount into 6-decimal base units using integer math.
 *
 * Floats cannot represent 0.1 exactly, and an autonomous agent that rounds a
 * payment differently from the service gets rejected or overpays. Sub-unit
 * precision is rejected rather than silently truncated.
 */
export function usdcToBaseUnits(raw, label = 'amount') {
  const text = String(raw).trim();
  const match = /^(\d+)(?:\.(\d{1,6}))?$/.exec(text);
  if (!match) {
    throw new ConfigError(
      `${label} must be a positive decimal with at most ${USDC_DECIMALS} ` +
        `decimal places, got "${raw}"`,
    );
  }
  const whole = match[1];
  const fraction = (match[2] ?? '').padEnd(USDC_DECIMALS, '0');
  return BigInt(whole) * USDC_SCALE + BigInt(fraction);
}

export function baseUnitsToUsdc(units) {
  const value = BigInt(units);
  const whole = value / USDC_SCALE;
  const fraction = (value % USDC_SCALE).toString().padStart(USDC_DECIMALS, '0');
  return `${whole}.${fraction}`;
}

function parsePositiveAmount(raw, label) {
  const units = usdcToBaseUnits(raw, label);
  if (units <= 0n) {
    throw new ConfigError(`${label} must be greater than zero, got "${raw}"`);
  }
  return units;
}

function parsePort(raw) {
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new ConfigError(`SERVICE_PORT must be an integer 1-65535, got "${raw}"`);
  }
  return port;
}

function parseTimeout(raw) {
  const ms = Number(raw);
  if (!Number.isInteger(ms) || ms < 1000 || ms > 120_000) {
    throw new ConfigError(`CLIENT_TIMEOUT_MS must be 1000-120000, got "${raw}"`);
  }
  return ms;
}

/**
 * How old a published snapshot may be before the gateway refuses to sell it.
 * Selling a stale position is worse than refusing, so the default is tight and
 * the value is validated rather than silently coerced.
 */
function parseTtlSeconds(raw) {
  const seconds = Number(raw);
  if (!Number.isInteger(seconds) || seconds < 10 || seconds > 86_400) {
    throw new ConfigError(
      `SNAPSHOT_TTL_SECONDS must be an integer 10-86400, got "${raw}"`,
    );
  }
  return seconds;
}

function assertAccountId(value, label) {
  if (!HEDERA_ACCOUNT_RE.test(value)) {
    throw new ConfigError(
      `${label} must look like shard.realm.num (e.g. 0.0.7326075), got "${value}"`,
    );
  }
  return value;
}

function assertEvmAddress(value, label) {
  if (!EVM_ADDRESS_RE.test(value)) {
    throw new ConfigError(
      `${label} must be a 20-byte EVM address (0x + 40 hex), got "${value}"`,
    );
  }
  return value;
}

export function loadConfig() {
  const accountId = assertAccountId(requireEnv('HEDERA_ACCOUNT_ID'), 'HEDERA_ACCOUNT_ID');

  const privateKey = requireEnv('HEDERA_PRIVATE_KEY');
  if (/^0x0{64}$/.test(privateKey)) {
    throw new ConfigError(
      'HEDERA_PRIVATE_KEY is still the placeholder from .env.example. Refusing to start.',
    );
  }

  const network = process.env.HEDERA_NETWORK?.trim() || 'hedera:testnet';
  if (network !== 'hedera:testnet' && network !== 'hedera:mainnet') {
    throw new ConfigError(
      `HEDERA_NETWORK must be hedera:testnet or hedera:mainnet, got "${network}"`,
    );
  }

  const payTo = assertAccountId(
    process.env.PAY_TO?.trim() || accountId,
    'PAY_TO',
  );

  const priceUnits = parsePositiveAmount(process.env.PRICE_USDC ?? '0.001', 'PRICE_USDC');
  // The full position costs more than the advice. A single flat price would
  // leave money on the table and give buyers no reason to prefer the cheap tier.
  const treasuryPriceUnits = parsePositiveAmount(
    process.env.PRICE_TREASURY_USDC ?? '0.005',
    'PRICE_TREASURY_USDC',
  );
  const maxPaymentUnits = parsePositiveAmount(
    process.env.MAX_PAYMENT_USDC ?? '0.05',
    'MAX_PAYMENT_USDC',
  );

  return {
    hedera: { accountId, privateKey, network },
    // EVM verification path. A Hedera ECDSA key is an secp256k1 key, so it
    // signs EVM transactions unchanged; only the payout address differs.
    // Left null when EVM_PAY_TO is unset so Hedera-only runs still boot.
    evm: process.env.EVM_PAY_TO?.trim()
      ? {
          privateKey,
          rpcUrl: process.env.EVM_RPC_URL?.trim() || 'https://rpc-amoy.polygon.technology',
          network: process.env.EVM_NETWORK?.trim() || 'eip155:80002',
          payTo: assertEvmAddress(process.env.EVM_PAY_TO.trim(), 'EVM_PAY_TO'),
        }
      : null,
    service: {
      port: parsePort(process.env.SERVICE_PORT ?? '3402'),
      // Kept as the cheap-tier price: PRICE_USDC is the historical name and
      // existing tests assert against it.
      priceUnits,
      priceUsdc: baseUnitsToUsdc(priceUnits),
      treasuryPriceUnits,
      treasuryPriceUsdc: baseUnitsToUsdc(treasuryPriceUnits),
      snapshotPath: process.env.SNAPSHOT_PATH?.trim() || DEFAULT_SNAPSHOT_PATH,
      snapshotTtlSeconds: parseTtlSeconds(process.env.SNAPSHOT_TTL_SECONDS ?? '300'),
      payTo,
      facilitatorUrl: process.env.FACILITATOR_URL?.trim() || 'https://blocky402.com',
    },
    client: {
      maxPaymentUnits,
      maxPaymentUsdc: baseUnitsToUsdc(maxPaymentUnits),
      timeoutMs: parseTimeout(process.env.CLIENT_TIMEOUT_MS ?? '30000'),
    },
  };
}

/**
 * Log-safe projection of the config. Use this for console output, audit
 * trails and error reports; it cannot leak the private key.
 */
export function redact(config) {
  return {
    hedera: { accountId: config.hedera.accountId, network: config.hedera.network },
    service: {
      port: config.service.port,
      priceUsdc: config.service.priceUsdc,
      treasuryPriceUsdc: config.service.treasuryPriceUsdc,
      snapshotPath: config.service.snapshotPath,
      snapshotTtlSeconds: config.service.snapshotTtlSeconds,
      payTo: config.service.payTo,
      facilitatorUrl: config.service.facilitatorUrl,
    },
    client: {
      maxPaymentUsdc: config.client.maxPaymentUsdc,
      timeoutMs: config.client.timeoutMs,
    },
  };
}
