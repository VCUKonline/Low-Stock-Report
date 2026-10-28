# Shopify Low-Stock Streamlit Dashboard

## Rules implemented
- Active Shopify products only.
- Group listings are assumed to be native Shopify products with more than 3 variants.
- Skips products with more than 100 variants.
- Excludes product titles containing `bundle deal` or `pack of 5` (case-insensitive).
- The only risk threshold is: **current stock < units sold in the last 7 days**.
- Report includes stock and 7-, 14-, and 28-day sales.
- Brand and product/variant/SKU search filters.
- Download buttons for 7-day, 14-day, 28-day, and full-detail CSVs; all downloads contain rows that passed the 7-day risk threshold.
- WhatsApp button can send either filtered results or the complete report.
- Sends dashboard URL first, then one WhatsApp message per product, with a 10-second default delay between messages.

## Local setup (Windows)
1. Extract the ZIP to a folder.
2. Open Anaconda Prompt or CMD in that folder.
3. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
   If using Anaconda/Jupyter, use the same Python environment where Streamlit is installed.
4. Copy `.env.example` to `.env` and enter your actual credentials.
5. Run:
   ```bash
   python -m streamlit run app.py
   ```
6. Click **Refresh Shopify data**.

## Streamlit Community Cloud setup
1. Put `app.py`, `inventory_report.py`, `requirements.txt`, and `README.md` in a private GitHub repository. Do not upload `.env`.
2. In Streamlit Community Cloud, create an app pointing to `app.py`.
3. In app settings, add these values under **Secrets** using TOML syntax:
   ```toml
   SHOPIFY_STORE_DOMAIN = "yourstore.myshopify.com"
   SHOPIFY_ACCESS_TOKEN = "your_shopify_admin_api_access_token"
   SHOPIFY_API_VERSION = "2026-07"

   WHATSAPP_ACCESS_TOKEN = "your_whatsapp_cloud_api_access_token"
   WHATSAPP_PHONE_NUMBER_ID = "your_whatsapp_phone_number_id"
   WHATSAPP_TO_NUMBER = "countrycodeandnumber"
   WHATSAPP_GRAPH_VERSION = "v23.0"

   DASHBOARD_URL = "https://your-app-name.streamlit.app"
   ```
   Replace every placeholder. Do not include these secrets in Python files or GitHub commits.
4. Deploy, copy the actual assigned URL, then update `DASHBOARD_URL` in Secrets if needed.
5. Refresh the report and test downloads before sending WhatsApp messages.

## Notes and limitations
- `localhost` is only accessible from the computer running Streamlit. Use the deployed `https://...streamlit.app` URL for WhatsApp sharing.
- Protect the public dashboard before sharing. Anyone who can access an unprotected dashboard may see inventory data and may be able to trigger WhatsApp messages. Add authentication/access controls before public use.
- WhatsApp API acceptance is not proof of delivery. For business-initiated messages outside the customer-service window, an approved WhatsApp template may be required.
- The script counts sales from orders created in the last 28 days, using `currentQuantity` from paid or partially-refunded orders. Verify this matches your store's reporting rules.
- Shopify `inventoryQuantity` is used as the stock value. Confirm that this field matches your preferred stock/location calculation.
- If a single order has more than 100 line items, the starter implementation stops with an explicit error rather than silently omitting line items.
- “Group listing” means one Shopify product with more than 3 native variants. If your group listings are created by a grouping app as separate Shopify products, this rule must be adapted to your catalog structure.
- Sending to WhatsApp uses the configured recipient number. Do not share the access token.
