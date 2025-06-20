import { ApiClient } from "@deltadefi-protocol/typescript-sdk";
import {
  GetMarketDepthRequest,
  GetMarketPriceRequest,
} from "@deltadefi-protocol/typescript-sdk";

/**
 * Fetch market depth using the provided API client.
 * @param apiClient - The initialized API client.
 */
export async function fetchMarketDepth(apiClient: ApiClient) {
  // Prepare the request data
  const marketDepthRequest: GetMarketDepthRequest = {
    symbol: "ADAUSDM", // Replace with the trading symbol you want to query
  };

  // Call the getDepth function
  const marketDepthResponse = await apiClient.markets.getDepth(
    marketDepthRequest
  );

  // Log the market depth response
  console.log("Market Depth:", marketDepthResponse);
}

/**
 * Fetch market price using the provided API client.
 * @param apiClient - The initialized API client.
 */
export async function fetchMarketPrice(apiClient: ApiClient) {
  // Prepare the request data
  const marketPriceRequest: GetMarketPriceRequest = {
    symbol: "ADAUSDM", // Replace with the trading symbol you want to query
  };

  // Call the getPrice function
  const marketPriceResponse = await apiClient.markets.getMarketPrice(
    marketPriceRequest
  );

  // Log the market price response
  console.log("Market Price:", marketPriceResponse);
}
