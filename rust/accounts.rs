use deltadefi::{DeltaDeFi, Stage};
use dotenv::dotenv;
use std::env;

pub async fn accounts() {
    dotenv().ok();
    let api_key = env::var("DELTADEFI_API_KEY").unwrap();
    let deltadefi = DeltaDeFi::new(api_key, Stage::Staging, None, None);

    let account_balance = deltadefi.accounts.get_account_balance().await.unwrap();
    println!("Account Balance: {:?}", account_balance);

    let deposit_records = deltadefi.accounts.get_deposit_records().await.unwrap();
    println!("Deposit Records: {:?}", deposit_records);

    let withdrawal_records = deltadefi.accounts.get_withdrawal_records().await.unwrap();
    println!("Withdrawal Records: {:?}", withdrawal_records);

    let order_records = deltadefi.accounts.get_order_records().await.unwrap();
    println!("Order Records: {:?}", order_records);
}
