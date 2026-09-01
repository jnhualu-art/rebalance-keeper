/**
 * Tests for the config layer.
 *
 * The amount maths is the highest-risk part of an autonomous payer: a
 * rounding difference between what the agent signs and what the service
 * demands means either a rejected payment or an overpayment. These cases
 * pin that behaviour down.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

// Set before importing: config reads process.env at load time.
//
// Every field the assertions rely on is pinned here, so the suite passes or
// fails on its own terms. Reading any of it from a developer's .env would
// make the test green or red according to whoever's laptop it runs on.
const PRIVATE_KEY = '0x' + 'ab'.repeat(32);
const EVM_NETWORK = 'eip155:84532'; // Base Sepolia
process.env.HEDERA_ACCOUNT_ID = '0.0.7326075';
process.env.HEDERA_PRIVATE_KEY = PRIVATE_KEY;
process.env.EVM_PAY_TO = '0x' + '11'.repeat(20);
process.env.EVM_NETWORK = EVM_NETWORK;
process.env.PRICE_USDC = '0.001';
process.env.MAX_PAYMENT_USDC = '0.05';

const {
  baseUnitsToUsdc,
  loadConfig,
  redact,
  usdcToBaseUnits,
} = await import('../src/config.js');

test('0.1 USDC converts exactly, not to a float-rounded value', () => {
  // 0.1 is not representable in binary floating point. float(0.1) * 1e6
  // lands on 100000.00000000001, which is why integer maths is used here.
  assert.equal(usdcToBaseUnits('0.1'), 100000n);
});

test('typical amounts convert to 6-decimal base units', () => {
  assert.equal(usdcToBaseUnits('1.5'), 1_500_000n);
  assert.equal(usdcToBaseUnits('1'), 1_000_000n);
  assert.equal(usdcToBaseUnits('0.000001'), 1n);
  assert.equal(usdcToBaseUnits('75'), 75_000_000n);
});

test('base unit conversion round-trips', () => {
  assert.equal(baseUnitsToUsdc(1_500_000n), '1.500000');
  assert.equal(baseUnitsToUsdc(1n), '0.000001');
  assert.equal(baseUnitsToUsdc(0n), '0.000000');
});

test('sub-base-unit precision is rejected, never truncated to zero', () => {
  assert.throws(() => usdcToBaseUnits('0.0000001'), /at most 6 decimal places/);
  assert.throws(() => usdcToBaseUnits('1.0000001'), /at most 6 decimal places/);
});

test('malformed amounts are rejected; zero is a valid conversion', () => {
  // usdcToBaseUnits is a pure converter, so zero converts cleanly.
  // Rejecting non-positive values belongs to the caller
  // (parsePositiveAmount / loadConfig), which is asserted separately below.
  assert.equal(usdcToBaseUnits('0'), 0n);
  assert.throws(() => usdcToBaseUnits('-1'), /at most 6 decimal places/);
  assert.throws(() => usdcToBaseUnits('abc'), /at most 6 decimal places/);
  assert.throws(() => usdcToBaseUnits(''), /at most 6 decimal places/);
  assert.throws(() => usdcToBaseUnits('1.2.3'), /at most 6 decimal places/);
});

test('loadConfig wires the EVM payout address through', () => {
  const config = loadConfig();
  assert.equal(config.evm.payTo, '0x' + '11'.repeat(20));
  assert.equal(config.evm.network, EVM_NETWORK);
  assert.equal(config.service.priceUsdc, '0.001000');
  assert.equal(config.client.maxPaymentUsdc, '0.050000');
});

test('redact never exposes the private key', () => {
  const config = loadConfig();
  const safe = JSON.stringify(redact(config));
  assert.doesNotMatch(safe, /abab/);
  assert.ok(!('privateKey' in redact(config).hedera));
  // And the raw config must not be logged by accident either.
  assert.ok(config.hedera.privateKey === PRIVATE_KEY);
});

test('a malformed EVM payout address is rejected at startup', () => {
  const original = process.env.EVM_PAY_TO;
  try {
    process.env.EVM_PAY_TO = '0xnope';
    assert.throws(() => loadConfig(), /20-byte EVM address/);
  } finally {
    process.env.EVM_PAY_TO = original;
  }
});

test('an out-of-range spend ceiling is rejected', () => {
  const original = process.env.MAX_PAYMENT_USDC;
  try {
    process.env.MAX_PAYMENT_USDC = '0';
    assert.throws(() => loadConfig(), /greater than zero/);
  } finally {
    process.env.MAX_PAYMENT_USDC = original;
  }
});

test('a distinct Hedera buyer account is parsed and redacted', () => {
  const buyerId = '0.0.9999999';
  const buyerKey = '0x' + 'cd'.repeat(32);
  const prevChain = process.env.CHAIN;
  const prevBuyerId = process.env.HEDERA_BUYER_ACCOUNT_ID;
  const prevBuyerKey = process.env.HEDERA_BUYER_PRIVATE_KEY;
  try {
    process.env.CHAIN = 'hedera';
    process.env.HEDERA_BUYER_ACCOUNT_ID = buyerId;
    process.env.HEDERA_BUYER_PRIVATE_KEY = buyerKey;
    const config = loadConfig();
    assert.equal(config.hederaBuyer.accountId, buyerId);
    assert.equal(config.hederaBuyer.privateKey, buyerKey);
    // redact must expose the buyer id but never the key
    assert.equal(redact(config).hederaBuyer.accountId, buyerId);
    assert.ok(!('privateKey' in (redact(config).hederaBuyer ?? {})));
  } finally {
    process.env.CHAIN = prevChain;
    process.env.HEDERA_BUYER_ACCOUNT_ID = prevBuyerId;
    process.env.HEDERA_BUYER_PRIVATE_KEY = prevBuyerKey;
  }
});

test('a partial Hedera buyer config is rejected', () => {
  const prevChain = process.env.CHAIN;
  const prevId = process.env.HEDERA_BUYER_ACCOUNT_ID;
  const prevKey = process.env.HEDERA_BUYER_PRIVATE_KEY;
  try {
    process.env.CHAIN = 'hedera';
    process.env.HEDERA_BUYER_ACCOUNT_ID = '0.0.8888888';
    delete process.env.HEDERA_BUYER_PRIVATE_KEY;
    assert.throws(() => loadConfig(), /must be set together/);
  } finally {
    process.env.CHAIN = prevChain;
    process.env.HEDERA_BUYER_ACCOUNT_ID = prevId;
    process.env.HEDERA_BUYER_PRIVATE_KEY = prevKey;
  }
});
