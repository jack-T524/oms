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

# ⚠️ 請把這裡換成你的 Google 試算表網址
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1fPnXxVa1YhxnD8_eVneCjZNdlAx60LdIoycRO2ubSKU/edit?gid=845570727#gid=845570727"

@st.cache_resource
def connect_gspread():
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
    st.error("⚠️ 無法連線至 Google 試算表。請檢查 Secrets 設定與網址。")
    st.stop()

# ==========================================
# 2. 輔助函式
# ==========================================
def parse_boss_text(text):
    parts = text.split()
    if len(parts) >= 4:
        return {"item": parts[0], "price": parts[1], "name": parts[2], "qty": parts[3]}
    return {"item": "", "price": "", "name": "", "qty": "1"}

def get_all_customers():
    records = sheet_customers.get_all_records()
    return pd.DataFrame(records) if records else pd.DataFrame(columns=["姓名", "電話", "地址"])

def get_customer_info(name, df_cust):
    if not df_cust.empty and '姓名' in df_cust.columns:
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

    if st.button("💾 儲存訂單", type="primary"):
        if name and item:
            date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
            if len(sheet_orders.get_all_values()) == 0:
                sheet_orders.append_row(["日期", "姓名", "品項", "數量", "單價", "狀態"])
            sheet_orders.append_row([date_now, name, item, qty, price, status])
            
            if 'new_phone' in locals() and new_phone and new_address:
                if len(sheet_customers.get_all_values()) == 0:
                    sheet_customers.append_row(["姓名", "電話", "地址"])
                sheet_customers.append_row([name, str(new_phone), str(new_address)])
            
            st.success("訂單已成功寫入 Google 試算表！")
            st.rerun()

# ----------------- 分頁 2: 訂單看板與出貨 (自動併單核心) -----------------
with tab2:
    st.subheader("2. 訂單狀態與出貨管理")
    
    records_orders = sheet_orders.get_all_records()
    if records_orders:
        df_orders = pd.DataFrame(records_orders)
        
        # === 新增功能：處理「待確認」訂單 (補件區) ===
        if '狀態' in df_orders.columns:
            pending_orders = df_orders[df_orders['狀態'] == '待確認']
            if not pending_orders.empty:
                st.warning("⚠️ 您有尚未補齊收件資訊的訂單，請補齊後轉入出貨流程：")
                # 抓出所有缺資料的客戶名單
                pending_names = pending_orders['姓名'].unique()
                
                col_sel, col_p, col_a, col_btn = st.columns([1.5, 1.5, 1.5, 1])
                with col_sel:
                    selected_name = st.selectbox("選擇要補齊的客戶", pending_names)
                with col_p:
                    new_phone = st.text_input("輸入電話")
                with col_a:
                    new_address = st.text_input("輸入地址")
                with col_btn:
                    st.write("") # 排版用空白
                    if st.button("💾 更新並解鎖出貨", use_container_width=True):
                        if new_phone and new_address:
                            # 1. 將新資料寫入 Customers 熟客名單
                            if len(sheet_customers.get_all_values()) == 0:
                                sheet_customers.append_row(["姓名", "電話", "地址"])
                            sheet_customers.append_row([selected_name, str(new_phone), str(new_address)])
                            
                            # 2. 將 Google 試算表中該客戶的狀態從「待確認」改為「可出貨」
                            all_values = sheet_orders.get_all_values()
                            for i, row in enumerate(all_values):
                                if i == 0: continue # 跳過標題列
                                # row[1] 是姓名, row[5] 是狀態 (索引從 0 開始)
                                if row[1] == selected_name and row[5] == '待確認':
                                    # Google Sheet 的列數是從 1 開始，所以是 i+1
                                    sheet_orders.update_cell(i+1, 6, '可出貨')
                            
                            st.success(f"✅ {selected_name} 的資料已補齊！系統已自動併單。")
                            st.rerun() # 重新整理畫面
                        else:
                            st.error("請完整輸入電話與地址！")
                st.divider()
        # ==========================================

        st.markdown("##### 📦 準備出貨與匯出 Excel (滿3000免運，未滿加60)")
        
        # 只抓取「可出貨」的訂單來併單
        if '狀態' in df_orders.columns:
            df_ready = df_orders[df_orders['狀態'] == '可出貨'].copy()
        else:
            df_ready = pd.DataFrame()
        
        if not df_ready.empty:
            # 結合熟客資料庫獲取電話地址
            df_customers_updated = get_all_customers() # 抓取最新客戶資料
            df_merged = pd.merge(df_ready, df_customers_updated, on='姓名', how='left')
            
            # 強制轉換數字格式，避免 Google 試算表讀取成字串導致計算錯誤
            df_merged['單價'] = pd.to_numeric(df_merged['單價'], errors='coerce').fillna(0).astype(int)
            df_merged['數量'] = pd.to_numeric(df_merged['數量'], errors='coerce').fillna(1).astype(int)
            
            # 組合出貨明細字串 (包含單價與數量)
            df_merged['出貨明細'] = df_merged['品項'].astype(str) + "(單價$" + df_merged['單價'].astype(str) + " x" + df_merged['數量'].astype(str) + ")"
            # 計算單項小計
            df_merged['商品小計'] = df_merged['單價'] * df_merged['數量']
            
            # 執行群組併單
            df_consolidated = df_merged.groupby(['姓名', '電話', '地址']).agg({
                '出貨明細': lambda x: '、\n'.join(x),
                '商品小計': 'sum'
            }).reset_index()
            
            # 運費邏輯判斷：滿 3000 免運，否則 60
            df_consolidated['運費'] = df_consolidated['商品小計'].apply(lambda x: 0 if x >= 3000 else 60)
            df_consolidated['運費標示'] = df_consolidated['運費'].apply(lambda x: '免運' if x == 0 else '含運費')
            df_consolidated['最終總金額'] = df_consolidated['商品小計'] + df_consolidated['運費']
            
            # 調整顯示的欄位順序
            final_columns = ['姓名', '電話', '地址', '出貨明細', '商品小計', '運費', '運費標示', '最終總金額']
            df_consolidated = df_consolidated[final_columns]
            
            # 顯示結果
            st.dataframe(df_consolidated, use_container_width=True)
            
            # 匯出 Excel
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
    col_title, col_btn = st.columns([8, 2])
    with col_title:
        st.subheader("3. 熟客名單 (連動 Google 試算表)")
    with col_btn:
        # 加入一個手動重整按鈕，確保隨時看到最新資料
        if st.button("🔄 重新整理清單", use_container_width=True):
            st.rerun()

    # 關鍵修正：在顯示表格前，強制「即時」再去抓一次最新資料
    df_customers_latest = get_all_customers()
    
    # 防呆檢查：確保資料表不是真的全空
    if not df_customers_latest.empty and len(df_customers_latest) > 0:
        st.dataframe(df_customers_latest, use_container_width=True)
        st.info(f"💡 目前資料庫中共有 {len(df_customers_latest)} 位熟客資料。")
    else:
        st.warning("目前試算表中尚未建立熟客資料，或系統正在同步中。")
