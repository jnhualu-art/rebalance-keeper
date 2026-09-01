/**
 * Tests for the snapshot contract — the file the Python agent publishes and
 * this service sells.
 *
 * These matter more than they look. The gateway takes money before it hands
 * over data, so every way the data can be missing, corrupt or old has to be a
 * refusal rather than a sale. A silent fall-through here would mean charging
 * an agent for a position that does not exist.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  SNAPSHOT_SCHEMA,
  SnapshotError,
  buildSignalPayload,
  buildTreasuryPayload,
  loadSnapshot,
  parseSnapshot,
} from '../src/snapshot.js';

const NOW = Date.parse('2026-09-01T12:00:00.000Z');

/** A snapshot exactly as scripts/export_snapshot.py writes it. */
function makeSnapshot(overrides = {}) {
  const base = {
    schema: SNAPSHOT_SCHEMA,
    generated_at: '2026-09-01T11:59:00.000Z', // 60s before NOW
    chain: { id: 5042002, name: 'Arc Testnet', explorer: 'https://testnet.arcscan.app' },
    block_number: 59885789,
    wallet: '0x57047A430c4cfe335674e6bAD81b4D5F68ff505c',
    explorer: 'https://testnet.arcscan.app/address/0x57047A430c4cfe335674e6bAD81b4D5F68ff505c',
    treasury: {
      usdc_balance: 74.998958,
      native_usdc_balance: 74.998958,
      floor_usdc: 50,
      ceiling_usdc: 75,
      health: 1.499979,
    },
    decision: { action: 'none', zone: 'WARNING', amount_usdc: 0, reason: 'Treasury healthy' },
  };
  if (overrides.treasury) {
    base.treasury = { ...base.treasury, ...overrides.treasury };
    delete overrides.treasury;
  }
  if (overrides.decision) {
    base.decision = { ...base.decision, ...overrides.decision };
    delete overrides.decision;
  }
  return { ...base, ...overrides };
}

test('a fresh, well-formed snapshot is accepted', () => {
  const { snapshot, ageSeconds } = parseSnapshot(makeSnapshot(), { now: NOW, ttlSeconds: 300 });
  assert.equal(snapshot.treasury.usdc_balance, 74.998958);
  assert.equal(Math.round(ageSeconds), 60);
});

test('age is measured against the injected clock, not wall time', () => {
  // Pins that no test outcome depends on when the suite happens to run.
  const { ageSeconds } = parseSnapshot(makeSnapshot(), { now: NOW, ttlSeconds: 300 });
  assert.ok(Math.abs(ageSeconds - 60) < 0.001);
});

test('a snapshot older than the ttl is refused as stale', () => {
  const old = makeSnapshot({ generated_at: '2026-09-01T11:00:00.000Z' }); // 1h
  assert.throws(
    () => parseSnapshot(old, { now: NOW, ttlSeconds: 300 }),
    (err) => err instanceof SnapshotError && err.reason === 'stale',
  );
});

test('the ttl boundary is inclusive at the ttl and stale beyond it', () => {
  const exactly = makeSnapshot({ generated_at: '2026-09-01T11:55:00.000Z' }); // 300s
  const justOver = makeSnapshot({ generated_at: '2026-09-01T11:54:59.000Z' }); // 301s
  assert.doesNotThrow(() => parseSnapshot(exactly, { now: NOW, ttlSeconds: 300 }));
  assert.throws(() => parseSnapshot(justOver, { now: NOW, ttlSeconds: 300 }), /stale|old/);
});

test('a clock-skewed future timestamp is tolerated rather than called stale', () => {
  // A producer whose clock runs ahead would otherwise be permanently unsellable.
  const future = makeSnapshot({ generated_at: '2026-09-01T12:05:00.000Z' });
  const { ageSeconds } = parseSnapshot(future, { now: NOW, ttlSeconds: 300 });
  assert.equal(ageSeconds, 0); // clamped, never negative
});

test('an unrecognised schema is refused instead of guessed at', () => {
  const doc = makeSnapshot({ schema: 'arckeeper-treasury-snapshot/2' });
  assert.throws(
    () => parseSnapshot(doc, { now: NOW }),
    (err) => err instanceof SnapshotError && err.reason === 'schema_mismatch',
  );
});

test('a missing or non-numeric balance is refused as malformed', () => {
  const missing = makeSnapshot({ treasury: { usdc_balance: undefined } });
  const text = makeSnapshot({ treasury: { usdc_balance: '74.99' } });
  for (const doc of [missing, text]) {
    assert.throws(
      () => parseSnapshot(doc, { now: NOW }),
      (err) => err instanceof SnapshotError && err.reason === 'malformed',
    );
  }
});

test('a missing or empty zone is refused as malformed', () => {
  const missing = makeSnapshot({ decision: { zone: undefined } });
  const empty = makeSnapshot({ decision: { zone: '' } });
  for (const doc of [missing, empty]) {
    assert.throws(
      () => parseSnapshot(doc, { now: NOW }),
      (err) => err instanceof SnapshotError && err.reason === 'malformed',
    );
  }
});

test('a missing or unparseable generated_at is refused as malformed', () => {
  const missing = makeSnapshot({ generated_at: undefined });
  const nonsense = makeSnapshot({ generated_at: 'not-a-timestamp' });
  for (const doc of [missing, nonsense]) {
    assert.throws(
      () => parseSnapshot(doc, { now: NOW }),
      (err) => err instanceof SnapshotError && err.reason === 'malformed',
    );
  }
});

test('non-object snapshots are refused', () => {
  for (const doc of [null, 42, 'text', ['a']]) {
    assert.throws(
      () => parseSnapshot(doc, { now: NOW }),
      (err) => err instanceof SnapshotError && err.reason === 'malformed',
    );
  }
});

test('a missing file is reported as missing, not as corrupt', () => {
  const enoent = Object.assign(new Error('nope'), { code: 'ENOENT' });
  const read = async () => {
    throw enoent;
  };
  return assert.rejects(
    () => loadSnapshot('/does/not/exist.json', { read, now: NOW }),
    (err) => err instanceof SnapshotError && err.reason === 'missing',
  );
});

test('unparseable JSON is reported as malformed', async () => {
  const read = async () => '{ not json';
  await assert.rejects(
    () => loadSnapshot('/x.json', { read, now: NOW }),
    (err) => err instanceof SnapshotError && err.reason === 'malformed',
  );
});

test('loadSnapshot returns the parsed document for a good file', async () => {
  const read = async () => JSON.stringify(makeSnapshot());
  const { snapshot } = await loadSnapshot('/x.json', { read, now: NOW });
  assert.equal(snapshot.decision.zone, 'WARNING');
});

test('the cheap tier carries the advice but not the raw position', () => {
  const payload = buildSignalPayload(makeSnapshot());
  assert.equal(payload.zone, 'WARNING');
  assert.equal(payload.action, 'none');
  assert.equal(payload.advice, 'Treasury healthy');
  // The point of the two tiers: buying the cheap one must not hand over the
  // position itself, or nobody would ever buy the expensive one.
  assert.equal(payload.treasury, undefined);
  assert.ok(!JSON.stringify(payload).includes('74.998958'));
});

test('headroom is the distance to the ceiling, rounded', () => {
  const payload = buildSignalPayload(makeSnapshot());
  // 75 - 74.998958 = 0.001042
  assert.equal(payload.headroomUsdc, 0.001042);
});

test('the full tier exposes the whole position and the decision', () => {
  const payload = buildTreasuryPayload(makeSnapshot());
  assert.equal(payload.treasury.usdc_balance, 74.998958);
  assert.equal(payload.treasury.floor_usdc, 50);
  assert.equal(payload.decision.zone, 'WARNING');
  assert.equal(payload.blockNumber, 59885789);
  assert.ok(payload.explorer.startsWith('https://'));
});

test('an infinite health ratio survives the JSON round-trip as null', () => {
  // Python cannot serialise Infinity, so export_snapshot.py writes null.
  // The payload builders must pass that through without choking.
  const doc = makeSnapshot({ treasury: { health: null } });
  const payload = buildTreasuryPayload(doc);
  assert.equal(payload.treasury.health, null);
  assert.doesNotThrow(() => buildSignalPayload(doc));
});
