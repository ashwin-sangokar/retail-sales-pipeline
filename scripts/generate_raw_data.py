"""
generate_raw_data.py
---------------------
Simulates a raw retail sales export (e.g. from a POS / e-commerce system).
Intentionally injects real-world messiness so the ETL pipeline has genuine
cleaning work to do:
    - missing values (customer name, region, discount)
    - duplicate rows (same order line exported twice)
    - inconsistent date formats
    - inconsistent text casing / whitespace
    - invalid numeric entries (negative qty, zero price, text in numeric field)
    - inconsistent category labels for the same product
"""

import random
import csv
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

N_ROWS = 6000
START_DATE = datetime(2024, 1, 1)
END_DATE = datetime(2025, 12, 31)

REGIONS = ["North", "South", "East", "West", "Central"]
REGION_VARIANTS = {  # inconsistent casing/whitespace as found in real exports
    "North": ["North", "north", " North", "NORTH"],
    "South": ["South", "south", "South "],
    "East": ["East", "east", "EAST"],
    "West": ["West", "west", " West"],
    "Central": ["Central", "central", "Central "],
}

CATEGORIES = {
    "Electronics": ["Wireless Mouse", "Bluetooth Speaker", "USB-C Hub", "Laptop Stand", "Webcam HD"],
    "Apparel": ["Cotton T-Shirt", "Denim Jacket", "Running Shoes", "Wool Sweater", "Sports Cap"],
    "Home & Kitchen": ["Non-stick Pan", "Electric Kettle", "Storage Jar Set", "LED Desk Lamp", "Memory Foam Pillow"],
    "Beauty": ["Face Moisturizer", "Hair Dryer", "Lipstick Set", "Sunscreen SPF50", "Shampoo 500ml"],
    "Sports": ["Yoga Mat", "Dumbbell Set", "Cricket Bat", "Football", "Resistance Bands"],
}
# A couple of products get mislabeled into a wrong/inconsistent category sometimes (real-world mess)
CATEGORY_TYPOS = {"Electronics": ["Electronic", "electronics "], "Beauty": ["Beauty & Personal Care", "beauty"]}

PAYMENT_METHODS = ["Credit Card", "Debit Card", "UPI", "Cash on Delivery", "Net Banking"]
CHANNELS = ["Online", "In-Store"]

# base price per product (so discount/profit logic is realistic), cost is ~55-75% of price
PRODUCT_PRICE = {}
PRODUCT_CATEGORY = {}
for cat, products in CATEGORIES.items():
    for p in products:
        PRODUCT_PRICE[p] = round(random.uniform(8, 250), 2)
        PRODUCT_CATEGORY[p] = cat

product_list = list(PRODUCT_PRICE.keys())

# Pre-generate a customer pool (so repeat customers exist -> needed for customer behavior analysis)
N_CUSTOMERS = 900
customers = []
for i in range(1, N_CUSTOMERS + 1):
    customers.append({
        "customer_id": f"CUST{i:05d}",
        "customer_name": fake.name(),
        "region": random.choice(REGIONS),
    })


def random_date_str(d):
    """Return date in one of several inconsistent formats, like real POS exports."""
    fmt = random.choice(["%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y", "%d-%b-%Y"])
    return d.strftime(fmt)


def messy_region(region):
    if random.random() < 0.12:
        return None  # missing region
    return random.choice(REGION_VARIANTS[region])


def messy_category(cat):
    if cat in CATEGORY_TYPOS and random.random() < 0.15:
        return random.choice(CATEGORY_TYPOS[cat])
    return cat


def messy_customer_name(name):
    if random.random() < 0.04:
        return None
    if random.random() < 0.05:
        return f"  {name}  "  # stray whitespace
    return name


rows = []
order_id_counter = 100000

for _ in range(N_ROWS):
    order_id_counter += 1
    order_id = f"ORD{order_id_counter}"
    cust = random.choice(customers)
    product = random.choice(product_list)
    category = PRODUCT_CATEGORY[product]
    base_price = PRODUCT_PRICE[product]

    order_date = START_DATE + timedelta(days=random.randint(0, (END_DATE - START_DATE).days))

    qty = random.choice([1, 1, 1, 2, 2, 3, 4, 5])
    # inject occasional invalid quantity
    if random.random() < 0.01:
        qty = random.choice([-1, 0])

    unit_price = base_price
    # occasional data entry error: price stored as 0 or absurdly high (typo, extra zero)
    if random.random() < 0.008:
        unit_price = 0
    elif random.random() < 0.005:
        unit_price = base_price * 100

    discount_pct = random.choice([0, 0, 0, 5, 10, 15, 20])
    discount_val = "" if random.random() < 0.10 else discount_pct  # missing discount sometimes

    payment = random.choice(PAYMENT_METHODS)
    channel = random.choice(CHANNELS)

    row = {
        "order_id": order_id,
        "order_date": random_date_str(order_date),
        "customer_id": cust["customer_id"],
        "customer_name": messy_customer_name(cust["customer_name"]),
        "region": messy_region(cust["region"]),
        "product_name": product if random.random() > 0.02 else product.upper(),
        "category": messy_category(category),
        "quantity": qty,
        "unit_price": unit_price,
        "discount_percent": discount_val,
        "payment_method": payment,
        "sales_channel": channel,
    }
    rows.append(row)

# Inject exact duplicate rows (same order line exported twice) - common ETL issue
dupes = random.sample(rows, int(N_ROWS * 0.03))
rows.extend(dupes)

random.shuffle(rows)

fieldnames = list(rows[0].keys())
out_path = "/home/claude/retail-pipeline/data/raw/raw_sales_data.csv"
with open(out_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

print(f"Generated {len(rows)} rows -> {out_path}")
