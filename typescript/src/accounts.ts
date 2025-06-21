import { getApiClient } from ".";

export const accounts = async () => {
  const apiClient = await getApiClient();

  const accountBalance = await apiClient.accounts.getAccountBalance();
  console.log("Account Balance:", accountBalance);

  const depositRecords = await apiClient.accounts.getDepositRecords();
  console.log("Deposit Records:", depositRecords);

  const withdrawRecords = await apiClient.accounts.getWithdrawalRecords();
  console.log("Withdraw Records:", withdrawRecords);

  const orderRecords = await apiClient.accounts.getOrderRecords({
    status: "openOrder",
  });
  console.log("Open Order Records:", orderRecords);
  console.log();
};
