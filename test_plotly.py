import sys, os
sys.path.append(os.path.join(os.getcwd(), 'backend'))
from packaging_engine import simulate_sales_scenario

h_item = {"id": 1, "remaining_stock": 7, "total_stock": 15, "base_price": 50000, "current_price": 40000, "cost": 35000}
f_item = {"id": 4, "remaining_stock": 7, "total_stock": 15, "base_price": 50000, "current_price": 40000, "cost": 35000, "velocity_ratio": 1.0}
res = simulate_sales_scenario(h_item, f_item, 500, 30, "base")

history = res["history"]
days_x = [f"D-{h['day_idx']}" for h in history]
asset_value = [h_item["remaining_stock"] * h_item["cost"] * h["decay_factor"] for h in history]

print("Length of days_x:", len(days_x))
print("days_x[4]:", days_x[4], "asset_value[4]:", asset_value[4])
print("days_x[0:5]:", days_x[0:5])
print("asset_value[0:5]:", [f"{x:.1f}" for x in asset_value[0:5]])
