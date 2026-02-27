import math
def calculate_inventory_decay_factor(lead_days: int, total_lead_days: int, k: float = 20.0, p: float = 0.12) -> float:
    if lead_days <= 0: return 0.0
    if total_lead_days <= 0: return 1.0
    x = lead_days / total_lead_days
    try:
        exp_val = math.exp(-k * (x - p))
        decay = 1.0 / (1.0 + exp_val)
    except:
        decay = 1.0
    try:
        f_high = 1.0 / (1.0 + math.exp(-k * (1.0 - p)))
        f_low  = 1.0 / (1.0 + math.exp(-k * (0.0 - p)))
    except:
        f_high, f_low = 1.0, 0.0
    normalized_decay = (decay - f_low) / (f_high - f_low)
    return max(0.0, min(1.0, normalized_decay))

lead_days = 30
for t in range(30, -1, -1):
    print(f"t={t}, decay={calculate_inventory_decay_factor(t, lead_days):.3f}")
