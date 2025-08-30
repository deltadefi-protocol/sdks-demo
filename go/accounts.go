package main

import (
	"fmt"
	"os"

	dd "github.com/deltadefi-protocol/go-sdk"
	"github.com/lpernett/godotenv"
)

func main() {
	accounts()
}

func accounts() {
	godotenv.Load()
	config := dd.ApiConfig{
		Network:           "staging",
		ApiKey:            os.Getenv("DELTADEFI_API_KEY"),
		OperationPasscode: os.Getenv("ENCRYPTION_PASSCODE"),
	}

	client := dd.NewDeltaDeFi(config)

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
	if len(*withdrawalRecordRes) == 0 {
		fmt.Println("No withdrawal records found")
	}
	for _, record := range *withdrawalRecordRes {
		fmt.Println(record)
	}

	fmt.Println("\nOrder Records:")
	orderRecordsRes, _ := client.Accounts.GetOrderRecords(&dd.GetOrderRecordRequest{Status: dd.OrderRecordStatusOpenOrder})
	for _, record := range orderRecordsRes.Data {
		fmt.Println(record)
	}

	fmt.Println("\nOrder Record for:", orderRecordsRes.Data[0].Orders[0].OrderID)
	orderRecordRes, _ := client.Accounts.GetOrderRecord(orderRecordsRes.Data[0].Orders[0].OrderID)
	fmt.Printf("Order Record: %v\n", orderRecordRes)

}
