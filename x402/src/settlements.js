/**
 * ArcKeeper x402 — settlement ledger.
 *
 * Append-only record of what the paywall actually charged, written next to
 * the snapshot in state/. The operator dashboard reads this; the paid routes
 * do not. A settlement that failed still gets a row (success: false) —
 * an audit trail that only records wins is marketing, not accounting.
 *
 * Writes are synchronous on purpose: request volume here is a trickle, and
 * a lost ledger row is worse than a few milliseconds of latency.
 */

import fs from 'node:fs';
import path from 'node:path';

export function settlementsPathFor(snapshotPath) {
  return path.join(path.dirname(snapshotPath), 'settlements.json');
}

export function createSettlementLedger(filePath) {
  /** @returns {Array} the raw rows, or [] when the file is absent/corrupt */
  function readRows() {
    try {
      const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      // Missing file = no sales yet. Corrupt file = keep the service selling
      // and let the ledger restart; the chain remains the source of truth.
      return [];
    }
  }

  function record(entry) {
    const rows = readRows();
    rows.push({
      at: new Date().toISOString(),
      ...entry,
    });
    const tmp = `${filePath}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(rows, null, 2));
    fs.renameSync(tmp, filePath);
    return rows.length;
  }

  /**
   * Most recent rows, newest first. `successOnly` drops failed attempts,
   * which is what a public revenue display wants; the dashboard's audit
   * table wants everything.
   */
  function read(limit = 20, { successOnly = false } = {}) {
    const rows = readRows();
    const filtered = successOnly ? rows.filter((r) => r.success) : rows;
    return filtered.slice(-limit).reverse();
  }

  /** Totals for the dashboard: per-tier sales count and USDC revenue. */
  function totals() {
    const rows = readRows().filter((r) => r.success);
    const byTier = {};
    let revenueUsdc = 0;
    for (const row of rows) {
      const tier = byTier[row.tier] ?? (byTier[row.tier] = { sales: 0, revenueUsdc: 0 });
      tier.sales += 1;
      const amount = Number(row.priceUsdc);
      if (Number.isFinite(amount)) {
        tier.revenueUsdc = Number((tier.revenueUsdc + amount).toFixed(6));
        revenueUsdc = Number((revenueUsdc + amount).toFixed(6));
      }
    }
    return { byTier, revenueUsdc, totalSales: rows.length };
  }

  return { record, read, totals };
}
