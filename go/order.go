package main

import (
	"fmt"
	"os"
	"time"

	dd "github.com/deltadefi-protocol/go-sdk"
	"github.com/lpernett/godotenv"
)

func main() {
	order()
}

func order() {
	godotenv.Load()
	config := dd.ApiConfig{
		Network:           "staging",
		ApiKey:            os.Getenv("DELTADEFI_API_KEY"),
		OperationPasscode: os.Getenv("ENCRYPTION_PASSCODE"),
	}
	client := dd.NewDeltaDeFi(config)
	client.LoadOperationKey(config.OperationPasscode)

	orderPayload := &dd.BuildPlaceOrderTransactionRequest{
		Symbol:   "ADAUSDM",
		Side:     dd.OrderSideSell,
		Type:     dd.OrderTypeLimit,
		Quantity: 51.0,
		Price:    dd.FloatPtr(1.5),
	}
	postOrderRes, _ := client.PostOrder(orderPayload)
	fmt.Println("\nPost sell limit order:")
	fmt.Println(postOrderRes)

	// Sleep for 1s - make sure order is on book
	time.Sleep(1 * time.Second)

	client.CancelOrder(postOrderRes.Order.OrderID)
	fmt.Println("\nCancel Order Successful")
}
