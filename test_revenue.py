import sys
sys.path.append('backend')
from packaging_engine import simulate_sales_scenario

h_item = {
    "id": 1,
    "cost": 5000,
    "original_price": 10000,
    "current_price": 10000, # What if current price is SAME as original?
    "velocity_ratio": 1.0
}
f_item = {
    "id": 2,
    "cost": 15000,
    "original_price": 20000,
    "current_price": 20000,
    "velocity_ratio": 1.0
}

# 1. Prices same as original, with discount
res1 = simulate_sales_scenario(h_item, f_item, discount=2000, lead_days=30, market_condition="base", reference_date=None)
print("--- Test 1: current = original, discount = 2000 ---")
print(f"Revenue N (Baseline): {res1['history'][-1]['revenue_n']}")
print(f"Revenue B (Selected): {res1['history'][-1]['revenue_b']}")
print(f"Sold N (H, F): {sum(h['h_stock_a'] for h in res1['history'])}, etc...")

# 2. current_price > original_price
h_item["current_price"] = 12000
res2 = simulate_sales_scenario(h_item, f_item, discount=2000, lead_days=30, market_condition="base", reference_date=None)
print("--- Test 2: current > original, discount = 2000 ---")
print(f"Revenue N (Baseline): {res2['history'][-1]['revenue_n']}")
print(f"Revenue B (Selected): {res2['history'][-1]['revenue_b']}")
