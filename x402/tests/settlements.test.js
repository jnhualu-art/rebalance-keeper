import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { createSettlementLedger, settlementsPathFor } from '../src/settlements.js';

function tempLedger() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'arckeeper-ledger-'));
  return { ledger: createSettlementLedger(path.join(dir, 'settlements.json')), dir };
}

const sale = (over = {}) => ({
  tier: '/signal',
  priceUsdc: 0.001,
  success: true,
  transaction: '0x' + 'a'.repeat(64),
  network: 'eip155:84532',
  payer: '0x197cA46B3DF46F0E546213E670cd8490D8aB3ac0',
  errorReason: null,
  ...over,
});

test('settlementsPathFor drops the ledger next to the snapshot', () => {
  assert.equal(
    settlementsPathFor('/srv/x402/state/treasury-snapshot.json'),
    path.join('/srv/x402/state', 'settlements.json'),
  );
});

test('records append and read back newest first', () => {
  const { ledger } = tempLedger();
  ledger.record(sale({ tier: '/signal' }));
  ledger.record(sale({ tier: '/treasury', priceUsdc: 0.005 }));
  const rows = ledger.read();
  assert.equal(rows.length, 2);
  assert.equal(rows[0].tier, '/treasury', 'newest row comes first');
  assert.equal(rows[1].tier, '/signal');
  assert.ok(rows[0].at, 'each row carries a timestamp');
});

test('read(limit) caps and orders the window', () => {
  const { ledger } = tempLedger();
  for (let i = 0; i < 5; i += 1) ledger.record(sale({ tier: `/r${i}` }));
  const rows = ledger.read(2);
  assert.deepEqual(rows.map((r) => r.tier), ['/r4', '/r3']);
});

test('failed settlements are recorded, not erased', () => {
  const { ledger } = tempLedger();
  ledger.record(sale());
  ledger.record(sale({ success: false, transaction: null, errorReason: 'insufficient_funds' }));

  assert.equal(ledger.read().length, 2, 'audit view keeps both');
  assert.equal(ledger.read(undefined, { successOnly: true }).length, 1, 'revenue view drops failures');
  assert.equal(ledger.read(undefined, { successOnly: true })[0].errorReason, null);
});

test('totals aggregate sales and revenue per tier', () => {
  const { ledger } = tempLedger();
  ledger.record(sale({ tier: '/signal', priceUsdc: 0.001 }));
  ledger.record(sale({ tier: '/signal', priceUsdc: 0.001 }));
  ledger.record(sale({ tier: '/treasury', priceUsdc: 0.005 }));
  ledger.record(sale({ tier: '/treasury', priceUsdc: 0.005, success: false }));

  const totals = ledger.totals();
  assert.equal(totals.totalSales, 3, 'the failed row is not a sale');
  assert.equal(totals.revenueUsdc, 0.007);
  assert.equal(totals.byTier['/signal'].sales, 2);
  assert.equal(totals.byTier['/treasury'].revenueUsdc, 0.005);
});

test('a corrupt or missing ledger degrades to empty, not to a crash', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'arckeeper-ledger-'));
  const file = path.join(dir, 'settlements.json');
  fs.writeFileSync(file, '{not json at all');
  const ledger = createSettlementLedger(file);

  assert.deepEqual(ledger.read(), []);
  assert.deepEqual(ledger.totals(), { byTier: {}, revenueUsdc: 0, totalSales: 0 });
  // And the next successful sale starts a clean file.
  ledger.record(sale());
  assert.deepEqual(JSON.parse(fs.readFileSync(file, 'utf8')), [
    { at: ledger.read()[0].at, ...sale() },
  ]);
});
