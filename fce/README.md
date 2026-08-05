# FlareKeeper — Flare Compute Extension (FCE)

FlareKeeper's confidential-rebalancer, packaged as a **Flare Compute Extension
(FCE)** for the [Flare Confidential Compute (FCC)](https://dev.flare.network/fcc/overview)
framework (Flare Summer Signal — Bounty 2: Confidential Compute Apps).

## What this proves (Bounty 2 thesis)

> The agent's *rebalancing strategy* runs **inside a TEE**. The strategy logic
> and treasury inputs stay private; only the signed decision leaves the enclave.
> Anyone can **verify on-chain** that a decision came from the approved build.

```
treasury snapshot ──► [ TEE: REBALANCE/COMPUTE handler ] ──► decision (JSON)
                                                    │ signs with TEE identity key
                                                    ▼
                                       TEE_ACTION_RESULT signature
                                                    │
                                            FlareKeeperVerifier (on-chain)
                                                    │ ecrecover == teeAddress
                                                    ▼
                                       execution is UNLOCKED
```

## Layout

```
fce/
  python/
    base/            # FCC framework (DO NOT MODIFY — matches dev.flare.network spec)
      server.py  node.py  types.py  encoding.py
    app/             # ★ FlareKeeper's customization
      config.py      # op-type / op-command identifiers (must match the Solidity constants)
      strategy.py    # the confidential brain — pure, self-contained evaluate()
      handlers.py    # REBALANCE/COMPUTE handler (decode→validate→execute→respond)
      tests/         # unit tests for the handler
    fce_sdk.py       # shared seam: run handler + TEE-sign (used by the agent loop)
    main.py  Dockerfile  requirements.txt
  contracts/
    FlareKeeperInstructionSender.sol   # sends REBALANCE instructions to the TEE
    FlareKeeperVerifier.sol            # ★ on-chain TEE-signature gate (P1)
    interfaces/                        # TeeExtensionRegistry / TeeMachineRegistry
  scripts/
    demo_confidential.py   # offline: confidential compute + TEE sign + verify
    deploy_coston2.py      # deploy FlareKeeperVerifier to Coston2 + on-chain verify
  config/
    proxy/extension_proxy.docker.toml          # local e2e (chain_id 31337)
    proxy/extension_proxy.coston2.docker.toml  # Coston2 (chain_id 114)
    extension.env                              # optional tee-node env
  docker-compose.yaml          # base (Python extension)
  docker-compose.coston2.yaml  # Coston2 override
  foundry.toml                 # forge config for contracts/
  .env.example                 # deployment env vars
```

## Run the confidential + verifiable demo (offline, no chain/keys)

```bash
pip install eth-utils eth-keys            # the fce/ python deps
python fce/scripts/demo_confidential.py
```

Output:
1. **CONFIDENTIAL COMPUTE** — the strategy runs inside the handler; only the
   decision (`{zone, action, amount, reason}`) is returned.
2. **TEE SIGNATURE** — the result is signed with the tee-node `TEE_ACTION_RESULT`
   scheme (keccak256(abi.encode("TEE_ACTION_RESULT", chainid, resultHash)) +
   EIP-191 + secp256k1).
3. **OFFLINE VERIFY** — the signer is recovered and compared to `teeAddress`.

## Run the FCE on Coston2 (Docker)

The runtime (tee-node `server` binary, ext-proxy, redis) is shared infrastructure
from the official `fce-extension-scaffold`. Build the base image once, then bring
up FlareKeeper's Python extension:

```bash
# 1. Build the shared tee-node base image (one-time, from the official scaffold)
git clone https://github.com/flare-foundation/fce-extension-scaffold flare-fce-scaffold
cd flare-fce-scaffold && ./scripts/build-node-base.sh && cd -

# 2. Configure + run FlareKeeper's extension on Coston2
cd rebalance-keeper/fce
cp .env.example .env            # set PROXY_PRIVATE_KEY / GOVERNANCE / EXT_PROXY_URL
docker compose -f docker-compose.yaml -f docker-compose.coston2.yaml up
```

The tee-node forwards `REBALANCE/COMPUTE` instructions to `fce/python/app/handlers.py`
(which runs `strategy.evaluate`), signs the decision with the **TEE identity key**
via the `TEE_ACTION_RESULT` scheme, and the result is verifiable on-chain by
`FlareKeeperVerifier`. Register the extension (governance + `TeeExtensionRegistry`)
with the scaffold's `extension-setup.sh` / `post-build.sh` tooling — they supply the
`TeeExtensionRegistry` / `TeeMachineRegistry` addresses and the tee-node binary.

## On-chain verify (Coston2)

```bash
export FLARE_PRIVATE_KEY=0x...      # funded Coston2 account (faucet: flare.network/coston2)
export FLARE_RPC_URL=https://coston2-api.flare.network/ext/C/rpc
python fce/scripts/demo_confidential.py --onchain
```

`deploy_coston2.py` compiles `FlareKeeperVerifier.sol` (standalone — no system
contract deps) and calls `verifyDecision()`, which runs the **identical**
`ecrecover` check on-chain. Execution of the rebalance is gated on a stored,
verified decision hash.

## Production deployment (real TEE)

`FlareKeeperInstructionSender` + `FlareKeeperVerifier` are registered as an FCE
via the official FCC tooling (the `fce-extension-scaffold` / `fce-sign` repos),
which supplies the `TeeExtensionRegistry` / `TeeMachineRegistry` addresses on
Coston2 and the tee-node binary. The handler code in `fce/python/app/` is
shipped as the enclave image unchanged; the TEE identity key is generated inside
the enclave and the real `TEE_ACTION_RESULT` signatures are produced by the
tee-node — making the on-chain verify path fully enforceable.

## Honesty note

The demo's TEE key is a **simulated** one (deterministic, for reproducibility).
The cryptography, handler code, contract interfaces, and verification scheme are
production-shaped and identical to what runs on Flare's hosted TEE machines; only
the key material differs in the local demo. The previously-shipped `sim:` hash
attestation (default mode) is clearly distinct from this enclave-signed path.
