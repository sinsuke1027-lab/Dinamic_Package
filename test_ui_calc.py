import sys
import sqlite3
import pandas as pd
from datetime import date, timedelta
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
# We need to simulate the exact past data logic to get h_stock and f_stock
dep_dt = pd.to_datetime('2026-03-07')
v_today_dt = pd.to_datetime('2026-01-01')

# For simplicity, let's query the DB for remaining stock at an earlier point, or assume the UI calculated it.
# Actually, the user says "①現状維持だと売れ残りが発生し". Let's run the exact simulation logic.
h_stock = target_hotel["remaining_stock"]
f_stock = target_flight["remaining_stock"]

# But wait, past events? The db might have events.
events = pd.read_sql("SELECT * FROM booking_events WHERE booked_at <= '2026-01-01 23:59:59'", conn)
h_events = events[events["inventory_id"] == target_hotel["id"]]
f_events = events[events["inventory_id"] == target_flight["id"]]
h_stock = target_hotel["total_stock"] - h_events["quantity"].sum()
f_stock = target_flight["total_stock"] - f_events["quantity"].sum()

print(f"Start Stock H: {h_stock}, F: {f_stock}")

lead_days = (dep_dt.date() - v_today).days
print(f"Lead days: {lead_days}")

h_pricing = calculate_pricing_result(
    target_hotel["id"], target_hotel["name"], target_hotel["base_price"], target_hotel["total_stock"],
    h_stock, target_hotel["departure_date"], elasticity=-2.5, reference_date=v_today, strategy="demand_based"
)
f_pricing = calculate_pricing_result(
    target_flight["id"], target_flight["name"], target_flight["base_price"], target_flight["total_stock"],
    f_stock, target_flight["departure_date"], elasticity=-0.8, reference_date=v_today, strategy="demand_based"
)

h_item_sim = {
    "id": target_hotel["id"], "remaining_stock": h_stock, "total_stock": target_hotel["total_stock"],
    "base_price": target_hotel["base_price"], "current_price": h_pricing["final_price"],
    "original_price": target_hotel.get("current_price", target_hotel["base_price"]),
    "cost": int(target_hotel["base_price"] * 0.9), "elasticity": -2.5, "lead_days": lead_days
}
f_item_sim = {
    "id": target_flight["id"], "remaining_stock": f_stock, "total_stock": target_flight["total_stock"],
    "base_price": target_flight["base_price"], "current_price": f_pricing["final_price"],
    "original_price": target_flight.get("current_price", target_flight["base_price"]),
    "cost": int(target_flight["base_price"] * 0.9), "velocity_ratio": f_pricing.get("velocity_ratio") or 1.0, 
    "elasticity": -0.8, "lead_days": lead_days
}

discount, opt_sim = find_optimal_bundle_discount(h_item_sim, f_item_sim, lead_days, reference_date=v_today)
sim = simulate_sales_scenario(h_item_sim, f_item_sim, discount, lead_days, "base", reference_date=v_today)

print("\n--- Demand Hybird (Simulation ②) ---")
print(f"H Demand Price: {h_pricing['final_price']} (Reason: {h_pricing['reason']})")
print(f"F Demand Price: {f_pricing['final_price']} (Reason: {f_pricing['reason']})")
print(f"Discount: {discount}")

last_day = sim["history"][-1]
print("\n--- Status Quo (Simulation ①) ---")
print(f"N Rev: {last_day['revenue_n']}")
print(f"N Unsold H: {last_day['h_stock_a']}, F: {last_day['f_stock_a']}")

print("\n--- Selected (Simulation ②) ---")
print(f"B Rev: {last_day['revenue_b']}")
print(f"B Unsold H: {last_day['h_stock_b']}, F: {last_day['f_stock_b']}")

# Also show the prices used to calculate Status Quo
print(f"\nStatus Quo Prices -> H: {h_item_sim['original_price']}, F: {f_item_sim['original_price']}")
print(f"Demand Prices -> H: {h_item_sim['current_price']}, F: {f_item_sim['current_price']}")
