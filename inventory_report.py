import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

# Loads .env locally. On Streamlit Community Cloud, values can be supplied via st.secrets.
load_dotenv(Path(__file__).with_name(".env"))

API_VERSION_DEFAULT = "2026-07"
WHATSAPP_DELAY_DEFAULT = 10
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CSV_PATH = DATA_DIR / "low_stock_report.csv"
UPDATED_PATH = DATA_DIR / "last_updated.txt"

PRODUCTS_QUERY = """
query GetProducts($after: String, $search: String!) {
  products(first: 100, after: $after, query: $search) {
    edges {
      cursor
      node {
        id
        title
        vendor
        status
        variants(first: 100) {
          nodes { id title inventoryQuantity sku }
          pageInfo { hasNextPage }
        }
      }
    }
    pageInfo { hasNextPage }
  }
}
"""

ORDERS_QUERY = """
query GetOrders($after: String, $search: String!) {
  orders(first: 100, after: $after, query: $search, sortKey: CREATED_AT, reverse: true) {
    edges {
      cursor
      node {
        createdAt
        cancelledAt
        test
        displayFinancialStatus
        lineItems(first: 100) {
          nodes { currentQuantity variant { id } }
          pageInfo { hasNextPage }
        }
      }
    }
    pageInfo { hasNextPage }
  }
}
"""

def get_setting(name: str, default: str = "") -> str:
    """Read Streamlit secrets first, then environment/.env."""
    try:
        value = st.secrets.get(name, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    return os.getenv(name, default).strip()

def shopify_config():
    store = get_setting("SHOPIFY_STORE_DOMAIN").replace("https://", "").replace("http://", "").strip("/")
    token = get_setting("SHOPIFY_ACCESS_TOKEN")
    version = get_setting("SHOPIFY_API_VERSION", API_VERSION_DEFAULT)
    if not store or not token:
        raise RuntimeError(
            "Shopify credentials are missing. Configure SHOPIFY_STORE_DOMAIN and "
            "SHOPIFY_ACCESS_TOKEN in local .env or Streamlit Cloud Secrets."
        )
    return f"https://{store}/admin/api/{version}/graphql.json", token

def shopify_query(query, variables=None):
    url, token = shopify_config()
    response = requests.post(
        url,
        headers={
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        },
        json={"query": query, "variables": variables or {}},
        timeout=90,
    )
    if response.status_code == 401:
        raise RuntimeError("Shopify returned 401 Unauthorized. Check the Admin API token and store domain.")
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"Shopify GraphQL error: {payload['errors']}")
    if "data" not in payload:
        raise RuntimeError(f"Unexpected Shopify response: {payload}")
    return payload["data"]

def fetch_products():
    """
    Treat a Shopify product as a group listing when it has >3 native variants.
    Skip products with >100 variants and exclude titles containing 'bundle deal'
    or 'pack of 5' (case-insensitive).
    """
    products, cursor = [], None
    while True:
        connection = shopify_query(
            PRODUCTS_QUERY,
            {"after": cursor, "search": "status:active"},
        )["products"]

        for edge in connection["edges"]:
            product = edge["node"]
            title = (product.get("title") or "").strip()
            title_lower = title.casefold()

            if "bundle deal" in title_lower or "pack of 5" in title_lower:
                continue

            variants_connection = product["variants"]
            if variants_connection["pageInfo"]["hasNextPage"]:
                print(f"Skipping >100 variants: {title}")
                continue

            variants = variants_connection["nodes"]
            if len(variants) <= 3:
                continue

            products.append({
                "id": product["id"],
                "title": title,
                "brand": (product.get("vendor") or "").strip() or "Other",
                "variants": variants,
            })

        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["edges"][-1]["cursor"]

    return products

def fetch_sales_last_28_days():
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=28)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sales = {}
    cursor = None

    while True:
        connection = shopify_query(
            ORDERS_QUERY,
            {"after": cursor, "search": f"created_at:>={start}"},
        )["orders"]

        for edge in connection["edges"]:
            order = edge["node"]
            if (
                order.get("cancelledAt")
                or order.get("test")
                or order.get("displayFinancialStatus") not in ("PAID", "PARTIALLY_REFUNDED")
            ):
                continue

            created_at = datetime.fromisoformat(order["createdAt"].replace("Z", "+00:00"))
            age_days = (now - created_at).total_seconds() / 86400
            if age_days < 0 or age_days > 28:
                continue

            line_items = order["lineItems"]
            if line_items["pageInfo"]["hasNextPage"]:
                raise RuntimeError(
                    "An order has more than 100 line items. This starter code needs line-item pagination for that order."
                )

            for item in line_items["nodes"]:
                variant = item.get("variant")
                if not variant:
                    continue
                variant_id = variant["id"]
                quantity = int(item.get("currentQuantity") or 0)
                totals = sales.setdefault(variant_id, {7: 0, 14: 0, 28: 0})
                totals[28] += quantity
                if age_days <= 14:
                    totals[14] += quantity
                if age_days <= 7:
                    totals[7] += quantity

        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["edges"][-1]["cursor"]

    return sales

def build_report():
    products = fetch_products()
    sales = fetch_sales_last_28_days()
    rows = []

    for product in products:
        for variant in product["variants"]:
            stock = variant.get("inventoryQuantity")
            if stock is None:
                continue

            totals = sales.get(variant["id"], {7: 0, 14: 0, 28: 0})
            stock = int(stock)
            sold_7 = int(totals[7])

            # THE ONLY risk threshold: stock must be lower than sales in the last 7 days.
            if stock >= sold_7:
                continue

            rows.append({
                "Product Name": product["title"],
                "Variant Name": variant["title"] if variant["title"] != "Default Title" else product["title"],
                "SKU": variant.get("sku") or "",
                "Brand": product["brand"],
                "Stock": stock,
                "7 Days": sold_7,
                "14 Days": int(totals[14]),
                "28 Days": int(totals[28]),
            })

    columns = ["Product Name", "Variant Name", "SKU", "Brand", "Stock", "7 Days", "14 Days", "28 Days"]
    report = pd.DataFrame(rows, columns=columns)
    if not report.empty:
        report = report.sort_values(["Brand", "Product Name", "Stock"], kind="stable").reset_index(drop=True)

    report.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    UPDATED_PATH.write_text(datetime.now().astimezone().isoformat(), encoding="utf-8")
    return report

def send_whatsapp_text(message: str):
    token = get_setting("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = get_setting("WHATSAPP_PHONE_NUMBER_ID")
    recipient = get_setting("WHATSAPP_TO_NUMBER")

    if not all([token, phone_number_id, recipient]):
        raise RuntimeError(
            "WhatsApp credentials missing. Configure WHATSAPP_ACCESS_TOKEN, "
            "WHATSAPP_PHONE_NUMBER_ID, and WHATSAPP_TO_NUMBER."
        )

    graph_version = get_setting("WHATSAPP_GRAPH_VERSION", "v23.0")
    url = f"https://graph.facebook.com/{graph_version}/{phone_number_id}/messages"
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": message},
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"WhatsApp send failed ({response.status_code}): {response.text[:500]}")
    result = response.json()
    return result.get("messages", [{}])[0].get("id", "accepted")

def send_whatsapp_report(report: pd.DataFrame, dashboard_url: str, delay_seconds: int = 10, progress_callback=None):
    """
    Sends the dashboard URL first, then one message per product.
    Every product message includes only variants present in the selected report.
    """
    dashboard_url = (dashboard_url or "").strip()
    if not dashboard_url.startswith("https://"):
        raise RuntimeError("Enter the actual public HTTPS Streamlit dashboard URL before sending.")

    send_whatsapp_text(f"Shopify Low-Stock Dashboard\nOpen report: {dashboard_url}")
    time.sleep(delay_seconds)

    if report.empty:
        send_whatsapp_text("Shopify low-stock report: no at-risk variants match this selection.")
        return 0

    groups = list(report.groupby("Product Name", sort=False))
    sent_products = 0
    for index, (product_name, rows) in enumerate(groups, start=1):
        lines = [
            str(product_name),
            "",
            "Variant | Stock | 7d | 14d | 28d",
        ]
        for _, row in rows.iterrows():
            lines.append(
                f"{row['Variant Name']} | {int(row['Stock'])} | "
                f"{int(row['7 Days'])} | {int(row['14 Days'])} | {int(row['28 Days'])}"
            )

        # Keep a safety margin below WhatsApp's text-message body limit.
        message = "\n".join(lines)
        if len(message) > 4000:
            message = message[:3950] + "\n…Message shortened due to length."

        send_whatsapp_text(message)
        sent_products += 1
        if progress_callback:
            progress_callback(index, len(groups), str(product_name))

        if index < len(groups):
            time.sleep(delay_seconds)

    return sent_products

def report_metadata():
    try:
        updated = UPDATED_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        updated = "Not generated yet"
    return updated
