import os
import time

from deltadefi import ApiClient
from dotenv import load_dotenv
from sidan_gin import HDWallet

load_dotenv(".env", override=True)
api_key = os.environ.get("DELTADEFI_API_KEY")
seed_phrase = os.environ.get("SEED_PHRASE")

api = ApiClient(api_key=api_key)
wallet = HDWallet(seed_phrase)

res = api.order.build_place_order_transaction(
    symbol="ADAUSDX",
    side="sell",
    type="limit",
    quantity=51,
    price=1.5,
)

print("\nBuild place order transaction:")
print(res)

order_id = res["order_id"]
tx_hex = res["tx_hex"]
signed_tx = wallet.sign_tx(tx_hex)

print("\nSigned transaction hex:", signed_tx)

res = api.order.submit_place_order_transaction(
    order_id=order_id,
    signed_tx=signed_tx,
)
print("\nSubmit place order transaction:")
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
