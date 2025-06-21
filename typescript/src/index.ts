import { ApiClient } from "@deltadefi-protocol/sdk";
import { config } from "dotenv";
import { accounts } from "./accounts";
import { markets } from "./markets";
import { orders } from "./orders";

// Load environment variables from .env
config();

export const getApiClient = async (): Promise<ApiClient> => {
  const network = process.env.NETWORK;
  const apiKey = process.env.API_KEY;
  const operationKeyEncryptionPassword =
    process.env.OPERATION_KEY_ENCRYPTION_PASSWORD!;

  const apiClient = new ApiClient({
    network: network as "preprod" | "mainnet",
    apiKey: apiKey,
  });

  await apiClient.loadOperationKey(operationKeyEncryptionPassword);
  return apiClient;
};

/**
 * Main function to execute all SDK functions.
 */
async function main() {
  console.log("Starting calling accounts functions...");
  await accounts();

  console.log("Starting calling markets functions...");
  await markets();

  console.log("Starting calling orders functions...");

  await orders();
  console.log("Stop calling orders functions.");
}

// Execute the main function
main();
