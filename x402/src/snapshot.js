/**
 * ArcKeeper x402 — treasury snapshot loading and freshness checks.
 *
 * The Python agent owns the chain reads and the rebalance policy and publishes
 * its result as a JSON file. This module owns the consumer half of that
 * contract: read the file, prove it is well-formed, prove it is fresh.
 *
 * Why freshness is enforced here and not left to the caller: a paywall that
 * happily sells a three-day-old position is worse than one that refuses. The
 * buyer cannot tell the difference until it is too late, so the check has to
 * sit on the selling path.
 *
 * The parsing half is a pure function so it can be tested without touching the
 * filesystem; the reading half is a thin wrapper around it.
 */

import { readFile } from 'node:fs/promises';

// v2 added `last_action` (what the agent just did). v1 is still accepted:
// bumping the version must not turn an already-published file into a 503.
export const SUPPORTED_SCHEMAS = [
  'arckeeper-treasury-snapshot/1',
  'arckeeper-treasury-snapshot/2',
];
export const SNAPSHOT_SCHEMA = 'arckeeper-treasury-snapshot/2';
export const DEFAULT_TTL_SECONDS = 300;

export class SnapshotError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = 'SnapshotError';
    this.reason = options.reason ?? 'unreadable';
    this.detail = options.detail ?? null;
  }
}

/** Reasons the gateway can refuse to serve, mapped to HTTP status + code. */
export const SNAPSHOT_FAULTS = {
  missing: { status: 503, code: 'signal_unavailable' },
  unreadable: { status: 503, code: 'signal_unavailable' },
  malformed: { status: 503, code: 'signal_unavailable' },
  schema_mismatch: { status: 503, code: 'signal_unavailable' },
  stale: { status: 503, code: 'signal_stale' },
};

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * Validate a parsed snapshot document.
 *
 * Returns the snapshot on success. Throws SnapshotError on any problem, with a
 * `reason` the HTTP layer can map to a status code.
 */
export function parseSnapshot(document, { now = Date.now(), ttlSeconds = DEFAULT_TTL_SECONDS } = {}) {
  if (document === null || typeof document !== 'object' || Array.isArray(document)) {
    throw new SnapshotError('snapshot must be a JSON object', { reason: 'malformed' });
  }

  if (!SUPPORTED_SCHEMAS.includes(document.schema)) {
    throw new SnapshotError(
      `unsupported snapshot schema: expected one of ${SUPPORTED_SCHEMAS.join(', ')}, got ${String(document.schema)}`,
      { reason: 'schema_mismatch', detail: String(document.schema) },
    );
  }

  const treasury = document.treasury;
  if (!treasury || typeof treasury !== 'object') {
    throw new SnapshotError('snapshot is missing the treasury object', { reason: 'malformed' });
  }

  const decision = document.decision;
  if (!decision || typeof decision !== 'object') {
    throw new SnapshotError('snapshot is missing the decision object', { reason: 'malformed' });
  }

  if (!isFiniteNumber(treasury.usdc_balance)) {
    throw new SnapshotError('snapshot treasury.usdc_balance must be a number', {
      reason: 'malformed',
    });
  }
  if (typeof decision.zone !== 'string' || decision.zone === '') {
    throw new SnapshotError('snapshot decision.zone must be a non-empty string', {
      reason: 'malformed',
    });
  }

  const generatedAtMs = Date.parse(document.generated_at ?? '');
  if (Number.isNaN(generatedAtMs)) {
    throw new SnapshotError('snapshot generated_at must be an ISO-8601 timestamp', {
      reason: 'malformed',
    });
  }

  const ageSeconds = (now - generatedAtMs) / 1000;
  // A clock-skewed producer can push generated_at into the future. Tolerate a
  // small margin rather than treating every skewed write as permanently stale.
  if (ageSeconds > ttlSeconds) {
    throw new SnapshotError(
      `snapshot is ${Math.round(ageSeconds)}s old, ttl is ${ttlSeconds}s`,
      { reason: 'stale', detail: { ageSeconds, ttlSeconds } },
    );
  }

  return {
    snapshot: document,
    generatedAt: new Date(generatedAtMs).toISOString(),
    ageSeconds: Math.max(0, ageSeconds),
  };
}

/**
 * Read and validate the snapshot file.
 *
 * @param {string} path      absolute path to the published snapshot
 * @param {object} [options] { now, ttlSeconds, read }
 * @returns {Promise<{snapshot: object, generatedAt: string, ageSeconds: number}>}
 * @throws {SnapshotError} with a `reason` listed in SNAPSHOT_FAULTS
 */
export async function loadSnapshot(path, options = {}) {
  const { read = readFile } = options;
  let text;
  try {
    text = await read(path, 'utf8');
  } catch (err) {
    const missing = err?.code === 'ENOENT';
    throw new SnapshotError(`cannot read snapshot at ${path}: ${err?.message ?? err}`, {
      reason: missing ? 'missing' : 'unreadable',
    });
  }

  let document;
  try {
    document = JSON.parse(text);
  } catch (err) {
    throw new SnapshotError(`snapshot is not valid JSON: ${err?.message ?? err}`, {
      reason: 'malformed',
    });
  }

  return parseSnapshot(document, options);
}

/**
 * The cheap tier: what the position means, without the raw numbers.
 *
 * Deliberately lossy. If the advice were enough to reconstruct the full
 * position, nobody would ever buy the expensive tier.
 */
export function buildSignalPayload(snapshot) {
  const { decision, treasury, chain } = snapshot;
  return {
    service: 'arckeeper-signal',
    generatedAt: snapshot.generated_at,
    chain: chain?.name ?? null,
    zone: decision.zone,
    action: decision.action,
    amountUsdc: decision.amount_usdc ?? 0,
    advice: decision.reason ?? null,
    headroomUsdc:
      isFiniteNumber(treasury.ceiling_usdc) && isFiniteNumber(treasury.usdc_balance)
        ? Number((treasury.ceiling_usdc - treasury.usdc_balance).toFixed(6))
        : null,
    // Deliberately just the type and the outcome: whether the agent has acted
    // since the last reading is useful, the transaction details are what the
    // full tier is for.
    lastAction: snapshot.last_action
      ? { type: snapshot.last_action.type ?? null, status: snapshot.last_action.status ?? null }
      : null,
    servedAfter: 'verified x402 payment',
  };
}

/**
 * The full tier: everything the agent knows about the position.
 */
export function buildTreasuryPayload(snapshot) {
  return {
    service: 'arckeeper-treasury',
    generatedAt: snapshot.generated_at,
    chain: snapshot.chain ?? null,
    blockNumber: snapshot.block_number ?? null,
    wallet: snapshot.wallet ?? null,
    explorer: snapshot.explorer ?? null,
    treasury: snapshot.treasury ?? null,
    decision: snapshot.decision ?? null,
    // What the agent last did, including the transaction hash when there is
    // one. Absent on v1 snapshots, which predate the field.
    lastAction: snapshot.last_action ?? null,
    servedAfter: 'verified x402 payment',
  };
}
