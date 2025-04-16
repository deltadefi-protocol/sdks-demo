package main

import (
	"fmt"
	"os"
	"time"

	deltadefi "github.com/deltadefi-protocol/go-sdk"
	"github.com/lpernett/godotenv"
)

func main() {
	market()
}

func market() {
	godotenv.Load()
	config := deltadefi.ApiConfig{
		Network:           "staging",
		ApiKey:            os.Getenv("DELTADEFI_API_KEY"),
		OperationPasscode: os.Getenv("ENCRYPTION_PASSCODE"),
	}
	client := deltadefi.NewDeltaDeFi(config)

	marketDepthRes, _ := client.Market.GetDepth("ADAUSDX")
	fmt.Println("\nMarket Depth:")
	fmt.Println("Asks:")
	for _, record := range marketDepthRes.Asks {
		fmt.Println(record)
	}
	fmt.Println("Bids:")
	for _, record := range marketDepthRes.Bids {
		fmt.Println(record)
	}

	fmt.Println("\nMarket Price:")
	marketPriceRes, _ := client.Market.GetMarketPrice("ADAUSDX")
	fmt.Println(marketPriceRes.Price)

	fmt.Println("\nAggregated Price:")
	// Get aggregated price
	start := int64(1732982400) // Replace with your desired start timestamp
	end := time.Now().Unix()   // Current Unix timestamp
	payload := &deltadefi.GetAggregatedPriceRequest{
		Symbol:   "ADAUSDX",
		Interval: "1M",
		Start:    start,
		End:      end,
	}
	aggregatedPriceRes, _ := client.Market.GetAggregatedPrice(payload)
	for _, record := range *aggregatedPriceRes {
		fmt.Println(record)
	}
}
