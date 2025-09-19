import { GetMarketPriceRequest } from "@deltadefi-protocol/sdk";
import { getApiClient } from ".";

export const markets = async () => {
  const apiClient = await getApiClient();

  const marketPriceRequest: GetMarketPriceRequest = {
    symbol: "ADAUSDM", // Replace with the trading symbol you want to query
  };
  const marketPriceResponse = await apiClient.markets.getMarketPrice(
    marketPriceRequest
  );

  console.log("Market Price:", marketPriceResponse);
  console.log();
};
