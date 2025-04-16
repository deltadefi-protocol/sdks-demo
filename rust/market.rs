use deltadefi::{DeltaDeFi, Stage};
use dotenv::dotenv;
use std::env;

pub async fn market() {
    dotenv().ok();
    let api_key = env::var("DELTADEFI_API_KEY").expect("DELTADEFI_API_KEY must be set");
    let deltadefi = DeltaDeFi::new(api_key, Stage::Staging, None, None);

    // Get market depth
    let res = deltadefi.market.get_depth("ADAUSDX").await.unwrap();
    println!("\nGet market depth:\n{:?}", res);

    // Get market price
    let res = deltadefi.market.get_market_price("ADAUSDX").await.unwrap();
    println!("\nGet market price:\n{:?}", res);

    // Get aggregated price
    let start = 1_732_982_400; // Replace with your desired start timestamp
    let end = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("Time went backwards")
        .as_secs() as u64;
    let res = deltadefi
        .market
        .get_aggregated_price("ADAUSDX", "1M", start, end)
        .await
        .unwrap();
    println!("\nGet aggregated price:\n{:?}", res);
}
