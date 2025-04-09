import os

from deltadefi import ApiClient
from dotenv import load_dotenv

load_dotenv(".env", override=True)
api_key = os.environ.get("DELTADEFI_API_KEY")

api = ApiClient(api_key=api_key)

res = api.accounts.get_account_balance()
print("\nGet account balance:")
print(res)

res = api.accounts.get_deposit_records()
print("\nGet deposit records:")
print(res)

res = api.accounts.get_order_records()
print("\nGet order records:")
print(res)

res = api.accounts.get_withdrawal_records()
print("\nGet withdrawal records:")
print(res)
