use deltadefi::{DeltaDeFi, Stage};
use dotenv::dotenv;
use std::env;

pub async fn accounts() {
    dotenv().ok();
    let api_key = env::var("DELTADEFI_API_KEY").unwrap();
    let deltadefi = DeltaDeFi::new(api_key, Stage::Staging, None).unwrap();

    let account_balance = deltadefi.accounts.get_account_balance().await.unwrap();
    println!("\nAccount Balance: {:?}", account_balance);

    let deposit_records = deltadefi.accounts.get_deposit_records().await.unwrap();
    println!("\nDeposit Records: {:?}", deposit_records);

    let withdrawal_records = deltadefi.accounts.get_withdrawal_records().await.unwrap();
    println!("\nWithdrawal Records: {:?}", withdrawal_records);

    let order_records = deltadefi
        .accounts
        .get_order_records(deltadefi::OrderRecordStatus::OpenOrder, None, None, None)
        .await
        .unwrap();
    println!("\nOrder Records: {:?}", order_records);

    let order_record = deltadefi
        .accounts
        .get_order_record(&order_records.data[0].orders[0].order_id)
        .await
        .unwrap();
    println!("\nOrder Record: {:?}", order_record);
}
