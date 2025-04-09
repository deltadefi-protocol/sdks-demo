import { ApiClient } from "@deltadefi-protocol/typescript-sdk";

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
 * Fetch order records using the provided API client.
 * @param apiClient - The initialized API client.
 */
export async function fetchOrderRecords(apiClient: ApiClient) {
  // Call the getOrderRecords method
  const orderRecords = await apiClient.accounts.getOrderRecords();

  // Log the order records
  console.log("Order Records:", orderRecords);
}
