import {
  ApiClient,
  decryptWithCipher,
} from "@deltadefi-protocol/typescript-sdk";
import { config } from "dotenv";
import {
  fetchAccountBalance,
  fetchDepositRecords,
  fetchWithdrawalRecords,
  fetchOrderRecords,
  fetchEncryptedOperationKey,
} from "./accounts";
import { AppWalletKeyType } from "@meshsdk/core";
import { fetchMarketDepth, fetchMarketPrice } from "./markets";
import { buildAndSignAndSubmitAndCancelLimitOrderTransaction } from "./orders";

// Load environment variables from .env
config();

const sdk_network = process.env.NETWORK;
const sdk_apiKey = process.env.API_KEY;
const sdk_operation_key_encryption_password =
  process.env.OPERATION_KEY_ENCRYPTION_PASSWORD;

// Validate environment variables
if (!sdk_network || !sdk_apiKey) {
  throw new Error(
    "Missing required environment variables: NETWORK, API_KEY, or WALLET_ADDRESS"
  );
}

if (sdk_network !== "preprod" && sdk_network !== "mainnet") {
  throw new Error("Invalid NETWORK value. Expected 'preprod' or 'mainnet'.");
}

/**
 * Fetch the encrypted_operation_key.
 */
async function retrieveEncryptedOperationKey(): Promise<string> {
  console.log("Starting retrieveEncryptedOperationKey...");

  // Temporarily initialize ApiClient without signingKey
  console.log("Initializing ApiClient without signingKey...");
  const apiClient = new ApiClient({
    network: sdk_network as "preprod" | "mainnet",
    apiKey: sdk_apiKey,
  });

  console.log(
    "ApiClient initialized. Proceeding to retrieve encrypted_operation_key"
  );

  try {
    const fetchOperationKeyResponse = await fetchEncryptedOperationKey(
      apiClient
    );

    if (!fetchOperationKeyResponse) {
      console.error(
        "fetchEncryptedOperationKey failed: Missing encrypted_operation_key in response."
      );
      throw new Error(
        "fetchEncryptedOperationKey failed: Missing encrypted_operation_key in response."
      );
    }

    console.log("Successfully retrieved encrypted_operation_key.");
    return fetchOperationKeyResponse;
  } catch (error) {
    console.error("Error during retrieving encrypted_operation_key:", error);
    throw error;
  }
}

/**
 * Decrypt the encrypted_operation_key.
 */
async function decryptOperationKey(
  encryptedOperationKey: string
): Promise<string> {
  if (!sdk_operation_key_encryption_password) {
    throw new Error(
      "Missing OPERATION_KEY_ENCRYPTION_PASSWORD environment variable."
    );
  }

  console.log("Decrypting encrypted_operation_key...");
  const decryptedOperationKey = await decryptWithCipher({
    encryptedDataJSON: encryptedOperationKey,
    key: sdk_operation_key_encryption_password,
  });

  return decryptedOperationKey;
}

/**
 * Initialize the ApiClient with signingKey.
 */
function initializeApiClientWithSigningKey(
  decryptedOperationKey: string
): ApiClient {
  const sdk_signingKey: AppWalletKeyType = {
    type: "root",
    bech32: decryptedOperationKey,
  };

  console.log("Initializing ApiClient with signingKey...");
  return new ApiClient({
    network: sdk_network as "preprod" | "mainnet",
    apiKey: sdk_apiKey,
    signingKey: sdk_signingKey,
  });
}

/**
 * Main function to execute all SDK functions.
 */
async function main() {
  try {
    console.log("Starting SDK functions testing...");

    // Step 1: Perform signIn to get encrypted_operation_key
    const encryptedOperationKey = await retrieveEncryptedOperationKey();

    // Step 2: Decrypt the encrypted_operation_key
    const decryptedOperationKey = await decryptOperationKey(
      encryptedOperationKey
    );

    // Step 3: Initialize ApiClient with signingKey
    const apiClient = initializeApiClientWithSigningKey(decryptedOperationKey);

    // Step 4: Call functions from accounts
    console.log("Starting calling accounts functions...");
    await fetchAccountBalance(apiClient);
    await fetchDepositRecords(apiClient);
    await fetchWithdrawalRecords(apiClient);
    await fetchOrderRecords(apiClient);
    console.log("Stop calling accounts functions.");

    // // Step 5: Call functions from markets
    console.log("Starting calling markets functions...");
    await fetchMarketDepth(apiClient);
    await fetchMarketPrice(apiClient);
    console.log("Stop calling markets functions.");

    // Step 6: Call functions from orders
    console.log("Starting calling orders functions...");
    await buildAndSignAndSubmitAndCancelLimitOrderTransaction(apiClient);
    console.log("Stop calling orders functions.");

    console.log("SDK functions testing ends.");
  } catch (error) {
    console.error("Unhandled error in application:", error);
  }
}

// Execute the main function
main();
