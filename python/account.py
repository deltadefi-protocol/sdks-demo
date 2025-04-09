import os

from deltadefi import ApiClient
from dotenv import load_dotenv

load_dotenv(".env", override=True)
api_key = os.environ.get("DELTADEFI_API_KEY")

api = ApiClient(api_key=api_key)

res = api.accounts.get_account_balance()
print("Get account balance:")
print(res)

res = api.accounts.get_deposit_records()
print("Get deposit records:")
print(res)

res = api.accounts.get_order_records()
print("Get order records:")
print(res)

res = api.accounts.get_withdrawal_records()
print("Get withdrawal records:")
print(res)
