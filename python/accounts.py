import os

from deltadefi import ApiClient
from dotenv import load_dotenv

load_dotenv(".env", override=True)
api_key = os.environ.get("DELTADEFI_API_KEY")

api = ApiClient(api_key=api_key)

print(api.base_url)

res = api.accounts.get_account_balance()
print("\nGet account balance:")
print(res)

res = api.accounts.get_deposit_records()
print("\nGet deposit records:")
print(res)

res = api.accounts.get_order_records("openOrder")
print("\nGet order records:")
print(res)

res = api.accounts.get_order_record("054a0353-31fe-4575-ad06-927048288394")  # You should replace this with a real order ID
print("\nGet order record:")
print(res)

res = api.accounts.get_withdrawal_records()
print("\nGet withdrawal records:")
print(res)
