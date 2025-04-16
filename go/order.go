package main

import (
	"fmt"
	"os"
	"time"

	deltadefi "github.com/deltadefi-protocol/go-sdk"
	"github.com/lpernett/godotenv"
)

// func main() {
// 	order()
// }

func order() {
	godotenv.Load()
	config := deltadefi.ApiConfig{
		Network:           "staging",
		ApiKey:            os.Getenv("DELTADEFI_API_KEY"),
		OperationPasscode: os.Getenv("ENCRYPTION_PASSCODE"),
	}
	client := deltadefi.NewDeltaDeFi(config)

	buildPlaceOrderPayload := &deltadefi.BuildPlaceOrderTransactionRequest{
		Symbol:   "ADAUSDX",
		Side:     deltadefi.OrderSideSell,
		Type:     deltadefi.OrderTypeLimit,
		Quantity: 51.0,
		Price:    1.5,
	}
	buildPlaceOrderRes, _ := client.Order.BuildPlaceOrderTransaction(buildPlaceOrderPayload)
	fmt.Println("\nBuild Place Order Transaction:")
	fmt.Println(buildPlaceOrderRes)

	// Sign tx to be implemented by other Cardano infrastructure
	signedPlaceOrderTx := "signedTx"

	submitPlaceOrderPayload := &deltadefi.SubmitPlaceOrderTransactionRequest{
		OrderID:  buildPlaceOrderRes.OrderID,
		SignedTx: signedPlaceOrderTx,
	}
	submitPlaceOrderRes, _ := client.Order.SubmitPlaceOrderTransactionRequest(submitPlaceOrderPayload)
	fmt.Println("\nSubmit Place Order Transaction:")
	fmt.Println(submitPlaceOrderRes)

	// Sleep for 1s - make sure order is on book
	time.Sleep(1 * time.Second)

	buildCancelOrderRes, _ := client.Order.BuildCancelOrderTransaction(buildPlaceOrderRes.OrderID)
	fmt.Println("\nBuild Cancel Order Transaction:")
	fmt.Println(buildCancelOrderRes)

	// Sign tx to be implemented by other Cardano infrastructure
	signedCancelOrderTx := "signedTx"

	submitCancelOrderPayload := &deltadefi.SubmitCancelOrderTransactionRequest{
		SignedTx: signedCancelOrderTx,
	}
	submitCancelOrderRes, _ := client.Order.SubmitCancelOrderTransactionRequest(submitCancelOrderPayload)
	fmt.Println("\nSubmit Cancel Order Transaction:")
	fmt.Println(submitCancelOrderRes)
}
