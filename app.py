import streamlit as st
import requests
import datetime
import time

# --- 初期設定 ---
st.set_page_config(page_title="六本木 水島本店 送迎管理", page_icon="🚙", layout="centered")

# ロリポップのAPI連携URL（絶対に消さないでください）
API_URL = "https://mute-imari-1089.catfood.jp/mz6/api.php"

def post_api(payload):
    try:
        res = requests.post(API_URL, json=payload, timeout=10)
        return res.json()
    except Exception as e:
        return {"status": "error", "message": f"通信エラー: {str(e)}"}

def get_db_data():
    res = post_api({"action": "get_all_data"})
    if res.get("status") == "success":
        return res["data"]
    return None

# --- セッション（ログイン状態）の管理 ---
if "role" not in st.session_state:
    st.session_state.role = None
if "user_name" not in st.session_state:
    st.session_state.user_name = None

db_data = get_db_data()
if not db_data:
    st.error("データベースに接続できません。サーバーを確認してください。")
    st.stop()

# ==========================================
# 🔐 ログイン画面（スマホ特化のタブデザイン）
# ==========================================
if st.session_state.role is None:
    st.markdown("<h2 style='text-align: center;'>六本木 水島本店 送迎管理</h2>", unsafe_allow_html=True)
    st.write("")
    
    tab_driver, tab_cast, tab_admin = st.tabs(["🚙 スタッフ", "👸 キャスト", "⚙️ 管理者"])
    
    # --- 🚙 スタッフログイン ---
    with tab_driver:
        st.markdown("#### スタッフ専用ログイン")
        driver_list = ["-- 選択してください --"] + [d['name'] for d in db_data['drivers']]
        d_name = st.selectbox("スタッフ名", driver_list, key="d_name")
        d_pass = st.text_input("パスワード", type="password", key="d_pass")
        
        if st.button("ログイン", type="primary", use_container_width=True, key="d_login"):
            if d_name == "-- 選択してください --":
                st.warning("名前を選択してください。")
            else:
                correct_pass = next((d['password'] for d in db_data['drivers'] if d['name'] == d_name), "")
                if d_pass == correct_pass and correct_pass != "":
                    st.session_state.role = "driver"
                    st.session_state.user_name = d_name
                    st.rerun()
                else:
                    st.error("パスワードが間違っています。")

    # --- 👸 キャストログイン ---
    with tab_cast:
        st.markdown("#### キャスト専用ログイン")
        cast_list = ["-- 選択してください --"] + [c['name'] for c in db_data['casts']]
        c_name = st.selectbox("キャスト名", cast_list, key="c_name")
        c_pass = st.text_input("パスワード", type="password", key="c_pass")
        
        if st.button("ログイン", type="primary", use_container_width=True, key="c_login"):
            if c_name == "-- 選択してください --":
                st.warning("名前を選択してください。")
            else:
                correct_pass = next((c['password'] for c in db_data['casts'] if c['name'] == c_name), "")
                if c_pass == correct_pass and correct_pass != "":
                    st.session_state.role = "cast"
                    st.session_state.user_name = c_name
                    st.rerun()
                else:
                    st.error("パスワードが間違っています。")

    # --- ⚙️ 管理者ログイン ---
    with tab_admin:
        st.markdown("#### 管理者ログイン")
        a_pass = st.text_input("管理者パスワード", type="password", key="a_pass")
        
        if st.button("ログイン", type="primary", use_container_width=True, key="a_login"):
            admin_correct_pass = db_data['settings'].get('admin_password', 'admin')
            if a_pass == admin_correct_pass:
                st.session_state.role = "admin"
                st.session_state.user_name = "管理者"
                st.rerun()
            else:
                st.error("パスワードが間違っています。")
    st.stop()

# ==========================================
# 🚪 共通ヘッダー
# ==========================================
col1, col2 = st.columns([7, 3])
with col1:
    st.markdown(f"👤 **{st.session_state.user_name}** さん")
with col2:
    if st.button("ログアウト", use_container_width=True):
        st.session_state.role = None
        st.session_state.user_name = None
        st.rerun()
st.markdown("---")


# ==========================================
# 🚙 スタッフ（ドライバー）専用画面
# ==========================================
if st.session_state.role == "driver":
    st.markdown("### 📋 本日のあなたの担当リスト")
    
    if st.button("🔄 リストを最新にする", use_container_width=True):
        st.rerun()
        
    my_tasks = [a for a in db_data['attendance'] if a['driver_name'] == st.session_state.user_name and a['target_date'] == '当日']
    
    if not my_tasks:
        st.info("現在、あなたに割り当てられた送迎はありません。")
    else:
        for task in my_tasks:
            st.success(f"👸 **{task['cast_name']}**")
            st.write(f"📍 **エリア:** {task['area']}　／　⏰ **時間:** {task['pickup_time']}")
            st.write(f"📋 **状態:** 【 {task['status']} 】")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🚙 迎車に向かう", key=f"go_{task['id']}", use_container_width=True):
                    post_api({"action": "update_manual_dispatch", "updates": [{"id": task['id'], "driver_name": task['driver_name'], "pickup_time": task['pickup_time'], "status": "迎車中"}]})
                    st.rerun()
            with col2:
                if st.button("✅ 送迎完了", key=f"done_{task['id']}", use_container_width=True):
                    post_api({"action": "update_manual_dispatch", "updates": [{"id": task['id'], "driver_name": task['driver_name'], "pickup_time": task['pickup_time'], "status": "完了"}]})
                    st.rerun()
            st.markdown("---")

# ==========================================
# 👸 キャスト専用画面
# ==========================================
elif st.session_state.role == "cast":
    st.markdown("### 🚕 送迎の申請")
    
    my_record = next((a for a in db_data['attendance'] if a['cast_name'] == st.session_state.user_name and a['target_date'] == '当日'), None)
    
    if my_record:
        st.success("✅ 本日の送迎は手配済み・または申請済みです。")
        st.write(f"**予定時間:** {my_record['pickup_time']}")
        st.write(f"**担当スタッフ:** {my_record['driver_name']}")
        st.write(f"**現在の状態:** 【 {my_record['status']} 】")
        
        if st.button("🔄 最新情報に更新", use_container_width=True):
            st.rerun()
            
        st.markdown("---")
        if st.button("❌ 送迎をキャンセルする", use_container_width=True):
            post_api({"action": "cancel_dispatch", "cast_id": my_record['cast_id']})
            st.success("キャンセルしました。")
            time.sleep(1)
            st.rerun()
    else:
        st.info("本日の送迎を申請します。希望時間を選択してください。")
        c_info = next((c for c in db_data['casts'] if c['name'] == st.session_state.user_name), None)
        
        req_time = st.time_input("希望時間", datetime.time(20, 0))
        
        if st.button("📤 送迎をリクエストする", type="primary", use_container_width=True):
            payload = {
                "action": "create_or_update_dispatch",
                "cast_id": c_info['cast_id'],
                "cast_name": c_info['name'],
                "area": c_info['area'],
                "pickup_time": req_time.strftime("%H:%M"),
                "driver_name": "未定"
            }
            post_api(payload)
            st.success("リクエストを送信しました！")
            time.sleep(1)
            st.rerun()

# ==========================================
# ⚙️ 管理者専用画面（全機能を復元・タブ化）
# ==========================================
elif st.session_state.role == "admin":
    st.markdown("### 👑 管理者ダッシュボード")
    
    # 🌟 ここで失われていた機能をすべてタブに分けて復活させました！
    tab_dispatch, tab_driver, tab_cast, tab_setting = st.tabs(["🚕 配車管理", "🚙 スタッフ登録", "👸 キャスト登録", "⚙️ 設定"])
    
    # --- 🚕 配車管理タブ ---
    with tab_dispatch:
        if st.button("🔄 最新情報に更新", use_container_width=True, key="update_dispatch"):
            st.rerun()
            
        attendances = [a for a in db_data['attendance'] if a['target_date'] == '当日']
        driver_names = ["未定"] + [d['name'] for d in db_data['drivers']]
        
        if not attendances:
            st.info("現在、本日の送迎リクエストはありません。")
        else:
            updates = []
            for a in attendances:
                with st.expander(f"👸 {a['cast_name']} （状態: {a['status']} / 時間: {a['pickup_time']}）"):
                    d_index = driver_names.index(a['driver_name']) if a['driver_name'] in driver_names else 0
                    s_options = ["出勤", "迎車中", "完了", "未定"]
                    s_index = s_options.index(a['status']) if a['status'] in s_options else 0
                    
                    new_driver = st.selectbox("担当スタッフ", driver_names, index=d_index, key=f"d_{a['id']}")
                    new_time = st.text_input("時間", value=a['pickup_time'], key=f"t_{a['id']}")
                    new_status = st.selectbox("状態", s_options, index=s_index, key=f"s_{a['id']}")
                    
                    updates.append({
                        "id": a['id'],
                        "driver_name": new_driver,
                        "pickup_time": new_time,
                        "status": new_status
                    })
                    
            if st.button("💾 配車の変更を保存する", type="primary", use_container_width=True):
                post_api({"action": "update_manual_dispatch", "updates": updates})
                st.success("保存しました！現場のスタッフ画面に反映されます。")
                time.sleep(1)
                st.rerun()

    # --- 🚙 スタッフ（ドライバー）登録タブ ---
    with tab_driver:
        st.markdown("#### 新規スタッフ登録・編集")
        st.write("※既存のIDを入力すると上書き編集になります")
        with st.form("driver_form"):
            d_id = st.text_input("スタッフID (半角英数)")
            d_name = st.text_input("スタッフ名")
            d_pass = st.text_input("ログインパスワード")
            d_phone = st.text_input("電話番号")
            d_area = st.text_input("担当エリア")
            d_address = st.text_input("住所")
            d_capa = st.number_input("乗車定員", min_value=1, value=4)
            submit_driver = st.form_submit_button("💾 スタッフ情報を保存")
            
            if submit_driver:
                if d_id and d_name and d_pass:
                    post_api({"action": "save_driver", "driver_id": d_id, "name": d_name, "password": d_pass, "phone": d_phone, "area": d_area, "address": d_address, "capacity": d_capa})
                    st.success("スタッフ情報を保存しました！")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("ID、名前、パスワードは必須です。")

    # --- 👸 キャスト登録タブ ---
    with tab_cast:
        st.markdown("#### 新規キャスト登録・編集")
        st.write("※既存のIDを入力すると上書き編集になります")
        with st.form("cast_form"):
            c_id = st.text_input("キャストID (半角英数)")
            c_name = st.text_input("キャスト名")
            c_pass = st.text_input("ログインパスワード")
            c_phone = st.text_input("電話番号")
            c_area = st.text_input("送迎エリア")
            c_address = st.text_input("住所")
            c_manager = st.text_input("担当マネージャー")
            submit_cast = st.form_submit_button("💾 キャスト情報を保存")
            
            if submit_cast:
                if c_id and c_name and c_pass:
                    post_api({"action": "save_cast", "cast_id": c_id, "name": c_name, "password": c_pass, "phone": c_phone, "area": c_area, "address": c_address, "manager": c_manager})
                    st.success("キャスト情報を保存しました！")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("ID、名前、パスワードは必須です。")
                    
    # --- ⚙️ システム設定タブ ---
    with tab_setting:
        st.markdown("#### システム全体設定")
        with st.form("setting_form"):
            current_settings = db_data.get('settings', {})
            s_pass = st.text_input("管理者ログインパスワード", value=current_settings.get('admin_password', 'admin'))
            s_store = st.text_input("店舗住所", value=current_settings.get('store_address', ''))
            s_time = st.text_input("基準出勤時間 (例: 19:50)", value=current_settings.get('base_arrival_time', ''))
            s_notice = st.text_area("お知らせテキスト", value=current_settings.get('notice_text', ''))
            s_line = st.text_input("LINE Bot ID (開発中)", value=current_settings.get('line_bot_id', ''))
            submit_setting = st.form_submit_button("💾 設定を更新する")
            
            if submit_setting:
                post_api({"action": "save_settings", "admin_password": s_pass, "store_address": s_store, "base_arrival_time": s_time, "notice_text": s_notice, "line_bot_id": s_line})
                st.success("システム設定を更新しました！")
                time.sleep(1)
                st.rerun()
