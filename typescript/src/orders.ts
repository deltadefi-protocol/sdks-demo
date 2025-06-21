import {
  ApiClient,
  BuildPlaceOrderTransactionRequest,
  PostOrderRequest,
} from "@deltadefi-protocol/sdk";
import { getApiClient } from ".";

export const orders = async () => {
  const apiClient = await getApiClient();

  const orderRequest: PostOrderRequest = {
    symbol: "ADAUSDM",
    side: "sell",
    type: "limit",
    quantity: 100,
    price: 16,
  };

  const res = await apiClient.postOrder(orderRequest);
  console.log("Post Order Response:", res);

  const cancelRes = await apiClient.cancelOrder(res.order.order_id);
  console.log("Cancel Order Response:", cancelRes);
  console.log();
};
