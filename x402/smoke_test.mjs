/**
 * Smoke test: verify scheme registration + config for both chains without
 * starting the HTTP server. Run with:
 *   node smoke_test.mjs                 # uses CHAIN from .env (default evm)
 *   CHAIN=hedera node smoke_test.mjs    # Hedera rail
 */
import { HTTPFacilitatorClient, x402ResourceServer } from '@x402/core/server';
import { ExactHederaScheme } from '@x402/hedera/exact/server';
import { loadConfig } from './src/config.js';

const config = loadConfig();
console.log(
  '[smoke] chain =', config.service.chain,
  '| network =', config.service.network,
  '| payTo =', config.service.payTo,
  '| asset =', config.service.asset,
  '| facilitator =', config.service.facilitatorUrl,
);

const facilitator = new HTTPFacilitatorClient({ url: config.service.facilitatorUrl });
const rs = new x402ResourceServer(facilitator);
console.log('[smoke] typeof resourceServer.register =', typeof rs.register);

if (config.service.chain === 'hedera') {
  rs.register(config.service.network, new ExactHederaScheme());
  console.log('[smoke] registered ExactHederaScheme on', config.service.network);
} else {
  const { registerExactEvmScheme } = await import('@x402/evm/exact/server');
  registerExactEvmScheme(rs);
  console.log('[smoke] registered EVM scheme');
}

console.log('[smoke] OK');
