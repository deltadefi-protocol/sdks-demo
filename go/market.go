package main

import (
	"fmt"
	"os"
	"time"

	deltadefi "github.com/deltadefi-protocol/go-sdk"
	"github.com/lpernett/godotenv"
)

// func main() {
// 	market()
// }

func market() {
	godotenv.Load()
	config := deltadefi.ApiConfig{
		Network:           "staging",
		ApiKey:            os.Getenv("DELTADEFI_API_KEY"),
		OperationPasscode: os.Getenv("ENCRYPTION_PASSCODE"),
	}
	client := deltadefi.NewDeltaDeFi(config)

	fmt.Println("\nMarket Price:")
	marketPriceRes, _ := client.Market.GetMarketPrice("ADAUSDM")
	fmt.Println(marketPriceRes.Price)

	fmt.Println("\nAggregated Price:")
	// Get aggregated price
	start := int64(1732982400) // Replace with your desired start timestamp
	end := time.Now().Unix()   // Current Unix timestamp
	payload := &deltadefi.GetAggregatedPriceRequest{
		Symbol:   "ADAUSDM",
		Interval: "1d",
		Start:    start,
		End:      end,
	}
	aggregatedPriceRes, _ := client.Market.GetAggregatedPrice(payload)
	for _, record := range *aggregatedPriceRes {
		fmt.Println(record)
	}
}
