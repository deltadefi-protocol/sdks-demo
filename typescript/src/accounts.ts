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

  try {
    const orderId = "054a0353-31fe-4575-ad06-927048288394"; // You should replace this with a real order ID
    const orderRecord = await apiClient.accounts.getOrderRecord(orderId);
    console.log("Order Record:", orderRecord);
  } catch (error) {
    console.error("Error fetching order record:", error);
    console.log(
      "Note: Replace 'your-order-id-here' with an actual order ID to fetch a specific order record."
    );
  }

  console.log();
};
