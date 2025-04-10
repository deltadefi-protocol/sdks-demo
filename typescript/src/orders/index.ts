import {
  ApiClient,
  BuildPlaceOrderTransactionRequest,
} from "@deltadefi-protocol/typescript-sdk";

export async function buildAndSignAndSubmitAndCancelLimitOrderTransaction(
  apiClient: ApiClient
) {
  try {
    // Prepare the request data
    const orderRequest: BuildPlaceOrderTransactionRequest = {
      symbol: "ADAUSDX", // Replace with the trading symbol you want to query
      side: "sell", // "buy" or "sell"
      type: "limit", // "limit" or "market"
      quantity: 100, // Quantity in base units
      price: 0.62, // Price in quote units
    };

    // Build the order transaction
    const buildRes = await apiClient.orders.buildPlaceOrderTransaction(
      orderRequest
    );
    console.log("Build Order Response:", buildRes);

    const unsignedTx = buildRes.tx_hex;

    // Sign the order transaction
    const signedTx = await apiClient.wallet!.signTx(unsignedTx);
    console.log("Signed Transaction:", signedTx);

    const res = await apiClient.orders.submitPlaceOrderTransaction({
      order_id: buildRes.order_id,
      signed_tx: signedTx,
    });
    console.log("Submit Order Response:", res);

    // Cancel the order transaction
    const cancelRes = await apiClient.orders.buildCancelOrderTransaction(
      buildRes.order_id
    );
    console.log("Cancel Order Response:", cancelRes);

    const unsignedCancelTx = cancelRes.tx_hex;
    const signedCancelTx = await apiClient.wallet!.signTx(unsignedCancelTx);
    console.log("Signed Cancel Transaction:", signedCancelTx);

    const cancelRes2 = await apiClient.orders.submitCancelOrderTransaction({
      signed_tx: signedCancelTx,
    });
    console.log("Final Cancel Order Response:", cancelRes2);
  } catch (error: any) {
    if (error.response) {
      console.error("Error Response Data:", error.response.data);
      console.error("Error Response Status:", error.response.status);
      console.error("Error Response Headers:", error.response.headers);
    } else {
      console.error("Error Message:", error.message);
    }
    console.error(error.stack);
  }
}
