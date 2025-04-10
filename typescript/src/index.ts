import { ApiClient } from "@deltadefi-protocol/typescript-sdk";
import { config } from "dotenv";
import {
  fetchAccountBalance,
  fetchDepositRecords,
  fetchWithdrawalRecords,
  fetchOrderRecords,
} from "./accounts";
import { fetchMarketDepth, fetchMarketPrice } from "./markets";
import { buildAndSignAndSubmitAndCancelLimitOrderTransaction } from "./orders";
import { AppWalletKeyType } from "@meshsdk/core";

// Load environment variables from .env
config();

const sdk_network = process.env.NETWORK;
const sdk_apiKey = process.env.API_KEY;
const signingKey: AppWalletKeyType = {
  type: "mnemonic",
  words: (process.env.MNEMONIC || "").split(",") || [],
};

// Validate environment variables
if (!sdk_network || !sdk_apiKey) {
  throw new Error("Missing required environment variables: NETWORK or API_KEY");
}

if (sdk_network !== "preprod" && sdk_network !== "mainnet") {
  throw new Error("Invalid NETWORK value. Expected 'preprod' or 'mainnet'.");
}

// Initialize the API client
const apiClient = new ApiClient({
  network: sdk_network as "preprod" | "mainnet",
  apiKey: sdk_apiKey,
  signingKey: signingKey,
});

// Call functions from accounts
async function accounts() {
  console.log("Starting calling accounts functions...");

  // Fetch account balance
  await fetchAccountBalance(apiClient);

  // Fetch deposit records
  await fetchDepositRecords(apiClient);

  // Fetch withdrawal records
  await fetchWithdrawalRecords(apiClient);

  // Fetch order data
  await fetchOrderRecords(apiClient);

  console.log("Stop calling accounts functions.");
}

// call functions from markets
async function markets() {
  console.log("Starting calling markets functions...");

  // Fetch market depth
  await fetchMarketDepth(apiClient);

  // Fetch market price
  await fetchMarketPrice(apiClient);

  console.log("Stop calling markets functions.");
}

// Call functions from orders
async function orders() {
  console.log("Starting calling orders functions...");

  // Build, sign, submit and cancel a limit order transaction
  await buildAndSignAndSubmitAndCancelLimitOrderTransaction(apiClient);

  console.log("Stop calling orders functions.");
}

async function main() {
  try {
    console.log("Starting SDK functions testing...");

    // await accounts();
    // await markets();
    await orders();

    console.log("SDK functions testing ends.");
  } catch (error) {
    console.error("Unhandled error in application:", error);
  }
}

// Execute the main function
main();
