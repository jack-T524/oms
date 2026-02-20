import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import io

st.set_page_config(page_title="雲端理單控制台", layout="wide")
st.title("📦 雲端化電商出貨後台系統 (連動 Google 試算表)")

# ==========================================
# 1. 連線到 Google Sheets
# ==========================================
@st.cache_resource
def init_connection():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    # 讀取雲端後台設定的安全金鑰
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(st.secrets["spreadsheet_url"])
    return sheet

try:
    sheet = init_connection()
    ws_orders = sheet.worksheet("Orders")
    ws_customers = sheet.worksheet("Customers")
except Exception as e:
    st.error(f"⚠️ 系統連線 Google 試算表失敗，真實錯誤為： {e}")
    st.stop()

# ==========================================
# 2. 輔助函式與資料讀取
# ==========================================
def parse_boss_text(text):
    parts = text.split()
    if len(parts) >= 4:
        return {"item": parts[0], "price": parts[1], "name": parts[2], "qty": parts[3]}
    return {"item": "", "price": "", "name": "", "qty": ""}

# 即時抓取試算表資料轉成 DataFrame
df_orders = pd.DataFrame(ws_orders.get_all_records())
df_customers = pd.DataFrame(ws_customers.get_all_records())
# 確保欄位型態一致
if not df_customers.empty:
    df_customers['姓名'] = df_customers['姓名'].astype(str)

# ==========================================
# 3. 系統介面設計
# ==========================================
tab1, tab2, tab3 = st.tabs(["⚡ 快速建單", "📋 訂單看板與出貨", "👥 熟客資料庫"])

# ----------------- 分頁 1: 快速建單 -----------------
with tab1:
    st.subheader("1. 從老闆訊息建單")
    boss_text = st.text_input("貼上老闆的文字 (範例: 蘋果 500 王大明 2)", "")
    parsed = parse_boss_text(boss_text)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1: item = st.text_input("品項", parsed['item'])
    with col2: price = st.number_input("單價", value=int(parsed['price']) if parsed['price'].isdigit() else 0)
    with col3: name = st.text_input("客戶姓名", parsed['name'])
    with col4: qty = st.number_input("數量", value=int(parsed['qty']) if parsed['qty'].isdigit() else 1, min_value=1)
    
    shipping = st.number_input("預設運費", value=100)
    total_price = (price * qty) + shipping
    st.info(f"💰 系統自動試算總金額：( {price} * {qty} ) + {shipping} = **{total_price}** 元")

    if name:
        # 在 Google 試算表資料中尋找熟客
        known_cust = df_customers[df_customers['姓名'] == name] if not df_customers.empty else pd.DataFrame()
        
        if not known_cust.empty:
            phone = known_cust.iloc[0]['電話']
            address = known_cust.iloc[0]['地址']
            st.success(f"✅ 偵測到熟客！電話：{phone}, 地址：{address}")
            status = "可出貨"
        else:
            st.warning("⚠️ 新客或缺少收件資訊，請手動補齊或先存為『待確認』")
            new_phone = st.text_input("補齊電話 (選填)")
            new_address = st.text_input("補齊地址 (選填)")
            status = "待確認" if not new_phone or not new_address else "可出貨"
            
            msg = f"您好，您訂購的 [{item}] [{qty}] 個，加上運費總計為 [{total_price}] 元。麻煩您提供收件人的『電話』與『地址』以便為您安排出貨，謝謝！"
            st.text_area("複製給客人的確認訊息：", msg, height=100)

    if st.button("💾 寫入雲端資料庫", type="primary"):
        if name and item:
            date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
            order_id = len(df_orders) + 1
            
            # 直接將一行資料寫入 Google 試算表
            ws_orders.append_row([order_id, date_now, name, item, qty, price, shipping, total_price, status])
            
            # 如果有填寫新電話地址，寫入 Customers 試算表
            if 'new_phone' in locals() and new_phone and new_address:
                ws_customers.append_row([name, new_phone, new_address])
                
            st.success("✅ 訂單已成功寫入 Google 試算表！")
            st.rerun()

# ----------------- 分頁 2: 訂單看板與出貨 -----------------
with tab2:
    st.subheader("2. 雲端訂單與匯出")
    st.dataframe(df_orders, use_container_width=True)
    
    st.divider()
    df_ready = df_orders[df_orders['狀態'] == '可出貨'].copy() if not df_orders.empty else pd.DataFrame()
    
    if not df_ready.empty:
        total_sum = df_ready['總金額'].sum()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_ready.to_excel(writer, index=False, sheet_name='出貨單')
            worksheet = writer.sheets['出貨單']
            last_row = len(df_ready) + 2
            worksheet.cell(row=last_row, column=7, value="總計金額:")
            worksheet.cell(row=last_row, column=8, value=total_sum)
            
        st.download_button(
            label="📥 下載「可出貨」訂單 Excel",
            data=output.getvalue(),
            file_name=f"出貨單_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
    else:
        st.info("目前沒有『可出貨』狀態的訂單。")

# ----------------- 分頁 3: CRM 資料庫 -----------------
with tab3:
    st.subheader("3. 雲端客戶通訊錄")
    st.dataframe(df_customers, use_container_width=True)
