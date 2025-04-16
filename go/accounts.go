package main

import (
	"fmt"
	"os"

	deltadefi "github.com/deltadefi-protocol/go-sdk"
	"github.com/lpernett/godotenv"
)

// func main() {
// 	accounts()
// }

func accounts() {
	godotenv.Load()
	config := deltadefi.ApiConfig{
		Network:           "staging",
		ApiKey:            os.Getenv("DELTADEFI_API_KEY"),
		OperationPasscode: os.Getenv("ENCRYPTION_PASSCODE"),
	}
	client := deltadefi.NewDeltaDeFi(config)

	accountBalanceRes, _ := client.Accounts.GetAccountBalance()
	fmt.Println("\nAccount Balance:")
	for _, record := range *accountBalanceRes {
		fmt.Println(record)
	}

	fmt.Println("\nDeposit Records:")
	depositRecordRes, _ := client.Accounts.GetDepositRecords()
	for _, record := range *depositRecordRes {
		fmt.Println(record)
	}

	fmt.Println("\nWithdrawal Records:")
	withdrawalRecordRes, _ := client.Accounts.GetWithdrawalRecords()
	for _, record := range *withdrawalRecordRes {
		fmt.Println(record)
	}

	fmt.Println("\nOrder Records:")
	orderRecordsRes, _ := client.Accounts.GetOrderRecords()
	fmt.Printf("Order Records: %v\n", orderRecordsRes)
	for _, record := range orderRecordsRes.Orders {
		fmt.Println(record)
	}
}
