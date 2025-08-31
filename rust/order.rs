use deltadefi::{DeltaDeFi, OrderSide, OrderType, Stage};
use dotenv::dotenv;
use std::env;

pub async fn order() {
    dotenv().ok();
    let api_key = env::var("DELTADEFI_API_KEY").expect("DELTADEFI_API_KEY must be set");
    let encryption_passcode =
        env::var("ENCRYPTION_PASSCODE").expect("ENCRYPTION_PASSCODE must be set");

    // Initialize DeltaDeFi client and wallet
    let mut deltadefi = DeltaDeFi::new(api_key, Stage::Staging, None).unwrap();
    deltadefi
        .load_operation_key(&encryption_passcode)
        .await
        .unwrap();

    // Build place order transaction
    let res = deltadefi
        .post_order(
            "ADAUSDM",
            OrderSide::Sell,
            OrderType::Limit,
            100.0,
            Some(51.0),
            Some(false),
            None,
        )
        .await
        .expect("Failed to post order");

    println!("\nPost order:\n{:?}", res);

    deltadefi
        .cancel_order(&res.order.order_id)
        .await
        .expect("Failed to cancel order");

    println!("\nCancel order successful\n");
}
