/**
 * Diagnostic: find the EIP-712 domain parameters this USDC actually uses.
 *
 * The facilitator rejects our signature, and the on-chain contract exposes
 * DOMAIN_SEPARATOR() but reverts on authorizationState(). Rather than guess,
 * compute candidate domain separators locally and match against the value the
 * contract itself reports - the winner is the truth.
 *
 * Also recovers the signer from the payload we last produced, to distinguish
 * "our signature is wrong" from "the facilitator expects something else".
 *
 * Diagnostic only - delete once the happy path is green.
 */

import { createPublicClient, http, keccak256, toHex, encodeAbiParameters, parseAbiParameters, recoverTypedDataAddress } from 'viem';
import { baseSepolia } from 'viem/chains';

const USDC = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';
const RPC = 'https://sepolia.base.org';

const client = createPublicClient({ chain: baseSepolia, transport: http(RPC) });

// ---- 1. What does the contract say its domain is? ----
const onChain = await client.request({
  method: 'eth_call',
  params: [{ to: USDC, data: '0x3644e515' }, 'latest'],
});
console.log('on-chain DOMAIN_SEPARATOR :', onChain);

const DOMAIN_TYPE_HASH = keccak256(
  toHex('EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)'),
);

function domainSeparator(name, version, chainId, verifying) {
  return keccak256(
    encodeAbiParameters(parseAbiParameters('bytes32, bytes32, bytes32, uint256, address'), [
      DOMAIN_TYPE_HASH,
      keccak256(toHex(name)),
      keccak256(toHex(version)),
      BigInt(chainId),
      verifying,
    ]),
  );
}

console.log('\n-- candidate domains (chainId 84532) --');
let matched = null;
for (const name of ['USDC', 'USD Coin', 'USD Coin (Base Sepolia)', 'Base Sepolia USDC']) {
  for (const version of ['1', '2']) {
    const ds = domainSeparator(name, version, 84532, USDC);
    const hit = ds.toLowerCase() === onChain.toLowerCase();
    if (hit) matched = { name, version };
    console.log(`  name="${name}" version="${version}" -> ${ds}${hit ? '   *** MATCH ***' : ''}`);
  }
}

console.log(
  '\ndomain in use: ' + (matched ? `name="${matched.name}" version="${matched.version}"` : 'NONE MATCHED'),
);

// ---- 2. Does the signature we produced recover to the payer? ----
const authorization = {
  from: '0xe239cdc5fbe977a8a141B72194D3CF8c41bC5BC6',
  to: '0x1111111111111111111111111111111111111111',
  value: '1000',
  validAfter: '0',
  validBefore: '1788171835',
  nonce: '0xd38038c74b2f606f3f8b7b49e1732f2cd03d4e3dd9c09c9a3c3f0f214fe21620',
};
const signature =
  '0x8691909560ae535f4c20cde200052fab31698698c7805e7d455cb799307f6ebc575197cfc8b6136db3e4e0839ee3c38989d49d4c582622f32de4c20a1ee6ce661b';

const types = {
  TransferWithAuthorization: [
    { name: 'from', type: 'address' },
    { name: 'to', type: 'address' },
    { name: 'value', type: 'uint256' },
    { name: 'validAfter', type: 'uint256' },
    { name: 'validBefore', type: 'uint256' },
    { name: 'nonce', type: 'bytes32' },
  ],
};

console.log('\n-- signature recovery --');
for (const name of ['USDC', 'USD Coin']) {
  for (const version of ['2']) {
    const recovered = await recoverTypedDataAddress({
      domain: { name, version, chainId: 84532, verifyingContract: USDC },
      types,
      primaryType: 'TransferWithAuthorization',
      message: authorization,
      signature,
    });
    const ok = recovered.toLowerCase() === authorization.from.toLowerCase();
    console.log(
      `  name="${name}" v="${version}" -> ${recovered} ${ok ? '*** MATCHES payer ***' : '(not payer)'}`,
    );
  }
}

// ---- 3. EIP-3009 support, with correctly padded calldata ----
console.log('\n-- EIP-3009 / EIP-2612 support --');
const probe = async (label, data) => {
  try {
    const r = await client.request({ method: 'eth_call', params: [{ to: USDC, data }, 'latest'] });
    console.log(`  ${label.padEnd(34)} ok -> ${String(r).slice(0, 66)}`);
  } catch {
    console.log(`  ${label.padEnd(34)} revert -> not supported`);
  }
};

const word = (hex) => hex.replace(/^0x/, '').padStart(64, '0');
const zero32 = word('0x0');

await probe('authorizationState(addr,bytes32)', '0xd505accf' + word(authorization.from) + zero32);
await probe('nonces(address) [EIP-2612]', '0x7ecebe00' + word(authorization.from));
await probe('eip712Domain() [EIP-5267]', '0x84b0196e');
