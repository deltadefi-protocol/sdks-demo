import os

from deltadefi import ApiClient
from dotenv import load_dotenv
from sidan_gin import Wallet

load_dotenv(".env", override=True)
api_key = os.environ.get("DELTADEFI_API_KEY")
seed_phrase = os.environ.get("SEED_PHRASE")

wallet = Wallet.new_mnemonic(seed_phrase)
api = ApiClient(api_key=api_key, wallet=wallet)

res = api.post_order(
    symbol="ADAUSDM",
    side="sell",
    type="limit",
    quantity=51,
    price=15,
)

print("Order submitted successfully.", res)

# time.sleep(1)

# res = api.order.build_cancel_order_transaction(
#     order_id=order_id,
# )

# print("\nBuild cancel order transaction:")
# print(res)
# tx_hex = res.tx_hex
# signed_tx = wallet.sign_tx(tx_hex)
# res = api.order.submit_cancel_order_transaction(
#     signed_tx=signed_tx,
# )

# print("\nSubmit cancel order transaction:")
# print("Order canceled successfully.", res)
