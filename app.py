from datetime import datetime
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

if "report_df" not in st.session_state:
    st.session_state.report_df = None
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "highlight_periods" not in st.session_state:
    st.session_state.highlight_periods = {7, 14, 28}

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

# Equal-sized selling tiers based on each product's total 28-day sales.
if not all_df.empty:
    product_sales = all_df.groupby("Product Name")["Stock Sold in 28 Days"].sum().sort_values(ascending=False, kind="stable")
    product_count = len(product_sales)
    tiers = {}
    for rank, product_name in enumerate(product_sales.index):
        tier_index = min(2, (rank * 3) // max(product_count, 1))
        tiers[product_name] = ("High", "Medium", "Low")[tier_index]
    all_df["Selling"] = all_df["Product Name"].map(tiers)
else:
    all_df["Selling"] = pd.Series(dtype=str)

st.subheader("Filters")
all_brands = sorted(all_df["Brand"].dropna().astype(str).unique().tolist()) if not all_df.empty else []
f1, f2, f3 = st.columns([2, 2, 3])
with f1:
    selected_brands = st.multiselect("Brand", options=all_brands, default=all_brands)
with f2:
    selling_filter = st.selectbox("Selling", ["All", "High", "Medium", "Low"], index=0,
                                  help="Products are split into three approximately equal-sized groups by 28-day sales.")
with f3:
    search_text = st.text_input("Product filter", placeholder="e.g. hayati pro max 6000")

# The KPI counts respond to brand selection. They intentionally do not depend on
# selling/search filters so they remain useful brand-level totals.
if selected_brands:
    brand_df = all_df[all_df["Brand"].isin(selected_brands)].copy()
else:
    brand_df = all_df.iloc[0:0].copy()
risk_counts = {
    days: int((brand_df["Stock"] < brand_df[f"Stock Sold in {days} Days"]).sum())
    for days in (7, 14, 28)
}

st.subheader("At-risk variants — click to highlight")
k1, k2, k3 = st.columns(3)
for col, days, label, color in [
    (k1, 7, "7-day at-risk variants", "🔴"),
    (k2, 14, "14-day at-risk variants", "🟡"),
    (k3, 28, "28-day at-risk variants", "🟢"),
]:
    with col:
        active = days in st.session_state.highlight_periods
        button_label = f"{color} {label}\n{risk_counts[days]:,}  {'✓' if active else ''}"
        if st.button(button_label, key=f"toggle_risk_{days}", use_container_width=True):
            if active:
                st.session_state.highlight_periods.remove(days)
            else:
                st.session_state.highlight_periods.add(days)
            st.rerun()
st.caption("Selected cards highlight matching rows; they do not hide products or columns. Multiple periods can be selected.")

# Existing filters determine visible products. KPI selections only affect row highlighting.
filtered_all = all_df.copy()
if selected_brands:
    filtered_all = filtered_all[filtered_all["Brand"].isin(selected_brands)]
else:
    filtered_all = filtered_all.iloc[0:0]
if selling_filter != "All":
    filtered_all = filtered_all[filtered_all["Selling"] == selling_filter]
if search_text.strip():
    terms = [term.casefold() for term in search_text.split() if term.strip()]
    searchable = (filtered_all["Product Name"].fillna("").astype(str) + " " +
                  filtered_all["Variant Name"].fillna("").astype(str) + " " +
                  filtered_all["Brand"].fillna("").astype(str)).str.casefold()
    mask = pd.Series(True, index=filtered_all.index)
    for term in terms:
        mask &= searchable.str.contains(term, regex=False, na=False)
    filtered_all = filtered_all[mask]

st.write(f"Products shown: **{len(filtered_all)} variants** across **{filtered_all['Product Name'].nunique() if not filtered_all.empty else 0} products**.")
st.subheader("Product report")
display_cols = [
    "Brand", "Product Name", "Variant Name", "Selling", "Stock",
    "Stock Sold in 7 Days", "Stock Sold in 14 Days", "Stock Sold in 28 Days",
    "Stock Required for Next 7 Days", "Stock Required for Next 14 Days", "Stock Required for Next 28 Days",
]

# Row colour priority: red (7d) > yellow (14d) > green (28d).
def highlight_risk_rows(row):
    selected = st.session_state.highlight_periods
    risk7 = 7 in selected and row["Stock"] < row["Stock Sold in 7 Days"]
    risk14 = 14 in selected and row["Stock"] < row["Stock Sold in 14 Days"]
    risk28 = 28 in selected and row["Stock"] < row["Stock Sold in 28 Days"]
    if risk7:
        bg, fg = "#7F1D1D", "#FFFFFF"
    elif risk14:
        bg, fg = "#806000", "#FFFFFF"
    elif risk28:
        bg, fg = "#14532D", "#FFFFFF"
    else:
        bg, fg = "", ""
    return [f"background-color: {bg}; color: {fg};" if bg else "" for _ in row]

styled = filtered_all[display_cols].style.apply(highlight_risk_rows, axis=1)
st.dataframe(styled, use_container_width=True, hide_index=True, height=1100)
st.caption("Row priority: red = 7-day risk; yellow = 14-day risk; green = 28-day risk. If a variant qualifies for multiple periods, it appears once in the highest-priority colour.")

st.subheader("Download CSV report")
st.caption("Select one period. The CSV contains only variants at risk for that period, with common product details and only the matching sales and required-stock columns.")
period = st.radio("Report period", ["7 Days", "14 Days", "28 Days"], horizontal=True, index=0)
days = int(period.split()[0])
sales_col = f"Stock Sold in {period}"
required_col = f"Stock Required for Next {period}"
period_report = filtered_all[filtered_all["Stock"] < filtered_all[sales_col]].copy()
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
        seven_day = filtered_all[filtered_all["Stock"] < filtered_all["Stock Sold in 7 Days"]]
        run_send(seven_day, "filtered 7-day report")
with wa2:
    if st.button("📨 Send COMPLETE 7-day report", use_container_width=True):
        seven_day_all = all_df[all_df["Stock"] < all_df["Stock Sold in 7 Days"]]
        run_send(seven_day_all, "complete 7-day report")

st.divider()
st.caption("Keep credentials in Streamlit Secrets or local .env; never commit tokens to GitHub. Restrict dashboard access because it contains inventory data and can trigger WhatsApp messages.")
