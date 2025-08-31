mod accounts;
mod market;
mod order;

#[tokio::main]
async fn main() {
    // accounts::accounts().await;
    market::market().await;
    // order::order().await;
}
