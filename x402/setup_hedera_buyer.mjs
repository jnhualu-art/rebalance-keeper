// 创建独立的 Hedera testnet 买家账户，用于真实 x402 跨账户付款演示。
// 卖家仍是 .env 里的 HEDERA_ACCOUNT_ID；买家由本脚本生成并关联 USDC。
// 注意：USDC 余额需用户在 https://faucet.circle.com 选 "Hedera Testnet" 铸给买家账户。
import 'dotenv/config';
import { writeFileSync } from 'node:fs';
import {
  Client,
  PrivateKey,
  AccountId,
  AccountCreateTransaction,
  Hbar,
  TokenAssociateTransaction,
  TokenId,
} from '@hiero-ledger/sdk';

const USDC = '0.0.429274';

const operatorId = AccountId.fromString(process.env.HEDERA_ACCOUNT_ID);
const operatorKey = PrivateKey.fromStringECDSA(process.env.HEDERA_PRIVATE_KEY);
const client = Client.forTestnet().setOperator(operatorId, operatorKey);

const buyerKey = PrivateKey.generateECDSA();
const buyerPub = buyerKey.publicKey;

console.log('[1/3] creating buyer account (fund ~1 HBAR from seller)...');
const createTx = await new AccountCreateTransaction()
  .setKey(buyerPub)
  .setInitialBalance(new Hbar(1))
  .execute(client);
const createRc = await createTx.getReceipt(client);
const buyerId = createRc.accountId;
console.log('      buyer account =', buyerId.toString());

console.log('[2/3] associating USDC', USDC, 'to buyer...');
const assocTx = await new TokenAssociateTransaction()
  .setAccountId(buyerId)
  .setTokenIds([TokenId.fromString(USDC)])
  .freezeWith(client)
  .sign(buyerKey)
  .execute(client);
const assocRc = await assocTx.getReceipt(client);
console.log('      associate status =', assocRc.status.toString());

client.close();

const creds = {
  HEDERA_BUYER_ACCOUNT_ID: buyerId.toString(),
  HEDERA_BUYER_PRIVATE_KEY: buyerKey.toStringRaw(),
};
writeFileSync('state/hedera-buyer.json', JSON.stringify(creds, null, 2));
console.log('[3/3] saved to state/hedera-buyer.json');
console.log('');
console.log('NEXT: 打开 https://faucet.circle.com → 选 Hedera Testnet → 填账户', buyerId.toString());
console.log('       请求 USDC，等 20 USDC 到账后运行:');
console.log(
  `       HEDERA_BUYER_ACCOUNT_ID=${buyerId.toString()} HEDERA_BUYER_PRIVATE_KEY=${buyerKey.toStringRaw()} CHAIN=hedera node src/client.js /signal`,
);
