import os
import time

from deltadefi import ApiClient
from dotenv import load_dotenv

load_dotenv(".env", override=True)
api_key = os.environ.get("DELTADEFI_API_KEY")

api = ApiClient(api_key=api_key)

res = api.market.get_depth("ADAUSDX")
print("\nGet depth:")
print(res)

res = api.market.get_market_price("ADAUSDX")
print("\nGet market price:")
print(res)

end = int(time.time())
res = api.market.get_aggregated_price("ADAUSDX", "1M", 1732982400, end)
print("\nGet aggregated price")
print(res)
