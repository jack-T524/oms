import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import io

# ==========================================
# 1. 系統設定與 Google 試算表連線
# ==========================================
st.set_page_config(page_title="超級客服與理單控制台", layout="wide")

# ⚠️ 請把這裡換成你剛剛建立的 Google 試算表網址
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1fPnXxVa1YhxnD8_eVneCjZNdlAx60LdIoycRO2ubSKU/edit?gid=845570727#gid=845570727"

@st.cache_resource
def connect_gspread():
    """透過 Streamlit Secrets 安全連線到 Google Sheets"""
    # 讀取剛剛貼在 Secrets 裡的 JSON 內容
    credentials_dict = dict(st.secrets["gcp_service_account"])
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_url(SPREADSHEET_URL)

try:
    doc = connect_gspread()
    sheet_orders = doc.worksheet("Orders")
    sheet_customers = doc.worksheet("Customers")
except Exception as e:
    st.error(f"⚠️ 系統連線 Google 試算表失敗，真實錯誤為： {e}")
    st.stop()

# ==========================================
# 2. 輔助函式 (解析與資料庫操作)
# ==========================================
def parse_boss_text(text):
    """解析老闆的文字：假設格式為 '品項 價格 人名 數量'"""
    parts = text.split()
    if len(parts) >= 4:
        return {"item": parts[0], "price": parts[1], "name": parts[2], "qty": parts[3]}
    return {"item": "", "price": "", "name": "", "qty": "1"}

def get_all_customers():
    records = sheet_customers.get_all_records()
    return pd.DataFrame(records) if records else pd.DataFrame(columns=["姓名", "電話", "地址"])

def get_customer_info(name, df_cust):
    match = df_cust[df_cust['姓名'] == name]
    if not match.empty:
        return match.iloc[0]['電話'], match.iloc[0]['地址']
    return None, None

# ==========================================
# 3. 系統介面 (前端展示)
# ==========================================
st.title("📦 輕量化電商出貨後台系統 (雲端升級版)")

tab1, tab2, tab3 = st.tabs(["⚡ 快速建單 (智慧解析)", "📋 訂單看板與出貨 (自動併單)", "👥 熟客資料庫"])

df_customers = get_all_customers()

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
    
    if name:
        phone, address = get_customer_info(name, df_customers)
        if phone and address:
            st.success(f"✅ 偵測到熟客！電話：{phone}, 地址：{address}")
            status = "可出貨"
        else:
            st.warning("⚠️ 新客或缺少收件資訊，請手動補齊，或稍後再確認。")
            new_phone = st.text_input("補齊電話 (選填)")
            new_address = st.text_input("補齊地址 (選填)")
            status = "待確認" if not new_phone or not new_address else "可出貨"
            
            # 給客人的確認訊息 (這裡先不算運費，因為還沒併單)
            msg = f"您好，您訂購的 [{item}] (單價${price}) 共 [{qty}] 個。麻煩您提供收件人的『電話』與『地址』以便為您安排出貨，謝謝！"
            st.text_area("複製給客人的確認訊息：", msg, height=100)

    if st.button("💾 儲存訂單", type="primary"):
        if name and item:
            date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
            # 寫入 Orders 工作表 (如果第一列是標題，會自動往加)
            if len(sheet_orders.get_all_values()) == 0:
                sheet_orders.append_row(["日期", "姓名", "品項", "數量", "單價", "狀態"])
            sheet_orders.append_row([date_now, name, item, qty, price, status])
            
            # 如果是新客且有填資料，寫入 Customers
            if 'new_phone' in locals() and new_phone and new_address:
                if len(sheet_customers.get_all_values()) == 0:
                    sheet_customers.append_row(["姓名", "電話", "地址"])
                sheet_customers.append_row([name, str(new_phone), str(new_address)])
            
            st.success("訂單已成功寫入 Google 試算表！")
            st.rerun()

# ----------------- 分頁 2: 訂單看板與出貨 (自動併單核心) -----------------
with tab2:
    st.subheader("2. 訂單狀態與自動併單匯出")
    
    records_orders = sheet_orders.get_all_records()
    if records_orders:
        df_orders = pd.DataFrame(records_orders)
        
        # 顯示原始訂單資料
        st.markdown("##### 📝 原始訂單明細 (尚未併單)")
        st.dataframe(df_orders, use_container_width=True)
        
        st.divider()
        st.markdown("##### 📦 準備出貨與匯出 Excel (滿3000免運，未滿60)")
        
        # 只抓取「可出貨」的訂單來併單
        df_ready = df_orders[df_orders['狀態'] == '可出貨'].copy()
        
        if not df_ready.empty:
            # 1. 結合熟客資料庫獲取電話地址
            df_merged = pd.merge(df_ready, df_customers, on='姓名', how='left')
            
            # 2. 組合出貨明細字串與計算單項小計
            df_merged['出貨明細'] = df_merged['品項'].astype(str) + "(單價$" + df_merged['單價'].astype(str) + " x" + df_merged['數量'].astype(str) + ")"
            df_merged['商品小計'] = df_merged['單價'].astype(int) * df_merged['數量'].astype(int)
            
            # 3. 執行群組併單 (GroupBy)
            df_consolidated = df_merged.groupby(['姓名', '電話', '地址']).agg({
                '出貨明細': lambda x: '、\n'.join(x),
                '商品小計': 'sum'
            }).reset_index()
            
            # 4. 運費邏輯判斷
            df_consolidated['運費'] = df_consolidated['商品小計'].apply(lambda x: 0 if x >= 3000 else 60)
            df_consolidated['運費標示'] = df_consolidated['運費'].apply(lambda x: '免運' if x == 0 else '含運費')
            df_consolidated['最終總金額'] = df_consolidated['商品小計'] + df_consolidated['運費']
            
            # 顯示併單後的結果
            st.dataframe(df_consolidated, use_container_width=True)
            
            # 5. 匯出 Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_consolidated.to_excel(writer, index=False, sheet_name='出貨單')
            excel_data = output.getvalue()
            
            st.download_button(
                label="📥 下載最終出貨 Excel 表單",
                data=excel_data,
                file_name=f"合併出貨單_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
        else:
            st.info("目前沒有『可出貨』狀態的訂單可供併單。")
    else:
        st.info("試算表中尚無訂單資料。")

# ----------------- 分頁 3: CRM 資料庫 -----------------
with tab3:
    st.subheader("3. 熟客名單 (連動 Google 試算表)")
    st.dataframe(df_customers, use_container_width=True)
with tab3:
    st.subheader("3. 雲端客戶通訊錄")
    st.dataframe(df_customers, use_container_width=True)
