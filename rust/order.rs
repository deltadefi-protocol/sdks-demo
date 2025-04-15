use deltadefi::{DeltaDeFi, OrderSide, OrderType, Stage};
use dotenv::dotenv;
use std::env;
use whisky::{decrypt_with_cipher, Wallet};

pub async fn order() {
    dotenv().ok();
    let api_key = env::var("DELTADEFI_API_KEY").expect("DELTADEFI_API_KEY must be set");
    let encryption_passcode =
        env::var("ENCRYPTION_PASSCODE").expect("ENCRYPTION_PASSCODE must be set");

    // Initialize DeltaDeFi client and wallet
    let deltadefi = DeltaDeFi::new(api_key, Stage::Staging, None);

    let res = deltadefi.accounts.get_operation_key().await.unwrap();
    let encrypted_operation_key = res.encrypted_operation_key;
    let decrypted_operation_key =
        decrypt_with_cipher(&encrypted_operation_key, &encryption_passcode).unwrap();
    let wallet = Wallet::new(whisky::WalletType::Root(decrypted_operation_key), 0, 0);

    // Build place order transaction
    let res = deltadefi
        .order
        .build_place_order_transaction(
            "ADAUSDX",
            OrderSide::Sell,
            OrderType::Limit,
            51.0,
            Some(1.5),
            None,
            None,
        )
        .await
        .expect("Failed to build place order transaction");

    println!("\nBuild place order transaction:\n{:?}", res);

    let order_id = res.order_id;
    let tx_hex = res.tx_hex;
    let signed_tx = wallet.sign_tx(&tx_hex).unwrap();

    println!("\nSigned transaction hex: {}", signed_tx);

    // Submit place order transaction
    let res = deltadefi
        .order
        .submit_place_order_transaction(&order_id, &signed_tx)
        .await
        .expect("Failed to submit place order transaction");

    println!("\nSubmit place order transaction:");
    println!("Order submitted successfully: {:?}", res);

    // Uncomment the following lines to cancel the order after submission
    tokio::time::sleep(std::time::Duration::from_secs(1)).await;

    let order_id = "012d72b5-4b6a-4e7b-90a8-d0d65e6d4f84";
    let res = deltadefi
        .order
        .build_cancel_order_transaction(order_id)
        .await
        .expect("Failed to build cancel order transaction");

    println!("\nBuild cancel order transaction:\n{:?}", res);

    let tx_hex = res.tx_hex;
    let signed_tx = wallet.sign_tx(&tx_hex).unwrap();

    let res = deltadefi
        .order
        .submit_cancel_order_transaction(&signed_tx)
        .await
        .expect("Failed to submit cancel order transaction");

    println!("\nSubmit cancel order transaction:");
    println!("Order canceled successfully: {:?}", res);
}
