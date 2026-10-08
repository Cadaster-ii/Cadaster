/**
 * web/src/lib/stellar.ts
 *
 * Builds and submits the cadaster-token.mint() transaction via Freighter wallet.
 *
 * The Attestation struct fields and XDR encoding must exactly match the
 * Soroban contracttype.  We use @stellar/stellar-sdk's nativeToScVal helpers
 * to construct the ScMap that soroban-sdk's contracttype macro expects.
 */

import {
  Contract,
  Networks,
  SorobanRpc,
  TransactionBuilder,
  BASE_FEE,
  xdr,
  Address,
  scValToNative,
  nativeToScVal,
} from "@stellar/stellar-sdk";

const NETWORK = (process.env.NEXT_PUBLIC_STELLAR_NETWORK ?? "TESTNET") as
  | "TESTNET"
  | "PUBLIC";

const RPC_URL =
  process.env.NEXT_PUBLIC_SOROBAN_RPC_URL ??
  "https://soroban-testnet.stellar.org";

const TOKEN_CONTRACT_ID =
  process.env.NEXT_PUBLIC_TOKEN_CONTRACT_ID ?? "";

const NETWORK_PASSPHRASE =
  NETWORK === "TESTNET" ? Networks.TESTNET : Networks.PUBLIC;

// ── Attestation ScVal builder ─────────────────────────────────────────────────
//
// Soroban's `contracttype` macro serialises a struct as a sorted ScMap.
// Field order must match alphabetical order of field names.
//
// Attestation fields alphabetically:
//   asset_type, claim_hash, expiry, issued_at, nonce, score, verdict

function hexToBytes(hex: string): Buffer {
  return Buffer.from(hex, "hex");
}

function buildAttestationScVal(att: {
  claim_hash: string;
  asset_type: number;
  verdict: boolean;
  score: number;
  issued_at: number;
  expiry: number;
  nonce: string;
}): xdr.ScVal {
  // Build as ScMap with alphabetically sorted keys
  const entries: xdr.ScMapEntry[] = [
    new xdr.ScMapEntry({
      key: xdr.ScVal.scvSymbol("asset_type"),
      val: xdr.ScVal.scvU32(att.asset_type),
    }),
    new xdr.ScMapEntry({
      key: xdr.ScVal.scvSymbol("claim_hash"),
      val: xdr.ScVal.scvBytes(hexToBytes(att.claim_hash)),
    }),
    new xdr.ScMapEntry({
      key: xdr.ScVal.scvSymbol("expiry"),
      val: xdr.ScVal.scvU64(xdr.Uint64.fromString(att.expiry.toString())),
    }),
    new xdr.ScMapEntry({
      key: xdr.ScVal.scvSymbol("issued_at"),
      val: xdr.ScVal.scvU64(xdr.Uint64.fromString(att.issued_at.toString())),
    }),
    new xdr.ScMapEntry({
      key: xdr.ScVal.scvSymbol("nonce"),
      val: xdr.ScVal.scvBytes(hexToBytes(att.nonce)),
    }),
    new xdr.ScMapEntry({
      key: xdr.ScVal.scvSymbol("score"),
      val: xdr.ScVal.scvU32(att.score),
    }),
    new xdr.ScMapEntry({
      key: xdr.ScVal.scvSymbol("verdict"),
      val: xdr.ScVal.scvBool(att.verdict),
    }),
  ];

  return xdr.ScVal.scvMap(entries);
}

// ── mint() transaction ────────────────────────────────────────────────────────

export async function mintParcel(params: {
  walletAddress: string;
  signTransaction: (xdrStr: string) => Promise<string>;
  attestation: {
    claim_hash: string;
    asset_type: number;
    verdict: boolean;
    score: number;
    issued_at: number;
    expiry: number;
    nonce: string;
  };
  pubkey_hex: string;
  signature_hex: string;
}): Promise<{ txHash: string }> {
  if (!TOKEN_CONTRACT_ID) {
    throw new Error(
      "NEXT_PUBLIC_TOKEN_CONTRACT_ID is not set. Run the deploy script first."
    );
  }

  const server = new SorobanRpc.Server(RPC_URL, { allowHttp: false });

  // Load account
  const account = await server.getAccount(params.walletAddress);

  // Build the mint() invocation
  const contract = new Contract(TOKEN_CONTRACT_ID);

  const toScVal = Address.fromString(params.walletAddress).toScVal();
  const attestationScVal = buildAttestationScVal(params.attestation);
  const pubkeyScVal = xdr.ScVal.scvBytes(hexToBytes(params.pubkey_hex));
  const sigScVal = xdr.ScVal.scvBytes(hexToBytes(params.signature_hex));

  const tx = new TransactionBuilder(account, {
    fee: BASE_FEE,
    networkPassphrase: NETWORK_PASSPHRASE,
  })
    .addOperation(
      contract.call("mint", toScVal, attestationScVal, pubkeyScVal, sigScVal)
    )
    .setTimeout(60)
    .build();

  // Simulate to get the fee footprint
  const simResult = await server.simulateTransaction(tx);
  if (SorobanRpc.Api.isSimulationError(simResult)) {
    throw new Error(`Simulation failed: ${simResult.error}`);
  }

  const preparedTx = SorobanRpc.assembleTransaction(tx, simResult).build();
  const preparedXdr = preparedTx.toXDR();

  // Ask Freighter to sign
  const signedXdr = await params.signTransaction(preparedXdr);

  // Submit
  const submitResult = await server.sendTransaction(
    TransactionBuilder.fromXDR(signedXdr, NETWORK_PASSPHRASE)
  );

  if (submitResult.status === "ERROR") {
    throw new Error(`Transaction failed: ${submitResult.errorResult?.toXDR("base64")}`);
  }

  // Poll for finality
  let getResult = await server.getTransaction(submitResult.hash);
  let attempts = 0;
  while (
    getResult.status === SorobanRpc.Api.GetTransactionStatus.NOT_FOUND &&
    attempts < 15
  ) {
    await new Promise((r) => setTimeout(r, 2000));
    getResult = await server.getTransaction(submitResult.hash);
    attempts++;
  }

  if (getResult.status !== SorobanRpc.Api.GetTransactionStatus.SUCCESS) {
    throw new Error(
      `Transaction did not succeed: ${getResult.status}`
    );
  }

  return { txHash: submitResult.hash };
}
