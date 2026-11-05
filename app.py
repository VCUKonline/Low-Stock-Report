import time
from datetime import datetime
import pandas as pd
import streamlit as st

from inventory_report import build_report, report_metadata, send_whatsapp_report, get_setting

st.set_page_config(page_title="Shopify Low-Stock Report", page_icon="📦", layout="wide")
st.title("Shopify Low-Stock Risk Dashboard")
st.caption("Group listings only • Each report uses its own stock-versus-sales threshold")

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
                st.success(f"Loaded {len(st.session_state.report_df)} group-listing variants.")
            except Exception as exc:
                st.error(f"Refresh failed: {exc}")
    st.caption("Downloads use the currently loaded data. Refresh to fetch current Shopify stock and sales.")

if st.session_state.report_df is None:
    st.info("Click **Refresh Shopify data** in the sidebar to load group listings.")
    st.stop()

all_df = st.session_state.report_df.copy()
last_updated = st.session_state.last_refresh or report_metadata()
st.caption(f"Report last refreshed: {last_updated}")

def at_risk(frame, days):
    return frame[frame["Stock"] < frame[f"{days} Days"]].copy()

risk7_all = at_risk(all_df, 7)
risk14_all = at_risk(all_df, 14)
risk28_all = at_risk(all_df, 28)

m1, m2, m3 = st.columns(3)
m1.metric("7-day at-risk variants", len(risk7_all))
m2.metric("14-day at-risk variants", len(risk14_all))
m3.metric("28-day at-risk variants", len(risk28_all))

st.subheader("Filter reports")
all_brands = sorted(all_df["Brand"].dropna().astype(str).unique().tolist()) if not all_df.empty else []
selected_brands = st.multiselect(
    "Brand", options=all_brands, default=all_brands,
    help="All report downloads and WhatsApp sends use this brand selection."
)
search_text = st.text_input("Search product, variant, or SKU", placeholder="Type product, variant, or SKU")

filtered_all = all_df.copy()
if selected_brands:
    filtered_all = filtered_all[filtered_all["Brand"].isin(selected_brands)]
else:
    filtered_all = filtered_all.iloc[0:0]
if search_text.strip():
    q = search_text.strip()
    mask = (
        filtered_all["Product Name"].astype(str).str.contains(q, case=False, na=False)
        | filtered_all["Variant Name"].astype(str).str.contains(q, case=False, na=False)
        | filtered_all["SKU"].astype(str).str.contains(q, case=False, na=False)
    )
    filtered_all = filtered_all[mask]

risk7 = at_risk(filtered_all, 7)
risk14 = at_risk(filtered_all, 14)
risk28 = at_risk(filtered_all, 28)

st.write(f"Filtered group listings: **{len(filtered_all)} variants** across **{filtered_all['Product Name'].nunique() if not filtered_all.empty else 0} products**.")
st.subheader("All group listings")
all_cols = [
    "Product Name", "Variant Name", "SKU", "Brand", "Stock", "7 Days", "14 Days", "28 Days",
    "Additional Stock Required 7 Days (Outers)",
    "Additional Stock Required 14 Days (Outers)",
    "Additional Stock Required 28 Days (Outers)",
]
st.dataframe(filtered_all[all_cols], use_container_width=True, hide_index=True)

st.subheader("Download reports")
st.caption("Each threshold report includes only variants whose stock is below sales for that period. All group listings includes every filtered variant, regardless of threshold.")
def csv_bytes(frame):
    return frame.to_csv(index=False).encode("utf-8-sig")

cols7 = ["Product Name", "Variant Name", "SKU", "Brand", "Stock", "7 Days"]
cols14 = ["Product Name", "Variant Name", "SKU", "Brand", "Stock", "14 Days"]
cols28 = ["Product Name", "Variant Name", "SKU", "Brand", "Stock", "28 Days"]
d1, d2, d3, d4 = st.columns(4)
with d1:
    st.download_button(f"⬇️ 7-day report ({len(risk7)})", csv_bytes(risk7[cols7]), "low_stock_7_day.csv", "text/csv", use_container_width=True)
with d2:
    st.download_button(f"⬇️ 14-day report ({len(risk14)})", csv_bytes(risk14[cols14]), "low_stock_14_day.csv", "text/csv", use_container_width=True)
with d3:
    st.download_button(f"⬇️ 28-day report ({len(risk28)})", csv_bytes(risk28[cols28]), "low_stock_28_day.csv", "text/csv", use_container_width=True)
with d4:
    st.download_button(f"⬇️ All group listings ({len(filtered_all)})", csv_bytes(filtered_all[all_cols]), "all_group_listings.csv", "text/csv", use_container_width=True)

st.subheader("Send report link and product messages to WhatsApp")
dashboard_url = st.text_input(
    "Public dashboard URL", value=get_setting("DASHBOARD_URL"),
    placeholder="https://your-app-name.streamlit.app",
    help="Use your deployed public HTTPS URL."
)
delay = st.number_input("Delay between WhatsApp messages (seconds)", min_value=10, max_value=120, value=10, step=1)
st.caption("WhatsApp sends the dashboard link and then one message per product for the 7-day at-risk report.")
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
        st.info("API acceptance does not guarantee delivery; check WhatsApp delivery status if messages do not arrive.")
    except Exception as exc:
        st.error(f"Sending stopped: {exc}. Earlier messages may already have been sent; check WhatsApp before retrying.")

with wa1:
    if st.button("📲 Send FILTERED 7-day report", use_container_width=True):
        run_send(risk7, "filtered 7-day report")
with wa2:
    if st.button("📨 Send COMPLETE 7-day report", use_container_width=True):
        run_send(risk7_all, "complete 7-day report")

st.divider()
st.caption("Keep credentials in Streamlit Secrets or local .env; never commit tokens to GitHub. Restrict dashboard access because it contains inventory data and can trigger WhatsApp messages.")
