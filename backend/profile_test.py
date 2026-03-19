import cProfile
import pstats
import sys

from dashboard.app import get_pricing_results, load_inventory, load_booking_events

def run():
    print("Loading data...")
    inv_df = load_inventory()
    events_df = load_booking_events()
    print(f"Loaded {len(inv_df)} inventory, {len(events_df)} events.")
    print("Precomputing metrics...")
    from datetime import datetime, timezone, timedelta
    now_global = datetime.now(timezone.utc)
    one_day_ago_g = now_global - timedelta(days=1)
    cutoff_14d_g = now_global - timedelta(days=14)

    df_24h_g = events_df[(events_df["booked_at"] >= one_day_ago_g) & (events_df["booked_at"] <= now_global)]
    actual_24h_map_g = df_24h_g.groupby("inventory_id")["quantity"].sum().to_dict()

    df_14d_g = events_df[(events_df["booked_at"] >= cutoff_14d_g) & (events_df["booked_at"] <= now_global)]
    actual_14d_map_g = df_14d_g.groupby("inventory_id")["quantity"].sum().to_dict()

    precomputed_g = {"actual_24h": actual_24h_map_g, "actual_14d": actual_14d_map_g}

    print("Running get_pricing_results...")
    res = get_pricing_results(inv_df, precomputed_metrics=precomputed_g)
    print(f"Done. {len(res)} results.")

if __name__ == "__main__":
    profiler = cProfile.Profile()
    profiler.enable()
    run()
    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats('cumtime')
    stats.print_stats(30)
