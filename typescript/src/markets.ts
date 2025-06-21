import {
  GetMarketDepthRequest,
  GetMarketPriceRequest,
} from "@deltadefi-protocol/sdk";
import { getApiClient } from ".";

export const markets = async () => {
  const apiClient = await getApiClient();

  const marketDepthRequest: GetMarketDepthRequest = {
    symbol: "ADAUSDM", // Replace with the trading symbol you want to query
  };

  const marketDepthResponse = await apiClient.markets.getDepth(
    marketDepthRequest
  );

  console.log("Market Depth:", marketDepthResponse);

  const marketPriceRequest: GetMarketPriceRequest = {
    symbol: "ADAUSDM", // Replace with the trading symbol you want to query
  };
  const marketPriceResponse = await apiClient.markets.getMarketPrice(
    marketPriceRequest
  );

  console.log("Market Price:", marketPriceResponse);
  console.log();
};
