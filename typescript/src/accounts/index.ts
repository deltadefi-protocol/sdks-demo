import { ApiClient } from "@deltadefi-protocol/typescript-sdk";
import { config } from "dotenv";

// Load environment variables from .env
config();

export async function fetchEncryptedOperationKey(apiClient: ApiClient) {
  // Call the signIn method
  const getOperationKeyResponse = await apiClient.accounts.getOperationKey();

  return getOperationKeyResponse.encrypted_operation_key;
}

/**
 * Fetch account balance using the provided API client.
 * @param apiClient - The initialized API client.
 */
export async function fetchAccountBalance(apiClient: ApiClient) {
  // Call the getAccountBalance method
  const accountBalance = await apiClient.accounts.getAccountBalance();

  // Log the account balance
  console.log("Account Balance:", accountBalance);
}

/**
 * Fetch deposit records using the provided API client.
 * @param apiClient - The initialized API client.
 */
export async function fetchDepositRecords(apiClient: ApiClient) {
  // Call the getDepositRecords method
  const depositRecords = await apiClient.accounts.getDepositRecords();

  // Log the deposit records
  console.log("Deposit Records:", depositRecords);
}

/**
 * Fetch withdraw records using the provided API client.
 * @param apiClient - The initialized API client.
 */
export async function fetchWithdrawalRecords(apiClient: ApiClient) {
  // Call the getWithdrawRecords method
  const withdrawRecords = await apiClient.accounts.getWithdrawalRecords();

  // Log the withdraw records
  console.log("Withdraw Records:", withdrawRecords);
}

/**
 * Fetch open order records using the provided API client.
 * @param apiClient - The initialized API client.
 * @param limit - The number of records to fetch per page (between 1 and 250).
 * @param page - The page number to fetch (between 1 and 1000).
 */
export async function fetchOpenOrderRecords(
  apiClient: ApiClient,
  limit: number = 10,
  page: number = 1
) {
  console.log(
    `Fetching open order records with limit: ${limit}, page: ${page}`
  );

  // Validate parameters
  if (limit < 1 || limit > 250) {
    console.warn(`Invalid limit: ${limit}. Using default limit of 10.`);
    limit = 10;
  }

  if (page < 1 || page > 1000) {
    console.warn(`Invalid page: ${page}. Using default page of 1.`);
    page = 1;
  }

  try {
    // Call the getOrderRecords method with status 'openOrder'
    const orderRecords = await apiClient.accounts.getOrderRecords({
      status: "openOrder",
      limit,
      page,
    });

    // Log the open order records
    console.log("Open Order Records:", orderRecords);

    return orderRecords;
  } catch (error) {
    console.error("Error fetching open order records:", error);
    throw error;
  }
}

/**
 * Fetch order history records using the provided API client.
 * @param apiClient - The initialized API client.
 * @param limit - The number of records to fetch per page (between 1 and 250).
 * @param page - The page number to fetch (between 1 and 1000).
 */
export async function fetchOrderHistoryRecords(
  apiClient: ApiClient,
  limit: number = 10,
  page: number = 1
) {
  console.log(
    `Fetching order history records with limit: ${limit}, page: ${page}`
  );

  // Validate parameters
  if (limit < 1 || limit > 250) {
    console.warn(`Invalid limit: ${limit}. Using default limit of 10.`);
    limit = 10;
  }

  if (page < 1 || page > 1000) {
    console.warn(`Invalid page: ${page}. Using default page of 1.`);
    page = 1;
  }

  try {
    // Call the getOrderRecords method with status 'orderHistory'
    const orderRecords = await apiClient.accounts.getOrderRecords({
      status: "orderHistory",
      limit,
      page,
    });

    // Log the order history records
    console.log("Order History Records:", orderRecords);

    return orderRecords;
  } catch (error) {
    console.error("Error fetching order history records:", error);
    throw error;
  }
}

/**
 * Fetch trading history records using the provided API client.
 * @param apiClient - The initialized API client.
 * @param limit - The number of records to fetch per page (between 1 and 250).
 * @param page - The page number to fetch (between 1 and 1000).
 */
export async function fetchTradingHistoryRecords(
  apiClient: ApiClient,
  limit: number = 10,
  page: number = 1
) {
  console.log(
    `Fetching trading history records with limit: ${limit}, page: ${page}`
  );

  // Validate parameters
  if (limit < 1 || limit > 250) {
    console.warn(`Invalid limit: ${limit}. Using default limit of 10.`);
    limit = 10;
  }

  if (page < 1 || page > 1000) {
    console.warn(`Invalid page: ${page}. Using default page of 1.`);
    page = 1;
  }

  try {
    // Call the getOrderRecords method with status 'tradingHistory'
    const orderRecords = await apiClient.accounts.getOrderRecords({
      status: "tradingHistory",
      limit,
      page,
    });

    // Log the trading history records
    console.log("Trading History Records:", orderRecords);

    return orderRecords;
  } catch (error) {
    console.error("Error fetching trading history records:", error);
    throw error;
  }
}
