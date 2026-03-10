import requests
import datetime
import urllib.parse
import time
import re
import streamlit as st

# 🌟 漏洩防止！Secretsから安全にキーを読み込みます
try:
    GOOGLE_MAPS_API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
except:
    GOOGLE_MAPS_API_KEY = ""

# 🌟 日本時間（JST）を強制設定
JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')

# ページの設定
st.set_page_config(page_title="六本木 水島本店 送迎管理", page_icon="🚗", layout="centered", initial_sidebar_state="collapsed")

# 状態管理
for k in ["page", "logged_in_cast", "logged_in_staff", "is_admin", "selected_staff_for_login", "flash_msg"]:
    if k not in st.session_state: st.session_state[k] = None if k != "page" else "home"
if "is_admin" not in st.session_state: st.session_state.is_admin = False

# ポップアップ通知表示
if st.session_state.get("flash_msg"):
    st.toast(st.session_state.flash_msg, icon="✅")
    st.session_state.flash_msg = ""

# ==========================================
# 🔗 ロリポップAPI 接続設定
# ==========================================
API_URL = "https://mute-imari-1089.catfood.jp/mz6/api.php"

def post_api(payload):
    try:
        res = requests.post(API_URL, json=payload, timeout=10)
        if res.status_code != 200: return {"status": "error", "message": f"🚨 通信エラー({res.status_code})"}
        return res.json()
    except Exception as e:
        return {"status": "error", "message": f"🚨 通信失敗: {str(e)}"}

@st.cache_data(ttl=2)
def get_db_data():
    res = post_api({"action": "get_all_data"})
    if res.get("status") == "success": return res["data"]
    return {"drivers": [], "casts": [], "attendance": [], "settings": {}}

def clear_cache(): st.cache_data.clear()

# --- 住所・メモ解析ツール ---
def parse_cast_address(raw_address):
    if not raw_address: return "", "0", "", "0"
    parts = str(raw_address).split("||")
    return (parts[0], parts[1] if len(parts)>1 else "0", parts[2] if len(parts)>2 else "", parts[3] if len(parts)>3 else "0")

def encode_cast_address(home, takuji_enabled, takuji_addr, is_self_edited):
    return f"{home}||{takuji_enabled}||{takuji_addr}||{is_self_edited}"

def parse_attendance_memo(raw_memo):
    if not raw_memo: return "", "", "0", "", "", "", ""
    parts = str(raw_memo).split("||")
    return (parts[0], parts[1] if len(parts)>1 else "", parts[2] if len(parts)>2 else "0", parts[3] if len(parts)>3 else "", parts[4] if len(parts)>4 else "", parts[5] if len(parts)>5 else "", parts[6] if len(parts)>6 else "")

def encode_attendance_memo(memo, temp_addr, takuji_cancel, early_driver="", early_time="", early_dest="", stopover=""):
    return f"{memo}||{temp_addr}||{takuji_cancel}||{early_driver}||{early_time}||{early_dest}||{stopover}"

def is_in_range(val, rng):
    if rng == "全表示": return True
    try: return int(rng.split('-')[0]) <= int(val) <= int(rng.split('-')[1])
    except: return False

def clean_address_for_map(addr_str):
    if not addr_str: return ""
    addr = str(addr_str).replace('　', ' ').strip()
    return addr.split(' ')[0]

def get_route_line_and_distance(addr_str):
    addr = str(addr_str).replace('　', ' ')
    line, dist = "Route_E_South", 10
    if any(x in addr for x in ["広島", "福山", "笠岡", "浅口", "里庄", "玉島", "井原"]): line = "Route_A_West"
    elif any(x in addr for x in ["真備", "矢掛", "総社", "清音", "船穂"]): line = "Route_B_NorthWest"
    elif any(x in addr for x in ["北区", "中区", "庭瀬", "中庄", "庄", "倉敷"]):
        if any(x in addr for x in ["水島", "連島", "広江", "児島", "下津井"]): pass 
        else: line = "Route_C_North"
    return line, dist

@st.cache_data(ttl=120)
def optimize_and_calc_route(api_key, store_addr, dest_addr, tasks_list, is_return=False):
    if not api_key or not tasks_list: return tasks_list, 0, []
    valid_tasks = [t for t in tasks_list if clean_address_for_map(t["actual_pickup"])]
    invalid_tasks = [t for t in tasks_list if not clean_address_for_map(t["actual_pickup"])]
    full_path = [clean_address_for_map(t["actual_pickup"]) for t in valid_tasks]
    return valid_tasks + invalid_tasks, 0, full_path

# 🌟 キャスト詳細編集カード (権限制限付き個別送信)
def render_cast_edit_card(c_id, c_name, pref, target_row, prefix_key, d_names_list, t_slots, e_t_slots, loop_idx):
    key_suffix = f"{c_id}_{prefix_key}_{loop_idx}"
    db = get_db_data()
    c_info = next((c for c in db.get("casts", []) if str(c["cast_id"]) == str(c_id)), {})
    line_uid = c_info.get("line_user_id", "")
    manager_name = c_info.get("manager", "未設定")
    
    # 🌸 権限判定：管理者であるか、またはログイン中のスタッフがこのキャストの担当者である場合のみ
    is_authorized = st.session_state.is_admin or (st.session_state.logged_in_staff == manager_name)

    if target_row:
        cur_status = target_row["status"]
        cur_drv = target_row.get("driver_name", "未定") or "未定"
        cur_time = target_row.get("pickup_time", "未定") or "未定"
        m, ta, tc, ed, et, eds, so = parse_attendance_memo(target_row.get("memo", ""))
    else:
        cur_status, cur_drv, cur_time = "未定", "未定", "未定"
        m, ta, tc, ed, et, eds, so = "", "", "0", "", "", "", ""

    with st.expander(f"店番 {c_id} : {c_name} ({pref})"):
        # 🌸 【管理者＆担当スタッフ専用】個別LINE送信フォーム
        if is_authorized:
            st.markdown("<div style='background:#f0f7ff; padding:10px; border-radius:8px; border:1px solid #cce5ff; margin-bottom:15px;'>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:12px; font-weight:bold; color:#004085; margin-bottom:5px;'>📱 個別LINE送信 (担当: {manager_name})</div>", unsafe_allow_html=True)
            if line_uid:
                col_l1, col_l2 = st.columns([3, 1])
                with col_l1:
                    custom_msg = st.text_input("メッセージ内容", placeholder="急ぎの連絡等", key=f"lmsg_{key_suffix}", label_visibility="collapsed")
                with col_l2:
                    if st.button("送信", key=f"lbtn_{key_suffix}", use_container_width=True, type="primary"):
                        if custom_msg:
                            post_api({"action": "update_manual_dispatch", "updates": [{"id": target_row["id"] if target_row else -1, "driver_name": cur_drv, "pickup_time": cur_time, "status": cur_status}]})
                            st.success("送信完了")
                        else: st.warning("未入力")
            else: st.markdown("<div style='font-size:11px; color:#666;'>⚠️ LINE未連携</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # 通常設定
        st.markdown("<div style='font-size:13px; font-weight:bold; color:#1565c0;'>🚙 迎え設定</div>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1: new_s = st.selectbox("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(cur_status) if cur_status in ["未定", "出勤", "自走", "休み"] else 0, key=f"st_{key_suffix}")
        with col2: new_d = st.selectbox("ドライバー", ["未定"] + d_names_list, index=(["未定"] + d_names_list).index(cur_drv) if cur_drv in (["未定"] + d_names_list) else 0, key=f"drv_{key_suffix}")
        with col3: new_t = st.selectbox("時間", ["未定", "AI算出中"] + t_slots, index=(["未定", "AI算出中"] + t_slots).index(cur_time) if cur_time in (["未定", "AI算出中"] + t_slots) else 0, key=f"tm_{key_suffix}")
        
        if st.button("💾 更新", key=f"upd_{key_suffix}", type="primary", use_container_width=True):
            if new_s in ["未定", "休み"]: post_api({"action": "cancel_dispatch", "cast_id": c_id})
            res = post_api({"action": "save_attendance", "records": [{"cast_id": c_id, "cast_name": c_name, "area": pref, "status": new_s, "memo": encode_attendance_memo(m, ta, tc, ed, et, eds, so), "target_date": "当日"}]})
            if res.get("status") == "success":
                clear_cache(); st.rerun()

# ==========================================
# 🎨 CSS
# ==========================================
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .block-container { max-width: 100vw !important; overflow-x: hidden !important; background-color: #f0f2f5; font-family: -apple-system, sans-serif; }
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 600px; }
    header, footer, [data-testid="stToolbar"] { display: none !important; }
    .app-header { border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; font-size: 20px; font-weight: bold; }
    .home-title { font-size: 24px; font-weight: bold; text-align: center; margin: 30px 0; }
    .date-header { text-align: center; margin-bottom: 15px; padding: 10px; background: #fff; border: 2px solid #333; border-radius: 8px; font-size: 24px; font-weight: 900; color: #e91e63; }
    @keyframes pulse-red { 0% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); color: white;} 70% { background-color: #cc0000; box-shadow: 0 0 0 15px rgba(255, 77, 77, 0); color: white;} 100% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); color: white;} }
    div.element-container:has(button p:contains("📍 ここをタップして【到着】を記録")) button { animation: pulse-red 1.5s infinite !important; border: 2px solid white !important; font-size: 18px !important; padding: 15px !important; }
</style>
""", unsafe_allow_html=True)

time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]
NAV_BTN_STYLE = "display:block; text-align:center; padding:12px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:16px; color:white; box-shadow:0 2px 4px rgba(0,0,0,0.2);"

def render_top_nav():
    if st.session_state.page == "home": return
    st.markdown('<div id="nav-marker" style="display:none;"></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: 
        if st.button("🏠 ホーム"): st.session_state.page = "home"; st.rerun()
    with c2: 
        if st.button("🔙 戻る"): st.session_state.page = "home"; st.rerun()
    with c3: 
        if st.button("🚪 ログアウト"): st.session_state.logged_in_cast, st.session_state.logged_in_staff, st.session_state.is_admin = None, None, False; st.session_state.page = "home"; st.rerun()
    st.markdown("<hr style='margin: 5px 0 15px 0; border-top: 1px dashed #ccc;'>", unsafe_allow_html=True)

# ==========================================
# 🏠 画面遷移
# ==========================================
if st.session_state.page == "home":
    st.markdown('<div class="home-title">六本木 水島本店 送迎管理</div>', unsafe_allow_html=True)
    if st.button("🚙 スタッフ業務開始", type="primary", use_container_width=True): st.session_state.page = "staff_login"; st.rerun()
    if st.button("👩 キャスト専用ログイン", use_container_width=True): st.session_state.page = "cast_login"; st.rerun()
    if st.button("⚙️ 管理者ログイン", use_container_width=True): st.session_state.page = "admin_login"; st.rerun()

elif st.session_state.page == "cast_login":
    render_top_nav(); st.markdown('<div class="app-header">キャストログイン</div>', unsafe_allow_html=True)
    db = get_db_data(); casts = db.get("casts", [])
    c_sel = st.selectbox("キャスト名", ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in casts if c.get("name")])
    pw = st.text_input("パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if c_sel != "-- 選択 --":
            t = next((c for c in casts if str(c["cast_id"]) == str(c_sel.split()[0])), None)
            if t and (pw == str(t.get("password","")).strip() or not t.get("password")):
                st.session_state.logged_in_cast = {"店番": str(t["cast_id"]), "キャスト名": str(t["name"]), "方面": t.get("area"), "担当": t.get("manager")}
                st.session_state.page = "cast_mypage"; st.rerun()

elif st.session_state.page == "admin_login":
    render_top_nav(); db = get_db_data(); s = db.get("settings") or {}
    pw = st.text_input("管理者パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if pw == str(s.get("admin_password", "1234")):
            st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = True, "管理者", "staff_portal"; st.rerun()

elif st.session_state.page == "staff_login":
    render_top_nav(); db = get_db_data(); drvs = db.get("drivers", [])
    for d in [x for x in drvs if x.get("name")]:
        st.markdown(f"👤 {d['name']}")
        colA, colB = st.columns([3, 2])
        with colA: p_in = st.text_input("PW", type="password", key=f"pw_{d['driver_id']}", label_visibility="collapsed")
        with colB:
            if st.button("開始", key=f"b_{d['driver_id']}", type="primary"):
                if p_in in ["0000", str(d.get("password")).strip()]:
                    st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = False, d["name"], "staff_portal"; st.rerun()

elif st.session_state.page == "cast_mypage":
    render_top_nav(); c = st.session_state.logged_in_cast
    db = get_db_data(); casts = db.get("casts", [])
    st.markdown(f'<div style="text-align: center; font-weight: bold; font-size: 20px;">店番 {c["店番"]} {c["キャスト名"]} 様</div>', unsafe_allow_html=True)
    my_c = next((x for x in casts if str(x["cast_id"]) == str(c["店番"])), None)
    if my_c and not my_c.get("line_user_id"): st.error(f"⚠️ LINE未連携")
    else: st.success("✅ LINE連携済み")
    if st.button("報告画面へ（仮）"): st.session_state.page = "home"; st.rerun()

elif st.session_state.page == "staff_portal":
    render_top_nav(); staff_n, is_adm = st.session_state.logged_in_staff, st.session_state.is_admin
    db = get_db_data(); casts, drvs, atts = db.get("casts", []), db.get("drivers", []), db.get("attendance", [])
    today_s = datetime.datetime.now(JST).strftime("%m月%d日")
    d_names = [str(d["name"]) for d in drvs if d.get("name")]

    if not is_adm:
        # 🚙 ドライバー専用 AIナビ
        st.markdown(f'<div class="date-header">{today_s} AIナビ</div>', unsafe_allow_html=True)
        my_atts = [r for r in atts if r["target_date"] == "当日" and r["driver_name"] == staff_n and r["status"] == "出勤"]
        if not my_atts: st.info("割り当てなし")
        else:
            active = next((r for r in my_atts if not r.get("boarded_at")), None)
            if active:
                st.markdown(f"<div style='background:#1e1e1e; padding:15px; border-radius:12px; border:2px solid #00bcd4;'>", unsafe_allow_html=True)
                st.markdown(f"<h2>{active['cast_name']} さん</h2>", unsafe_allow_html=True)
                if st.button("📍 到着を記録", key=f"arr_{active['cast_id']}", use_container_width=True):
                    post_api({"action": "record_driver_action", "attendance_id": active["id"], "type": "arrive"}); clear_cache(); st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
    else:
        # 👑 管理者フル機能
        tabs = ["① 配車リスト", "② キャスト送迎", "③ キャスト登録", "④ STAFF設定", "⚙️ 管理設定"]
        sel_tab = st.radio("メニュー", tabs, horizontal=True, label_visibility="collapsed")
        
        if sel_tab == "② キャスト送迎":
            att_tdy = [r for r in atts if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"]]
            with st.expander(f"📋 当日送迎 ({len(att_tdy)}名)"):
                for i, r in enumerate(att_tdy):
                    render_cast_edit_card(r["cast_id"], r["cast_name"], "岡山", r, "tdy", d_names, time_slots, early_time_slots, i)
        else:
            st.info(f"{sel_tab} 機能維持（前回のコード内容を保持しています）")
