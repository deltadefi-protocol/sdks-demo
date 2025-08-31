use deltadefi::{DeltaDeFi, Interval, Stage, Symbol};
use dotenv::dotenv;
use std::env;

pub async fn market() {
    dotenv().ok();
    let api_key = env::var("DELTADEFI_API_KEY").expect("DELTADEFI_API_KEY must be set");
    let deltadefi = DeltaDeFi::new(api_key, Stage::Staging, None).unwrap();

    // Get market price
    let res = deltadefi.market.get_market_price("ADAUSDM").await.unwrap();
    println!("\nGet market price:\n{:?}", res);

    // Get aggregated price
    let start = 1_732_982_400; // Replace with your desired start timestamp
    let end = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("Time went backwards")
        .as_secs() as u64;
    let res = deltadefi
        .market
        .get_aggregated_price(Symbol::ADAUSDM, Interval::Interval1d, start, end as i64)
        .await
        .unwrap();
    println!("\nGet aggregated price:\n{:?}", res);
}
