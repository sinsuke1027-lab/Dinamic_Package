import sys
import sqlite3
import pandas as pd
from datetime import date
sys.path.append('backend')
from pricing_engine import calculate_pricing_result
from packaging_engine import simulate_sales_scenario, get_velocity_ratio, find_optimal_bundle_discount

v_today = date(2026, 1, 1)

conn = sqlite3.connect("inventory.db")
conn.row_factory = sqlite3.Row
hotel_query = "SELECT * FROM inventory WHERE item_type='hotel' AND name LIKE '%アロハ%' AND departure_date='2026-03-07'"
target_hotel = dict(conn.execute(hotel_query).fetchone())

flight_query = "SELECT * FROM inventory WHERE item_type='flight' AND name LIKE '%JL%FUK%HNL%' AND departure_date='2026-03-07'"
target_flight = dict(conn.execute(flight_query).fetchone())

# Dashboard settings
h_stock = 8
f_stock = 18

print(f"H: {target_hotel['name']}, base: {target_hotel['base_price']}")
print(f"F: {target_flight['name']}, base: {target_flight['base_price']}")

lead_days = 65  # approx

# Calculate demand based
h_pricing_demand = calculate_pricing_result(
    inventory_id=target_hotel["id"], name=target_hotel["name"], base_price=target_hotel["base_price"],
    total_stock=target_hotel["total_stock"], remaining_stock=h_stock, departure_date=target_hotel.get("departure_date"),
    reference_date=v_today, strategy="demand_based"
)
f_pricing_demand = calculate_pricing_result(
    inventory_id=target_flight["id"], name=target_flight["name"], base_price=target_flight["base_price"],
    total_stock=target_flight["total_stock"], remaining_stock=f_stock, departure_date=target_flight.get("departure_date"),
    reference_date=v_today, strategy="demand_based"
)

print(f"H Demand Price: {h_pricing_demand['final_price']} (Reason: {h_pricing_demand['reason']})")
print(f"F Demand Price: {f_pricing_demand['final_price']} (Reason: {f_pricing_demand['reason']})")

h_item_sim_demand = {
    "id": target_hotel["id"], "remaining_stock": h_stock, "total_stock": target_hotel["total_stock"],
    "base_price": target_hotel["base_price"], "current_price": h_pricing_demand["final_price"],
    "original_price": target_hotel.get("current_price", target_hotel["base_price"]),
    "cost": int(target_hotel["base_price"] * 0.9), "elasticity": -1.5,
    "lead_days": lead_days
}
f_item_sim_demand = {
    "id": target_flight["id"], "remaining_stock": f_stock, "total_stock": target_flight["total_stock"],
    "base_price": target_flight["base_price"], "current_price": f_pricing_demand["final_price"],
    "original_price": target_flight.get("current_price", target_flight["base_price"]),
    "cost": int(target_flight["base_price"] * 0.9), "velocity_ratio": f_pricing_demand.get("velocity_ratio") or 1.0, "elasticity": -1.5,
    "lead_days": lead_days
}

# Find discount
discount, sim_opt = find_optimal_bundle_discount(h_item_sim_demand, f_item_sim_demand, lead_days, reference_date=v_today)
print(f"Discount: {discount}")

sim = simulate_sales_scenario(h_item_sim_demand, f_item_sim_demand, discount, lead_days, "base", reference_date=v_today)

print("----- RESULTS -----")
h_sold_n = h_stock - sim["history"][-1]["h_stock_a"]
f_sold_n = f_stock - sim["history"][-1]["f_stock_a"]
h_sold_b = h_stock - sim["history"][-1]["h_stock_b"]
f_sold_b = f_stock - sim["history"][-1]["f_stock_b"]

rev_n = sim["history"][-1]["revenue_n"]
rev_b = sim["history"][-1]["revenue_b"]

print(f"Scenario N: Sold H={h_sold_n}, F={f_sold_n} | Revenue N: {rev_n}")
print(f"Scenario B: Sold H={h_sold_b}, F={f_sold_b} (pkg={sim['packages_sold']}) | Revenue B: {rev_b}")
print(f"Prices N: H={h_item_sim_demand['original_price']}, F={f_item_sim_demand['original_price']}")
print(f"Prices B: H={h_item_sim_demand['current_price']}, F={f_item_sim_demand['current_price']}")
