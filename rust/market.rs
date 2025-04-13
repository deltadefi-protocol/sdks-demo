use deltadefi::{DeltaDeFi, Stage};
use dotenv::dotenv;
use std::env;

pub async fn market() {
    dotenv().ok();
    let api_key = env::var("DELTADEFI_API_KEY").expect("DELTADEFI_API_KEY must be set");
    let deltadefi = DeltaDeFi::new(api_key, Stage::Staging, None);

    // Get market depth
    match deltadefi.market.get_depth("ADAUSDX").await {
        Ok(depth) => println!("\nGet depth:\n{:?}", depth),
        Err(err) => eprintln!("Error getting market depth: {:?}", err),
    }

    // Get market price
    match deltadefi.market.get_market_price("ADAUSDX").await {
        Ok(price) => println!("\nGet market price:\n{:?}", price),
        Err(err) => eprintln!("Error getting market price: {:?}", err),
    }

    // Get aggregated price
    let start = 1_732_982_400; // Replace with your desired start timestamp
    let end = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("Time went backwards")
        .as_secs() as u64;
    match deltadefi
        .market
        .get_aggregated_price("ADAUSDX", "1M", start, end)
        .await
    {
        Ok(aggregated_price) => println!("\nGet aggregated price:\n{:?}", aggregated_price),
        Err(err) => eprintln!("Error getting aggregated price: {:?}", err),
    }
}
