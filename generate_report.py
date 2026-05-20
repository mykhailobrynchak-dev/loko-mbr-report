#!/usr/bin/env python3
"""Generate LOKO MBR Report (index.html) from Databricks.

Fetches:
  - Last 4 months including current month (Monthly tab) and last 4 full weeks (Weekly tab) for:
      financial, operational, replacement/adjustment, failed orders,
      failed reasons breakdown, campaigns, acceptance/availability.
  - Store-level weekly metrics (orders, merch price, rating, availability) per provider.
  - Customer text feedback (rating + comment) per provider per week.

Outputs a single self-contained index.html with three tabs:
Monthly / Weekly / Stores (with weekly selector).
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from databricks import sql as dbsql

DATABRICKS_HOST = os.environ["DATABRICKS_HOST"]
DATABRICKS_TOKEN = os.environ["DATABRICKS_TOKEN"]
DATABRICKS_HTTP_PATH = os.environ.get("DATABRICKS_HTTP_PATH", "")
DATABRICKS_WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")

PARTNER_NAME = "LOKO"

TEMPLATE_PATH = Path(__file__).parent / "template.html"
OUTPUT_PATH = Path(__file__).parent / "index.html"
DATA_PATH = Path(__file__).parent / "report_data.json"


def get_connection():
    if DATABRICKS_HTTP_PATH:
        return dbsql.connect(
            server_hostname=DATABRICKS_HOST,
            http_path=DATABRICKS_HTTP_PATH,
            access_token=DATABRICKS_TOKEN,
        )
    return dbsql.connect(
        server_hostname=DATABRICKS_HOST,
        http_path=f"/sql/1.0/warehouses/{DATABRICKS_WAREHOUSE_ID}",
        access_token=DATABRICKS_TOKEN,
    )


def run_query(cursor, query):
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def to_serializable(rows):
    out = []
    for row in rows:
        d = {}
        for k, v in row.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif hasattr(v, "as_py"):
                d[k] = v.as_py()
            elif hasattr(v, "__float__"):
                d[k] = float(v)
            elif hasattr(v, "__int__"):
                d[k] = int(v)
            else:
                d[k] = v
        out.append(d)
    return out


def _monthly_start():
    """Return first day of (current_month - 3) — last 4 months including current."""
    today = datetime.now().date()
    year = today.year
    month = today.month - 3
    while month <= 0:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}-01"


# Resolution reasons that are NOT order failures (appear in resolution table for all orders)
SUCCESS_RESOLUTION_REASONS = (
    "automatically_succeeded",
    "manually_succeeded_by_cs",
)


def _week_boundaries():
    """Return (4 weeks ago Monday, last completed Sunday) as ISO strings."""
    today = datetime.now().date()
    last_sunday = today - timedelta(days=today.isoweekday())
    four_weeks_ago_monday = last_sunday - timedelta(days=27)
    return str(four_weeks_ago_monday), str(last_sunday)


MONTHLY_START = _monthly_start()
WEEKLY_START, WEEKLY_END = _week_boundaries()

# ---------------------------------------------------------------------------
# SQL Queries — Monthly (last 4 months)
# ---------------------------------------------------------------------------

NETWORK_STORES = f"""
SELECT
    p.provider_id,
    p.provider_name,
    p.city_name
FROM ng_delivery_spark.dim_provider_v2 p
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND (
    (p.provider_status = 'active' AND p.lifecycle_status = 'ready_for_work')
    OR (p.provider_status = 'hidden' AND p.lifecycle_status = 'hidden')
  )
ORDER BY p.provider_name
LIMIT 500
"""

FINANCIAL_MONTHLY = f"""
SELECT
    DATE_FORMAT(f.order_created_date, 'yyyy-MM') AS period,
    COUNT(*) AS orders,
    SUM(f.provider_price_before_discount_eur) AS merchant_price_eur,
    SUM(f.provider_price_before_discount_eur) / NULLIF(COUNT(*), 0) AS merchant_price_per_order,
    SUM(f.order_gmv_eur) AS gmv_eur,
    SUM(f.order_gmv_eur) / NULLIF(COUNT(*), 0) AS aov_eur,
    COUNT(DISTINCT CASE WHEN f.is_first_delivery_order THEN f.user_id END) AS users_activated,
    COUNT(DISTINCT f.user_id) AS active_users,
    SUM(f.total_refunded_amount_eur) / NULLIF(SUM(f.order_gmv_eur), 0) * 100 AS refund_rate_pct
FROM ng_delivery_spark.fact_order_delivery f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.order_state = 'delivered'
  AND f.order_created_date >= '{MONTHLY_START}'
GROUP BY 1
ORDER BY 1
"""

FINANCIAL_WEEKLY = f"""
SELECT
    DATE_FORMAT(DATE_TRUNC('week', f.order_created_date), 'yyyy-MM-dd') AS period,
    COUNT(*) AS orders,
    SUM(f.provider_price_before_discount_eur) AS merchant_price_eur,
    SUM(f.provider_price_before_discount_eur) / NULLIF(COUNT(*), 0) AS merchant_price_per_order,
    SUM(f.order_gmv_eur) AS gmv_eur,
    SUM(f.order_gmv_eur) / NULLIF(COUNT(*), 0) AS aov_eur,
    COUNT(DISTINCT CASE WHEN f.is_first_delivery_order THEN f.user_id END) AS users_activated,
    COUNT(DISTINCT f.user_id) AS active_users,
    SUM(f.total_refunded_amount_eur) / NULLIF(SUM(f.order_gmv_eur), 0) * 100 AS refund_rate_pct
FROM ng_delivery_spark.fact_order_delivery f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.order_state = 'delivered'
  AND f.order_created_date >= '{WEEKLY_START}'
  AND f.order_created_date <= '{WEEKLY_END}'
GROUP BY 1
ORDER BY 1
"""

OPERATIONAL_MONTHLY = f"""
SELECT
    DATE_FORMAT(f.order_created_date, 'yyyy-MM') AS period,
    COUNT(*) AS delivered_orders,
    COUNT(DISTINCT f.provider_id) AS stores_with_orders,
    SUM(CASE WHEN f.is_honey_order THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100 AS honey_order_rate,
    SUM(CASE WHEN f.is_bad_order THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100 AS bad_order_rate,
    SUM(CASE WHEN f.is_order_delivered_5_min_late THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100 AS late_delivery_rate,
    SUM(CASE WHEN f.is_order_late_to_partner_5_min THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100 AS late_pickup_rate,
    AVG(f.order_delivery_minutes) AS avg_delivery_minutes,
    AVG(f.courier_delivery_time_min) AS avg_courier_delivery_min
FROM ng_delivery_spark.fact_order_delivery f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.order_state = 'delivered'
  AND f.order_created_date >= '{MONTHLY_START}'
GROUP BY 1
ORDER BY 1
"""

OPERATIONAL_WEEKLY = OPERATIONAL_MONTHLY.replace(
    "DATE_FORMAT(f.order_created_date, 'yyyy-MM') AS period",
    "DATE_FORMAT(DATE_TRUNC('week', f.order_created_date), 'yyyy-MM-dd') AS period",
).replace(
    f"AND f.order_created_date >= '{MONTHLY_START}'",
    f"AND f.order_created_date >= '{WEEKLY_START}'\n  AND f.order_created_date <= '{WEEKLY_END}'",
)

REPLACEMENT_ADJUSTMENT_MONTHLY = f"""
SELECT
    DATE_FORMAT(f.metric_timestamp_local, 'yyyy-MM') AS period,
    ROUND(SUM(f.order_item_adjustment_rate_value * f.order_item_adjustment_rate_weight)
        / NULLIF(SUM(f.order_item_adjustment_rate_weight), 0) * 100, 2) AS adjustment_rate,
    ROUND(SUM(f.order_item_replacement_rate_value * f.order_item_replacement_rate_weight)
        / NULLIF(SUM(f.order_item_replacement_rate_weight), 0) * 100, 2) AS replacement_rate
FROM ng_delivery_spark.fact_provider_weekly f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.metric_timestamp_local >= '{MONTHLY_START}'
GROUP BY 1
ORDER BY 1
"""

REPLACEMENT_ADJUSTMENT_WEEKLY = f"""
SELECT
    DATE_FORMAT(f.metric_timestamp_local, 'yyyy-MM-dd') AS period,
    ROUND(SUM(f.order_item_adjustment_rate_value * f.order_item_adjustment_rate_weight)
        / NULLIF(SUM(f.order_item_adjustment_rate_weight), 0) * 100, 2) AS adjustment_rate,
    ROUND(SUM(f.order_item_replacement_rate_value * f.order_item_replacement_rate_weight)
        / NULLIF(SUM(f.order_item_replacement_rate_weight), 0) * 100, 2) AS replacement_rate
FROM ng_delivery_spark.fact_provider_weekly f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.metric_timestamp_local >= '{WEEKLY_START}'
  AND f.metric_timestamp_local <= '{WEEKLY_END}'
GROUP BY 1
ORDER BY 1
"""

FAILED_ORDERS_MONTHLY = f"""
SELECT
    DATE_FORMAT(f.order_created_date, 'yyyy-MM') AS period,
    COUNT(*) AS total_placed,
    SUM(CASE WHEN f.order_state = 'delivered' THEN 1 ELSE 0 END) AS delivered,
    SUM(CASE WHEN f.order_state != 'delivered' THEN 1 ELSE 0 END) AS failed_total,
    SUM(CASE WHEN f.order_state != 'delivered' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) * 100 AS failed_rate_pct
FROM ng_delivery_spark.fact_order_delivery f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.order_created_date >= '{MONTHLY_START}'
GROUP BY 1
ORDER BY 1
"""

FAILED_ORDERS_WEEKLY = FAILED_ORDERS_MONTHLY.replace(
    "DATE_FORMAT(f.order_created_date, 'yyyy-MM') AS period",
    "DATE_FORMAT(DATE_TRUNC('week', f.order_created_date), 'yyyy-MM-dd') AS period",
).replace(
    f"AND f.order_created_date >= '{MONTHLY_START}'",
    f"AND f.order_created_date >= '{WEEKLY_START}'\n  AND f.order_created_date <= '{WEEKLY_END}'",
)

FAILED_REASONS_MONTHLY = f"""
SELECT
    DATE_FORMAT(f.order_created_date, 'yyyy-MM') AS period,
    r.reason,
    r.actor_type,
    COUNT(*) AS cnt
FROM ng_delivery_spark.delivery_order_order_resolution r
    JOIN ng_delivery_spark.fact_order_delivery f ON r.order_id = f.order_id
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.order_created_date >= '{MONTHLY_START}'
  AND f.order_state != 'delivered'
  AND r.reason NOT IN ({", ".join(repr(x) for x in SUCCESS_RESOLUTION_REASONS)})
GROUP BY 1, r.reason, r.actor_type
ORDER BY 1, cnt DESC
"""

FAILED_REASONS_WEEKLY = f"""
SELECT
    DATE_FORMAT(DATE_TRUNC('week', f.order_created_date), 'yyyy-MM-dd') AS period,
    r.reason,
    r.actor_type,
    COUNT(*) AS cnt
FROM ng_delivery_spark.delivery_order_order_resolution r
    JOIN ng_delivery_spark.fact_order_delivery f ON r.order_id = f.order_id
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.order_created_date >= '{WEEKLY_START}'
  AND f.order_created_date <= '{WEEKLY_END}'
  AND f.order_state != 'delivered'
  AND r.reason NOT IN ({", ".join(repr(x) for x in SUCCESS_RESOLUTION_REASONS)})
GROUP BY 1, r.reason, r.actor_type
ORDER BY 1, cnt DESC
"""

CAMPAIGNS_MONTHLY = f"""
SELECT
    DATE_FORMAT(f.order_created_date, 'yyyy-MM') AS period,
    SUM(f.total_order_item_discount_eur) AS campaigns_discount_eur,
    SUM(f.total_order_item_discount_eur)
        - SUM(f.provider_price_before_discount_eur - f.provider_price_after_discount_eur) AS bolt_spend_eur,
    SUM(f.provider_price_before_discount_eur - f.provider_price_after_discount_eur) AS merchant_spend_eur,
    COUNT(CASE WHEN f.total_order_item_discount_eur > 0 THEN 1 END) AS campaign_orders
FROM ng_delivery_spark.fact_order_delivery f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.order_state = 'delivered'
  AND f.order_created_date >= '{MONTHLY_START}'
GROUP BY 1
ORDER BY 1
"""

CAMPAIGNS_WEEKLY = CAMPAIGNS_MONTHLY.replace(
    "DATE_FORMAT(f.order_created_date, 'yyyy-MM') AS period",
    "DATE_FORMAT(DATE_TRUNC('week', f.order_created_date), 'yyyy-MM-dd') AS period",
).replace(
    f"AND f.order_created_date >= '{MONTHLY_START}'",
    f"AND f.order_created_date >= '{WEEKLY_START}'\n  AND f.order_created_date <= '{WEEKLY_END}'",
)

ACCEPTANCE_AVAILABILITY_MONTHLY = f"""
SELECT
    DATE_FORMAT(f.metric_timestamp_local, 'yyyy-MM') AS period,
    ROUND(SUM(f.provider_acceptance_rate_value * f.provider_acceptance_rate_weight)
        / NULLIF(SUM(f.provider_acceptance_rate_weight), 0) * 100, 1) AS acceptance_rate,
    ROUND(SUM(f.provider_active_rate_value * f.provider_active_rate_weight)
        / NULLIF(SUM(f.provider_active_rate_weight), 0) * 100, 1) AS availability_rate,
    ROUND(SUM(f.provider_rating_per_order_value * f.provider_rating_per_order_weight)
        / NULLIF(SUM(f.provider_rating_per_order_weight), 0), 3) AS avg_rating
FROM ng_delivery_spark.fact_provider_weekly f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.metric_timestamp_local >= '{MONTHLY_START}'
GROUP BY 1
ORDER BY 1
"""

ACCEPTANCE_AVAILABILITY_WEEKLY = f"""
SELECT
    DATE_FORMAT(f.metric_timestamp_local, 'yyyy-MM-dd') AS period,
    ROUND(SUM(f.provider_acceptance_rate_value * f.provider_acceptance_rate_weight)
        / NULLIF(SUM(f.provider_acceptance_rate_weight), 0) * 100, 1) AS acceptance_rate,
    ROUND(SUM(f.provider_active_rate_value * f.provider_active_rate_weight)
        / NULLIF(SUM(f.provider_active_rate_weight), 0) * 100, 1) AS availability_rate,
    ROUND(SUM(f.provider_rating_per_order_value * f.provider_rating_per_order_weight)
        / NULLIF(SUM(f.provider_rating_per_order_weight), 0), 3) AS avg_rating
FROM ng_delivery_spark.fact_provider_weekly f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.metric_timestamp_local >= '{WEEKLY_START}'
  AND f.metric_timestamp_local <= '{WEEKLY_END}'
GROUP BY 1
ORDER BY 1
"""

ACCEPTANCE_AVAILABILITY_CURRENT = f"""
SELECT
    ROUND(SUM(f.provider_acceptance_rate_value * f.provider_acceptance_rate_weight)
        / NULLIF(SUM(f.provider_acceptance_rate_weight), 0) * 100, 1) AS acceptance_rate,
    ROUND(SUM(f.provider_active_rate_value * f.provider_active_rate_weight)
        / NULLIF(SUM(f.provider_active_rate_weight), 0) * 100, 1) AS availability_rate,
    ROUND(SUM(f.provider_rating_per_order_value * f.provider_rating_per_order_weight)
        / NULLIF(SUM(f.provider_rating_per_order_weight), 0), 3) AS avg_rating
FROM ng_delivery_spark.fact_provider_weekly f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.metric_timestamp_local >= DATE_SUB(CURRENT_DATE(), 7)
"""

# Store-level weekly orders & merchant price (last 4 weeks)
STORE_WEEKLY = f"""
SELECT
    DATE_FORMAT(DATE_TRUNC('week', f.order_created_date), 'yyyy-MM-dd') AS period,
    f.provider_id,
    f.provider_name,
    f.city_name,
    COUNT(*) AS orders,
    SUM(f.provider_price_before_discount_eur) AS merchant_price_eur,
    SUM(f.provider_price_before_discount_eur) / NULLIF(COUNT(*), 0) AS aov_eur
FROM ng_delivery_spark.fact_order_delivery f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.order_state = 'delivered'
  AND f.order_created_date >= '{WEEKLY_START}'
  AND f.order_created_date <= '{WEEKLY_END}'
GROUP BY 1, 2, 3, 4
ORDER BY 1, orders DESC
LIMIT 5000
"""

# Per-store weekly rating + availability (from fact_provider_weekly)
STORE_QUALITY_WEEKLY = f"""
SELECT
    DATE_FORMAT(f.metric_timestamp_local, 'yyyy-MM-dd') AS period,
    f.provider_id,
    p.provider_name,
    ROUND(SUM(f.provider_active_rate_value * f.provider_active_rate_weight)
        / NULLIF(SUM(f.provider_active_rate_weight), 0) * 100, 1) AS availability_rate,
    ROUND(SUM(f.provider_acceptance_rate_value * f.provider_acceptance_rate_weight)
        / NULLIF(SUM(f.provider_acceptance_rate_weight), 0) * 100, 1) AS acceptance_rate,
    ROUND(SUM(f.provider_rating_per_order_value * f.provider_rating_per_order_weight)
        / NULLIF(SUM(f.provider_rating_per_order_weight), 0), 3) AS avg_rating
FROM ng_delivery_spark.fact_provider_weekly f
    JOIN ng_delivery_spark.dim_provider_v2 p ON f.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND f.metric_timestamp_local >= '{WEEKLY_START}'
  AND f.metric_timestamp_local <= '{WEEKLY_END}'
GROUP BY 1, 2, 3
ORDER BY 1, 3
LIMIT 5000
"""

# Customer text feedback per store per week (last 4 weeks)
CUSTOMER_REVIEWS_WEEKLY = f"""
SELECT
    DATE_FORMAT(DATE_TRUNC('week', r.created_date), 'yyyy-MM-dd') AS period,
    p.provider_id,
    p.provider_name,
    p.city_name,
    r.rating_value,
    r.comment,
    CAST(r.created AS STRING) AS created_at,
    f.order_reference_id
FROM ng_delivery_spark.delivery_rating_provider_rating_history r
    JOIN ng_delivery_spark.dim_provider_v2 p ON r.provider_id = p.provider_id
    LEFT JOIN ng_delivery_spark.fact_order_delivery f ON r.order_id = f.order_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND r.created_date >= '{WEEKLY_START}'
  AND r.created_date <= '{WEEKLY_END}'
  AND r.comment IS NOT NULL
  AND LENGTH(TRIM(r.comment)) > 0
  AND COALESCE(r.ignore_rating, false) = false
ORDER BY r.created DESC
LIMIT 2000
"""

# All ratings per store per week (including those without comments) — for avg/count
STORE_RATINGS_WEEKLY = f"""
SELECT
    DATE_FORMAT(DATE_TRUNC('week', r.created_date), 'yyyy-MM-dd') AS period,
    p.provider_id,
    AVG(r.rating_value) AS avg_review_rating,
    COUNT(*) AS reviews_count,
    SUM(CASE WHEN r.comment IS NOT NULL AND LENGTH(TRIM(r.comment)) > 0 THEN 1 ELSE 0 END) AS comments_count
FROM ng_delivery_spark.delivery_rating_provider_rating_history r
    JOIN ng_delivery_spark.dim_provider_v2 p ON r.provider_id = p.provider_id
WHERE p.country_code = 'ua'
  AND p.group_name = '{PARTNER_NAME}'
  AND r.created_date >= '{WEEKLY_START}'
  AND r.created_date <= '{WEEKLY_END}'
  AND COALESCE(r.ignore_rating, false) = false
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 5000
"""


def main():
    print(f"Partner: {PARTNER_NAME}")
    print(f"Monthly start: {MONTHLY_START}")
    print(f"Weekly window: {WEEKLY_START} — {WEEKLY_END}")
    print("Connecting to Databricks...")
    conn = get_connection()
    cursor = conn.cursor()

    print("Fetching financial data...")
    fin_m = to_serializable(run_query(cursor, FINANCIAL_MONTHLY))
    fin_w = to_serializable(run_query(cursor, FINANCIAL_WEEKLY))

    print("Fetching operational data...")
    ops_m = to_serializable(run_query(cursor, OPERATIONAL_MONTHLY))
    ops_w = to_serializable(run_query(cursor, OPERATIONAL_WEEKLY))

    print("Fetching replacement/adjustment rates...")
    repl_m = to_serializable(run_query(cursor, REPLACEMENT_ADJUSTMENT_MONTHLY))
    repl_w = to_serializable(run_query(cursor, REPLACEMENT_ADJUSTMENT_WEEKLY))

    print("Fetching failed orders...")
    fail_m = to_serializable(run_query(cursor, FAILED_ORDERS_MONTHLY))
    fail_w = to_serializable(run_query(cursor, FAILED_ORDERS_WEEKLY))

    print("Fetching failed order reasons...")
    fail_reasons_m = to_serializable(run_query(cursor, FAILED_REASONS_MONTHLY))
    fail_reasons_w = to_serializable(run_query(cursor, FAILED_REASONS_WEEKLY))

    print("Fetching campaign data...")
    camp_m = to_serializable(run_query(cursor, CAMPAIGNS_MONTHLY))
    camp_w = to_serializable(run_query(cursor, CAMPAIGNS_WEEKLY))

    print("Fetching acceptance/availability...")
    aa_current = to_serializable(run_query(cursor, ACCEPTANCE_AVAILABILITY_CURRENT))
    aa_m = to_serializable(run_query(cursor, ACCEPTANCE_AVAILABILITY_MONTHLY))
    aa_w = to_serializable(run_query(cursor, ACCEPTANCE_AVAILABILITY_WEEKLY))

    print("Fetching network stores (Bolt catalogue)...")
    network_stores = to_serializable(run_query(cursor, NETWORK_STORES))
    network_store_count = len(network_stores)

    print("Fetching store-level weekly orders...")
    store_weekly = to_serializable(run_query(cursor, STORE_WEEKLY))

    print("Fetching store-level weekly quality (rating/availability)...")
    store_quality = to_serializable(run_query(cursor, STORE_QUALITY_WEEKLY))

    print("Fetching store-level weekly review counts/avg...")
    store_ratings = to_serializable(run_query(cursor, STORE_RATINGS_WEEKLY))

    print("Fetching customer text reviews...")
    customer_reviews = to_serializable(run_query(cursor, CUSTOMER_REVIEWS_WEEKLY))

    # Merge per-store quality + review counts into store_weekly rows for convenient rendering
    quality_map = {}
    for q in store_quality:
        quality_map[(q["period"], q["provider_id"])] = q
    ratings_map = {}
    for r in store_ratings:
        ratings_map[(r["period"], r["provider_id"])] = r

    for entry in store_weekly:
        key = (entry["period"], entry["provider_id"])
        q = quality_map.get(key, {})
        r = ratings_map.get(key, {})
        entry["availability_rate"] = q.get("availability_rate")
        entry["acceptance_rate"] = q.get("acceptance_rate")
        entry["avg_rating"] = q.get("avg_rating")
        entry["avg_review_rating"] = r.get("avg_review_rating")
        entry["reviews_count"] = r.get("reviews_count", 0)
        entry["comments_count"] = r.get("comments_count", 0)

    # Inject network store count into operational rows (114 stores on Bolt, not only with orders)
    for row in ops_m:
        row["network_stores"] = network_store_count
        row["active_stores"] = network_store_count
    for row in ops_w:
        row["network_stores"] = network_store_count
        row["active_stores"] = network_store_count

    cursor.close()
    conn.close()

    report_data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "monthly_start": MONTHLY_START,
        "weekly_start": WEEKLY_START,
        "weekly_end": WEEKLY_END,
        "partner_name": PARTNER_NAME,
        "partner_display_name": "LOKO від Сільпо",
        "city": "27 міст України",
        "monthly": {
            "financial": fin_m,
            "operational": ops_m,
            "replacement_adjustment": repl_m,
            "failed_orders": fail_m,
            "failed_reasons": fail_reasons_m,
            "campaigns": camp_m,
            "acceptance_availability": aa_m,
        },
        "weekly": {
            "financial": fin_w,
            "operational": ops_w,
            "replacement_adjustment": repl_w,
            "failed_orders": fail_w,
            "failed_reasons": fail_reasons_w,
            "campaigns": camp_w,
            "acceptance_availability": aa_w,
        },
        "acceptance_current": aa_current,
        "network_stores": network_stores,
        "network_store_count": network_store_count,
        "store_weekly": store_weekly,
        "customer_reviews": customer_reviews,
    }

    DATA_PATH.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Data saved to {DATA_PATH}")

    print("Generating index.html...")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    js_data = f"const REPORT_DATA = {json.dumps(report_data, ensure_ascii=False, default=str)};"
    html = template.replace("/*__REPORT_DATA__*/", js_data)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Done! Report written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
