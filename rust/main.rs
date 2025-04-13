mod accounts;
mod market;

#[tokio::main]
async fn main() {
    accounts::accounts().await;
    market::market().await;
}
