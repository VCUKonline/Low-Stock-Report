import time
from datetime import datetime
import pandas as pd
import streamlit as st

from inventory_report import (
    build_report,
    report_metadata,
    send_whatsapp_report,
    get_setting,
)

st.set_page_config(page_title="Shopify Low-Stock Report", page_icon="📦", layout="wide")
st.title("Shopify Low-Stock Risk Dashboard")
st.caption("Group listings only • Risk threshold: current stock < units sold in the last 7 days")

if "report_df" not in st.session_state:
    st.session_state.report_df = None
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None

with st.sidebar:
    st.header("Report controls")
    if st.button("🔄 Refresh Shopify data", use_container_width=True):
        with st.spinner("Fetching Shopify products, stock and order sales..."):
            try:
                st.session_state.report_df = build_report()
                st.session_state.last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.success(f"Loaded {len(st.session_state.report_df)} at-risk variants.")
            except Exception as exc:
                st.error(f"Refresh failed: {exc}")

    st.caption("Refresh fetches current Shopify data. Download buttons use the report currently loaded in this session.")

if st.session_state.report_df is None:
    st.info("Click **Refresh Shopify data** in the sidebar to load the latest report.")
    st.stop()

full_df = st.session_state.report_df.copy()
last_updated = st.session_state.last_refresh or report_metadata()
st.caption(f"Report last refreshed: {last_updated}")

products_at_risk = full_df["Product Name"].nunique() if not full_df.empty else 0
brands_at_risk = full_df["Brand"].nunique() if not full_df.empty else 0
m1, m2, m3 = st.columns(3)
m1.metric("At-risk variants", len(full_df))
m2.metric("At-risk products", products_at_risk)
m3.metric("Brands represented", brands_at_risk)

st.subheader("Filter report")
all_brands = sorted(full_df["Brand"].dropna().astype(str).unique().tolist()) if not full_df.empty else []
selected_brands = st.multiselect("Brand", options=all_brands, default=all_brands, help="Choose one or more brands. Downloads and filtered WhatsApp sends use this selection.")
search_text = st.text_input("Search product or variant", placeholder="Type product or variant name")

filtered_df = full_df.copy()
if selected_brands:
    filtered_df = filtered_df[filtered_df["Brand"].isin(selected_brands)]
else:
    filtered_df = filtered_df.iloc[0:0]
if search_text.strip():
    mask = (
        filtered_df["Product Name"].astype(str).str.contains(search_text.strip(), case=False, na=False)
        | filtered_df["Variant Name"].astype(str).str.contains(search_text.strip(), case=False, na=False)
        | filtered_df["SKU"].astype(str).str.contains(search_text.strip(), case=False, na=False)
    )
    filtered_df = filtered_df[mask]

st.write(f"Showing **{len(filtered_df)} at-risk variants** across **{filtered_df['Product Name'].nunique() if not filtered_df.empty else 0} products**.")

display_cols = ["Product Name", "Variant Name", "SKU", "Brand", "Stock", "7 Days", "14 Days", "28 Days"]
st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)

st.subheader("Download reports")
st.caption("All three downloads use the same 7-day risk rule. Each button provides the selected sales-window column alongside stock and product details.")
d1, d2, d3, d4 = st.columns(4)

def csv_bytes(frame):
    return frame.to_csv(index=False).encode("utf-8-sig")

download_7 = ["Product Name", "Variant Name", "SKU", "Brand", "Stock", "7 Days"]
download_14 = ["Product Name", "Variant Name", "SKU", "Brand", "Stock", "14 Days"]
download_28 = ["Product Name", "Variant Name", "SKU", "Brand", "Stock", "28 Days"]

with d1:
    st.download_button("⬇️ Download 7-day report", csv_bytes(filtered_df[download_7]), "low_stock_7_day.csv", "text/csv", use_container_width=True)
with d2:
    st.download_button("⬇️ Download 14-day report", csv_bytes(filtered_df[download_14]), "low_stock_14_day.csv", "text/csv", use_container_width=True)
with d3:
    st.download_button("⬇️ Download 28-day report", csv_bytes(filtered_df[download_28]), "low_stock_28_day.csv", "text/csv", use_container_width=True)
with d4:
    st.download_button("⬇️ Download full detail", csv_bytes(filtered_df[display_cols]), "low_stock_full_detail.csv", "text/csv", use_container_width=True)

st.subheader("Send report link and product messages to WhatsApp")
dashboard_url = st.text_input(
    "Public dashboard URL",
    value=get_setting("DASHBOARD_URL"),
    placeholder="https://your-app-name.streamlit.app",
    help="Use your deployed public HTTPS URL. localhost links will not work for your team.",
)
delay = st.number_input("Delay between WhatsApp messages (seconds)", min_value=10, max_value=120, value=10, step=1)
st.caption("The dashboard link is sent first. Then one message per product is sent, containing all matching at-risk variants. A 10-second delay is applied between messages.")

confirm_send = st.checkbox("I understand this will send real WhatsApp messages to the configured recipient.")
wa1, wa2 = st.columns(2)

def run_send(frame, label):
    if not confirm_send:
        st.warning("Tick the confirmation checkbox before sending.")
        return
    if not dashboard_url.strip().startswith("https://"):
        st.error("Enter your deployed public HTTPS dashboard URL first.")
        return
    progress = st.progress(0, text="Preparing WhatsApp messages...")
    status = st.empty()

    def update_progress(index, total, product):
        progress.progress(index / max(total, 1), text=f"Sent product {index} of {total}")
        status.write(f"Last processed product: **{product}**")

    try:
        with st.spinner(f"Sending {label}... keep this page open until complete."):
            count = send_whatsapp_report(frame, dashboard_url.strip(), int(delay), update_progress)
        progress.progress(1.0, text="Finished")
        st.success(f"WhatsApp send process finished. Product messages sent: {count}.")
        st.info("The WhatsApp API accepting a message does not guarantee delivery. Check WhatsApp delivery status if messages do not arrive.")
    except Exception as exc:
        st.error(f"Sending stopped: {exc}. Earlier messages may already have been sent; check WhatsApp before retrying.")

with wa1:
    if st.button("📲 Send FILTERED report", use_container_width=True):
        run_send(filtered_df, "filtered report")
with wa2:
    if st.button("📨 Send COMPLETE report", use_container_width=True):
        run_send(full_df, "complete report")

st.divider()
st.caption("Security: do not commit .env or tokens to GitHub. Protect this dashboard before sharing publicly because it contains inventory data and can trigger WhatsApp messages.")
