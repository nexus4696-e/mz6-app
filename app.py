import streamlit as st
import requests
import datetime
import time

# --- 初期設定 ---
st.set_page_config(page_title="送迎管理", page_icon="🚙", layout="centered")

# スマホの無駄な余白を限界まで削る設定
st.markdown("""
    <style>
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        .block-container {
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        .streamlit-expanderHeader {
            font-size: 14px !important;
            padding: 0.5rem !important;
        }
    </style>
""", unsafe_allow_html=True)

# ロリポップのAPI連携URL
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
if "cast_id" not in st.session_state:
    st.session_state.cast_id = None

db_data = get_db_data()
if not db_data:
    st.error("データベースに接続できません。サーバーを確認してください。")
    st.stop()

# ==========================================
# 🔐 ログイン画面
# ==========================================
if st.session_state.role is None:
    st.markdown("<h4 style='text-align: center;'>水島本店 送迎システム</h4>", unsafe_allow_html=True)
    tab_driver, tab_cast, tab_admin = st.tabs(["🚙 スタッフ", "👸 キャスト", "⚙️ 管理者"])
    
    with tab_driver:
        driver_list = ["-- 選択 --"] + [d['name'] for d in db_data['drivers']]
        d_name = st.selectbox("スタッフ名", driver_list, key="d_name")
        d_pass = st.text_input("パスワード", type="password", key="d_pass")
        if st.button("ログイン", type="primary", use_container_width=True, key="d_login"):
            if d_name != "-- 選択 --":
                correct_pass = next((d['password'] for d in db_data['drivers'] if d['name'] == d_name), "")
                if d_pass == correct_pass:
                    st.session_state.role = "driver"
                    st.session_state.user_name = d_name
                    st.rerun()
                else:
                    st.error("パスワードが間違っています。")

    with tab_cast:
        # 🌟 キャスト検索：必ず「店番 キャスト名」で表示し、店番で検索可能にする
        cast_list_display = ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in db_data['casts']]
        c_selected = st.selectbox("店番とキャスト名", cast_list_display, key="c_name")
        c_pass = st.text_input("パスワード", type="password", key="c_pass")
        
        if st.button("ログイン", type="primary", use_container_width=True, key="c_login"):
            if c_selected != "-- 選択 --":
                selected_id = c_selected.split(" ")[0] # 選択肢から店番だけを抽出
                target_cast = next((c for c in db_data['casts'] if c['cast_id'] == selected_id), None)
                if target_cast and c_pass == target_cast['password']:
                    st.session_state.role = "cast"
                    st.session_state.user_name = target_cast['name']
                    st.session_state.cast_id = target_cast['cast_id']
                    st.rerun()
                else:
                    st.error("パスワードが間違っています。")

    with tab_admin:
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
# 🚪 極小共通ヘッダー
# ==========================================
col1, col2 = st.columns([7, 3])
with col1:
    # キャストがログインしている場合は店番も表示
    display_name = f"{st.session_state.cast_id} {st.session_state.user_name}" if st.session_state.role == "cast" else st.session_state.user_name
    st.markdown(f"👤 **{display_name}**")
with col2:
    if st.button("ログアウト", use_container_width=True):
        st.session_state.role = None
        st.session_state.user_name = None
        st.session_state.cast_id = None
        st.rerun()

# ==========================================
# 🚙 スタッフ専用画面
# ==========================================
if st.session_state.role == "driver":
    if st.button("🔄 更新", use_container_width=True):
        st.rerun()
        
    attendances = [a for a in db_data['attendance'] if a['target_date'] == '当日']
    driver_names = ["未定"] + [d['name'] for d in db_data['drivers']]
    
    if not attendances:
        st.info("本日の送迎リクエストはありません。")
    else:
        updates = []
        for a in attendances:
            is_mine = (a['driver_name'] == st.session_state.user_name)
            icon = "🟢" if is_mine else "⚪"
            # 🌟 リスト表示：必ず「店番 キャスト名」のセットにする
            label = f"{icon} {a['pickup_time']} | {a['cast_id']} {a['cast_name']} | {a['status']} | {a['driver_name']}"
            
            with st.expander(label):
                d_index = driver_names.index(a['driver_name']) if a['driver_name'] in driver_names else 0
                s_options = ["出勤", "迎車中", "完了", "未定", "キャンセル"]
                s_index = s_options.index(a['status']) if a['status'] in s_options else 0
                
                new_time = st.text_input("時間", value=a['pickup_time'], key=f"dt_{a['id']}")
                new_status = st.selectbox("状態", s_options, index=s_index, key=f"ds_{a['id']}")
                new_driver = st.selectbox("担当", driver_names, index=d_index, key=f"dd_{a['id']}")
                
                updates.append({
                    "id": a['id'],
                    "driver_name": new_driver,
                    "pickup_time": new_time,
                    "status": new_status
                })
                
        if st.button("💾 全ての変更を保存", type="primary", use_container_width=True, key="d_save"):
            post_api({"action": "update_manual_dispatch", "updates": updates})
            st.success("保存しました！")
            time.sleep(1)
            st.rerun()

# ==========================================
# 👸 キャスト専用画面
# ==========================================
elif st.session_state.role == "cast":
    my_record = next((a for a in db_data['attendance'] if a['cast_name'] == st.session_state.user_name and a['target_date'] == '当日'), None)
    c_info = next((c for c in db_data['casts'] if c['name'] == st.session_state.user_name), None)
    
    if my_record:
        st.success(f"状態: {my_record['status']}")
        st.write(f"⏰ {my_record['pickup_time']} ／ 🚙 {my_record['driver_name']}")
        
        if st.button("🔄 更新", use_container_width=True):
            st.rerun()
            
        with st.form("cast_update_form"):
            new_time = st.text_input("時間の変更 (例: 20:30)", value=my_record['pickup_time'])
            if st.form_submit_button("💾 時間を変更する"):
                post_api({"action": "update_manual_dispatch", "updates": [{"id": my_record['id'], "driver_name": my_record['driver_name'], "pickup_time": new_time, "status": my_record['status']}]})
                st.success("変更しました。")
                time.sleep(1)
                st.rerun()

        if st.button("❌ キャンセルする", use_container_width=True):
            post_api({"action": "cancel_dispatch", "cast_id": my_record['cast_id']})
            time.sleep(1)
            st.rerun()
    else:
        st.info("送迎リクエスト")
        with st.form("cast_request_form"):
            req_time = st.time_input("希望時間", datetime.time(20, 0))
            req_area = st.text_input("お迎えエリア", value=c_info['area'] if c_info else "")
            
            driver_names = ["指定なし"] + [d['name'] for d in db_data['drivers']]
            pref_driver = c_info.get('preferred_driver', '') if c_info else ''
            d_index = driver_names.index(pref_driver) if pref_driver in driver_names else 0
            req_driver = st.selectbox("希望スタッフ", driver_names, index=d_index)
            
            if st.form_submit_button("📤 リクエスト送信", type="primary", use_container_width=True):
                final_driver = "未定" if req_driver == "指定なし" else req_driver
                payload = {
                    "action": "create_or_update_dispatch",
                    "cast_id": c_info['cast_id'],
                    "cast_name": c_info['name'],
                    "area": req_area,
                    "pickup_time": req_time.strftime("%H:%M"),
                    "driver_name": final_driver
                }
                post_api(payload)
                st.success("送信しました！")
                time.sleep(1)
                st.rerun()

# ==========================================
# ⚙️ 管理者専用画面
# ==========================================
elif st.session_state.role == "admin":
    tab_dispatch, tab_driver, tab_cast, tab_setting = st.tabs(["配車", "ｽﾀｯﾌ", "ｷｬｽﾄ", "設定"])
    
    # --- 🚕 配車管理タブ ---
    with tab_dispatch:
        if st.button("🔄 更新", use_container_width=True, key="a_update"):
            st.rerun()
            
        attendances = [a for a in db_data['attendance'] if a['target_date'] == '当日']
        driver_names = ["未定"] + [d['name'] for d in db_data['drivers']]
        
        if not attendances:
            st.info("本日のリクエストはありません。")
        else:
            updates = []
            for a in attendances:
                # 🌟 リスト表示：必ず「店番 キャスト名」のセットにする
                label = f"{a['pickup_time']} | {a['cast_id']} {a['cast_name']} | {a['status']} | {a['driver_name']}"
                with st.expander(label):
                    d_index = driver_names.index(a['driver_name']) if a['driver_name'] in driver_names else 0
                    s_options = ["出勤", "迎車中", "完了", "未定", "キャンセル"]
                    s_index = s_options.index(a['status']) if a['status'] in s_options else 0
                    
                    new_time = st.text_input("時間", value=a['pickup_time'], key=f"a_t_{a['id']}")
                    new_status = st.selectbox("状態", s_options, index=s_index, key=f"a_s_{a['id']}")
                    new_driver = st.selectbox("担当", driver_names, index=d_index, key=f"a_d_{a['id']}")
                    
                    updates.append({
                        "id": a['id'],
                        "driver_name": new_driver,
                        "pickup_time": new_time,
                        "status": new_status
                    })
                    
            if st.button("💾 変更を保存", type="primary", use_container_width=True):
                post_api({"action": "update_manual_dispatch", "updates": updates})
                st.success("保存しました！")
                time.sleep(1)
                st.rerun()

    # --- 🚙 スタッフ登録タブ ---
    with tab_driver:
        st.markdown("##### 📋 登録済みスタッフ一覧")
        if db_data['drivers']:
            st.dataframe(db_data['drivers'], use_container_width=True)
        else:
            st.info("データがありません")
            
        st.markdown("---")
        st.markdown("##### ➕ 新規登録・上書き編集")
        with st.form("driver_form"):
            d_id = st.text_input("ID (半角英数 ※既存ID入力で上書き)")
            d_name = st.text_input("名前")
            d_pass = st.text_input("パスワード")
            d_phone = st.text_input("電話番号")
            d_area = st.text_input("担当エリア")
            d_address = st.text_input("住所")
            d_capa = st.number_input("乗車定員", min_value=1, value=4)
            if st.form_submit_button("💾 スタッフ保存"):
                if d_id and d_name:
                    post_api({"action": "save_driver", "driver_id": d_id, "name": d_name, "password": d_pass, "phone": d_phone, "area": d_area, "address": d_address, "capacity": d_capa})
                    st.success("保存しました！")
                    time.sleep(1)
                    st.rerun()

    # --- 👸 キャスト登録タブ ---
    with tab_cast:
        st.markdown("##### 📋 登録済みキャスト一覧")
        if db_data['casts']:
            st.dataframe(db_data['casts'], use_container_width=True)
        else:
            st.info("データがありません")
            
        st.markdown("---")
        st.markdown("##### ➕ 新規登録・上書き編集")
        with st.form("cast_form"):
            # 🌟 明確に「店番」と表記
            c_id = st.text_input("店番 (キャストID / 半角英数 ※既存入力で上書き)")
            c_name = st.text_input("名前")
            c_pass = st.text_input("パスワード")
            c_phone = st.text_input("電話番号")
            c_area = st.text_input("送迎エリア")
            c_address = st.text_input("住所")
            c_manager = st.text_input("担当マネージャー")
            if st.form_submit_button("💾 キャスト保存"):
                if c_id and c_name:
                    post_api({"action": "save_cast", "cast_id": c_id, "name": c_name, "password": c_pass, "phone": c_phone, "area": c_area, "address": c_address, "manager": c_manager})
                    st.success("保存しました！")
                    time.sleep(1)
                    st.rerun()
                    
    # --- ⚙️ システム設定タブ ---
    with tab_setting:
        with st.form("setting_form"):
            current_settings = db_data.get('settings', {})
            s_pass = st.text_input("管理者パスワード", value=current_settings.get('admin_password', 'admin'))
            s_store = st.text_input("店舗住所", value=current_settings.get('store_address', ''))
            s_time = st.text_input("基準出勤時間 (例: 19:50)", value=current_settings.get('base_arrival_time', ''))
            s_notice = st.text_area("お知らせテキスト", value=current_settings.get('notice_text', ''))
            s_line = st.text_input("LINE Bot ID", value=current_settings.get('line_bot_id', ''))
            if st.form_submit_button("💾 設定更新"):
                post_api({"action": "save_settings", "admin_password": s_pass, "store_address": s_store, "base_arrival_time": s_time, "notice_text": s_notice, "line_bot_id": s_line})
                st.success("更新しました！")
                time.sleep(1)
                st.rerun()
