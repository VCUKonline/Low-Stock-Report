from datetime import datetime
from pathlib import Path
import re
import pandas as pd
import streamlit as st

from inventory_report import build_report, report_metadata, send_whatsapp_report, get_setting

st.set_page_config(page_title="Vape Connect Stock & Sales Dashboard", page_icon="📦", layout="wide")

# Brand styling and a tall report area for viewing many variants at once.
st.markdown("""
<style>
  .vc-title {font-size: 2.55rem; font-weight: 850; line-height: 1.05; margin: 0;}
  .vc-title .white {color: #F7F7F7;}
  .vc-title .red {color: #EF4444;}
  div[data-testid="stDataFrame"] {width: 100%;}
  div[data-testid="stMetric"] {background: #171717; border: 1px solid #383838; padding: 12px 16px; border-radius: 12px;}
</style>
<div class="vc-title"><span class="white">VAPE CONNECT</span><br><span class="red">Stock &amp; Sales Dashboard</span></div>
""", unsafe_allow_html=True)

CATEGORY_FILE = Path(__file__).with_name("Product_selling_category.csv")


def normalize_key(value):
    """Normalize product/vendor text for reliable CSV-to-Shopify matching."""
    value = "" if pd.isna(value) else str(value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def load_selling_categories():
    if not CATEGORY_FILE.exists():
        raise FileNotFoundError(
            "Product_selling_category.csv was not found. Upload it beside app.py in the GitHub repository."
        )
    category_df = pd.read_csv(CATEGORY_FILE)
    required = {"Product Name", "Brand", "Priority"}
    missing = required.difference(category_df.columns)
    if missing:
        raise ValueError(f"Selling category CSV is missing columns: {', '.join(sorted(missing))}")

    category_df = category_df.copy()
    category_df["_product_key"] = category_df["Product Name"].map(normalize_key)
    category_df["_brand_key"] = category_df["Brand"].map(normalize_key)
    category_df["Selling"] = category_df["Priority"].astype("string").str.strip().str.title()
    category_df.loc[~category_df["Selling"].isin(["High", "Medium", "Low"]), "Selling"] = pd.NA

    # Only use valid classifications. If the CSV has duplicate product+brand keys,
    # the last valid row wins (the uploaded file is expected to have one row per product).
    category_df = category_df.dropna(subset=["Selling"])
    return category_df.drop_duplicates(["_product_key", "_brand_key"], keep="last").set_index(["_product_key", "_brand_key"])["Selling"]


if "report_df" not in st.session_state:
    st.session_state.report_df = None
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "selected_selling_category" not in st.session_state:
    st.session_state.selected_selling_category = None
if "selected_risk_periods" not in st.session_state:
    st.session_state.selected_risk_periods = set()

with st.sidebar:
    st.header("Report controls")
    if st.button("🔄 Refresh Shopify data", use_container_width=True):
        with st.spinner("Fetching Shopify products, stock and order sales..."):
            try:
                st.session_state.report_df = build_report()
                st.session_state.last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.success(f"Loaded {len(st.session_state.report_df)} variants.")
            except Exception as exc:
                st.error(f"Refresh failed: {exc}")
    st.caption("Downloads use the currently loaded data. Refresh to fetch current Shopify stock and sales.")

if st.session_state.report_df is None:
    st.info("Click **Refresh Shopify data** in the sidebar to load inventory and sales.")
    st.stop()

all_df = st.session_state.report_df.copy()
last_updated = st.session_state.last_refresh or report_metadata()
st.caption(f"Report last refreshed: {last_updated}")

# Assign selling categories from the supplied CSV. No automatic/equal split is performed.
try:
    category_lookup = load_selling_categories()
    all_df["_product_key"] = all_df["Product Name"].map(normalize_key)
    all_df["_brand_key"] = all_df["Brand"].map(normalize_key)
    all_df["Selling"] = [
        category_lookup.get((product_key, brand_key), pd.NA)
        for product_key, brand_key in zip(all_df["_product_key"], all_df["_brand_key"])
    ]
    all_df["Selling"] = all_df["Selling"].fillna("Unclassified")
except Exception as exc:
    st.error(f"Unable to load selling categories: {exc}")
    st.stop()

st.subheader("Filters")
all_brands = sorted(all_df["Brand"].dropna().astype(str).unique().tolist()) if not all_df.empty else []
f1, f2 = st.columns([2, 3])
with f1:
    selected_brands = st.multiselect("Brand", options=all_brands, default=all_brands)
with f2:
    search_text = st.text_input("Product filter", placeholder="e.g. hayati pro max 6000")

# Base dashboard frame: brand and product search apply to every dashboard view.
dashboard_base = all_df.copy()
if selected_brands:
    dashboard_base = dashboard_base[dashboard_base["Brand"].isin(selected_brands)]
else:
    dashboard_base = dashboard_base.iloc[0:0]
if search_text.strip():
    terms = [term.casefold() for term in search_text.split() if term.strip()]
    searchable = (
        dashboard_base["Product Name"].fillna("").astype(str) + " " +
        dashboard_base["Variant Name"].fillna("").astype(str) + " " +
        dashboard_base["Brand"].fillna("").astype(str)
    ).str.casefold()
    mask = pd.Series(True, index=dashboard_base.index)
    for term in terms:
        mask &= searchable.str.contains(term, regex=False, na=False)
    dashboard_base = dashboard_base[mask]

# KPI counts respond to selected brands and product search, but not selling/risk toggles.
risk_counts = {
    days: int((dashboard_base["Stock"] < dashboard_base[f"Stock Sold in {days} Days"]).sum())
    for days in (7, 14, 28)
}

st.subheader("Selling category — sourced from Product_selling_category.csv")
selling_cols = st.columns(4)
for col, category, label in zip(
    selling_cols,
    ["High", "Medium", "Low", None],
    ["🔴 HIGH", "🟡 MEDIUM", "⚪ LOW", "Clear category"],
):
    with col:
        is_active = st.session_state.selected_selling_category == category
        if st.button(("✓ " if is_active else "") + label, key=f"selling_{category or 'clear'}", use_container_width=True):
            st.session_state.selected_selling_category = None if is_active else category
            st.rerun()

st.subheader("At-risk period — additional dashboard filter")
risk_cols = st.columns(3)
for col, days, label, color in [
    (risk_cols[0], 7, "7-day at-risk", "🔴"),
    (risk_cols[1], 14, "14-day at-risk", "🟡"),
    (risk_cols[2], 28, "28-day at-risk", "🟢"),
]:
    with col:
        active = days in st.session_state.selected_risk_periods
        button_label = f"{color} {label}: {risk_counts[days]:,}" + (" ✓" if active else "")
        if st.button(button_label, key=f"toggle_risk_{days}", use_container_width=True):
            if active:
                st.session_state.selected_risk_periods.remove(days)
            else:
                st.session_state.selected_risk_periods.add(days)
            st.rerun()
st.caption("Selling and risk selections are dashboard filters only. If no risk period is selected, all products in the selected selling category remain visible and risk colours are still applied.")

# Dashboard filters: category selection excludes products absent from the category CSV (Option B).
dashboard_df = dashboard_base.copy()
if st.session_state.selected_selling_category:
    dashboard_df = dashboard_df[dashboard_df["Selling"] == st.session_state.selected_selling_category]

# Risk period buttons filter to the UNION of selected periods. With none selected, show all category matches.
selected_periods = st.session_state.selected_risk_periods
if selected_periods:
    risk_mask = pd.Series(False, index=dashboard_df.index)
    for days in selected_periods:
        risk_mask |= dashboard_df["Stock"] < dashboard_df[f"Stock Sold in {days} Days"]
    dashboard_df = dashboard_df[risk_mask]

st.write(
    f"Products shown: **{len(dashboard_df)} variants** across "
    f"**{dashboard_df['Product Name'].nunique() if not dashboard_df.empty else 0} products**."
)
st.subheader("Product report")
display_cols = [
    "Brand", "Product Name", "Variant Name", "Selling", "Stock",
    "Stock Sold in 7 Days", "Stock Sold in 14 Days", "Stock Sold in 28 Days",
    "Stock Required for Next 7 Days", "Stock Required for Next 14 Days", "Stock Required for Next 28 Days",
]

# Row colour always reflects the most urgent risk, regardless of selected risk-period filter.
def highlight_risk_rows(row):
    risk7 = row["Stock"] < row["Stock Sold in 7 Days"]
    risk14 = row["Stock"] < row["Stock Sold in 14 Days"]
    risk28 = row["Stock"] < row["Stock Sold in 28 Days"]
    if risk7:
        bg, fg = "#7F1D1D", "#FFFFFF"
    elif risk14:
        bg, fg = "#806000", "#FFFFFF"
    elif risk28:
        bg, fg = "#14532D", "#FFFFFF"
    else:
        bg, fg = "", ""
    return [f"background-color: {bg}; color: {fg};" if bg else "" for _ in row]

styled = dashboard_df[display_cols].style.apply(highlight_risk_rows, axis=1)
st.dataframe(styled, use_container_width=True, hide_index=True, height=1100)
st.caption("Row priority: red = 7-day risk; yellow = 14-day risk; green = 28-day risk. If a variant qualifies for multiple periods, it appears once in red.")

# CSV logic remains independent of the new dashboard-only risk-period buttons.
# Brand, product search and selected selling category continue to scope the same report data.
csv_base = dashboard_base.copy()
if st.session_state.selected_selling_category:
    csv_base = csv_base[csv_base["Selling"] == st.session_state.selected_selling_category]

st.subheader("Download CSV report")
st.caption("Select one period. The CSV contains only variants at risk for that period, with common product details and only the matching sales and required-stock columns.")
period = st.radio("Report period", ["7 Days", "14 Days", "28 Days"], horizontal=True, index=0)
days = int(period.split()[0])
sales_col = f"Stock Sold in {period}"
required_col = f"Stock Required for Next {period}"
period_report = csv_base[csv_base["Stock"] < csv_base[sales_col]].copy()
report_cols = ["Product Name", "Variant Name", "Brand", "Selling", "Stock", sales_col, required_col]
st.download_button(
    f"⬇️ Download {period} CSV ({len(period_report)} variants)",
    period_report[report_cols].to_csv(index=False).encode("utf-8-sig"),
    f"low_stock_{days}_day.csv", "text/csv", use_container_width=True,
)

st.subheader("Send report link and product messages to WhatsApp")
dashboard_url = st.text_input("Public dashboard URL", value=get_setting("DASHBOARD_URL"), placeholder="https://your-app-name.streamlit.app")
delay = st.number_input("Delay between WhatsApp messages (seconds)", min_value=10, max_value=120, value=10, step=1)
st.caption("WhatsApp sends the dashboard link and one message per product for the filtered 7-day at-risk report.")
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
        seven_day = csv_base[csv_base["Stock"] < csv_base["Stock Sold in 7 Days"]]
        run_send(seven_day, "filtered 7-day report")
with wa2:
    if st.button("📨 Send COMPLETE 7-day report", use_container_width=True):
        seven_day_all = all_df[all_df["Stock"] < all_df["Stock Sold in 7 Days"]]
        run_send(seven_day_all, "complete 7-day report")

st.divider()
st.caption("Keep credentials in Streamlit Secrets or local .env; never commit tokens to GitHub. Restrict dashboard access because it contains inventory data and can trigger WhatsApp messages.")
