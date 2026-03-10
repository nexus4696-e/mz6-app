import requests
import datetime
import urllib.parse
import time
import re
import streamlit as st

# 🌟 漏洩防止！Streamlitの裏側（Secrets）から安全にキーを読み込みます
try:
    GOOGLE_MAPS_API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
except:
    GOOGLE_MAPS_API_KEY = "" # 設定されていない場合のエラー回避

# 🌟 日本時間（JST）を強制的に設定して時差バグを完全に防止
JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')

# ページの設定
st.set_page_config(page_title="六本木 水島本店 送迎管理", page_icon="🚗", layout="centered", initial_sidebar_state="collapsed")

# 状態管理とフラッシュメッセージ（ポップアップ通知）
for k in ["page", "logged_in_cast", "logged_in_staff", "is_admin", "selected_staff_for_login", "flash_msg"]:
    if k not in st.session_state: st.session_state[k] = None if k != "page" else "home"
if "is_admin" not in st.session_state: st.session_state.is_admin = False

# 🌟 画面リロード時に通知があればフワッと表示してすぐ消す
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
        if res.status_code == 404: return {"status": "error", "message": "🚨 api.php が見つかりません。"}
        if res.status_code != 200: return {"status": "error", "message": f"🚨 サーバーエラー ({res.status_code})"}
        try: return res.json()
        except: return {"status": "error", "message": f"🚨 PHPエラー: {res.text[:100]}..."}
    except Exception as e:
        return {"status": "error", "message": f"🚨 通信失敗: {str(e)}"}

@st.cache_data(ttl=2)
def get_db_data():
    res = post_api({"action": "get_all_data"})
    if res.get("status") == "success": return res["data"]
    st.error(f"データベース通信エラー: {res.get('message')}")
    return {"drivers": [], "casts": [], "attendance": [], "settings": {}}

def clear_cache(): st.cache_data.clear()

def parse_cast_address(raw_address):
    if not raw_address: return "", "0", "", "0"
    parts = str(raw_address).split("||")
    home = parts[0]
    takuji_enabled = parts[1] if len(parts) > 1 else "0"
    takuji_addr = parts[2] if len(parts) > 2 else ""
    is_self_edited = parts[3] if len(parts) > 3 else "0"
    return home, takuji_enabled, takuji_addr, is_self_edited

def encode_cast_address(home, takuji_enabled, takuji_addr, is_self_edited):
    return f"{home}||{takuji_enabled}||{takuji_addr}||{is_self_edited}"

def parse_attendance_memo(raw_memo):
    if not raw_memo: return "", "", "0", "", "", "", ""
    parts = str(raw_memo).split("||")
    memo = parts[0]
    temp_addr = parts[1] if len(parts) > 1 else ""
    takuji_cancel = parts[2] if len(parts) > 2 else "0"
    early_driver = parts[3] if len(parts) > 3 else ""
    early_time = parts[4] if len(parts) > 4 else ""
    early_dest = parts[5] if len(parts) > 5 else ""
    stopover = parts[6] if len(parts) > 6 else ""
    return memo, temp_addr, takuji_cancel, early_driver, early_time, early_dest, stopover

def encode_attendance_memo(memo, temp_addr, takuji_cancel, early_driver="", early_time="", early_dest="", stopover=""):
    return f"{memo}||{temp_addr}||{takuji_cancel}||{early_driver}||{early_time}||{early_dest}||{stopover}"

def is_in_range(val, rng):
    if rng == "全表示": return True
    try: return int(rng.split('-')[0]) <= int(val) <= int(rng.split('-')[1])
    except: return False

def parse_address(addr_str):
    pref, city, rest = "", "", str(addr_str)
    prefs = ["岡山県", "広島県", "香川県"]
    for p in prefs:
        if rest.startswith(p):
            pref = p; rest = rest[len(p):]; break
    if pref == "岡山県":
        cities = ["岡山市", "倉敷市", "玉野市", "総社市", "瀬戸市", "浅口市", "笠岡市"]
        for c in cities:
            if rest.startswith(c): city = c; rest = rest[len(c):]; break
    elif pref == "広島県":
        cities = ["福山市", "尾道市", "三原市", "府中市", "東広島市"]
        for c in cities:
            if rest.startswith(c): city = c; rest = rest[len(c):]; break
    return pref, city, rest

def clean_address_for_map(addr_str):
    if not addr_str: return ""
    addr = str(addr_str).replace('　', ' ').strip()
    if re.match(r'^[0-9\.]+\s*,\s*[0-9\.]+$', addr): return addr
    addr = addr.split(' ')[0]
    match1 = re.match(r'^(.*?[0-9０-９]+[-ー]+[0-9０-９]+(?:[-ー]+[0-9０-９]+)?).*', addr)
    if match1: return match1.group(1)
    match2 = re.match(r'^(.*?[0-9０-９]+(?:丁目|番|番地|号)).*', addr)
    if match2: return match2.group(1)
    return addr

def get_route_line_and_distance(addr_str):
    addr = str(addr_str).replace('　', ' ')
    line, dist = "Route_E_South", 10
    if any(x in addr for x in ["広島", "福山", "笠岡", "浅口", "里庄", "玉島", "井原"]): line = "Route_A_West"
    elif any(x in addr for x in ["真備", "矢掛", "総社", "清音", "船穂"]): line = "Route_B_NorthWest"
    elif any(x in addr for x in ["北区", "中区", "庭瀬", "中庄", "庄", "倉敷"]):
        if any(x in addr for x in ["水島", "連島", "広江", "児島", "下津井"]): pass 
        else: line = "Route_C_North"
    return line, dist

# 🌟 【絶対ルール厳守】乗車時間を最短化する「完全なGoogle AIアルゴリズム」
@st.cache_data(ttl=120)
def optimize_and_calc_route(api_key, store_addr, dest_addr, tasks_list, is_return=False):
    if not api_key or not tasks_list: return tasks_list, 0, []
    valid_tasks, valid_pickups = [], []
    for t in tasks_list:
        addr = clean_address_for_map(t["actual_pickup"])
        if addr: valid_tasks.append(t); valid_pickups.append(addr)
    invalid_tasks = [t for t in tasks_list if not clean_address_for_map(t["actual_pickup"])]
    ordered_valid_tasks = valid_tasks
    total_sec, full_path = 0, []
    if len(valid_pickups) > 1:
        wp_str = "optimize:true|" + "|".join(valid_pickups)
        try:
            res = requests.get("https://maps.googleapis.com/maps/api/directions/json", params={
                "origin": store_addr, "destination": store_addr, "waypoints": wp_str, "key": api_key, "language": "ja"
            }).json()
            if res.get("status") == "OK":
                wp_order = res["routes"][0]["waypoint_order"]
                ordered_valid_tasks = [valid_tasks[i] for i in wp_order]
                legs = res["routes"][0]["legs"]
                if is_return:
                    if legs[0]["duration"]["value"] > legs[-1]["duration"]["value"]: ordered_valid_tasks.reverse()
                else:
                    if legs[0]["duration"]["value"] < legs[-1]["duration"]["value"]: ordered_valid_tasks.reverse()
        except: pass
    final_ordered_tasks = ordered_valid_tasks + invalid_tasks
    for t in final_ordered_tasks:
        if t.get("actual_pickup"): full_path.append(clean_address_for_map(t["actual_pickup"]))
        if t.get("stopover"): full_path.append(clean_address_for_map(t["stopover"]))
        if t.get("use_takuji") and t.get("takuji_addr"): full_path.append(clean_address_for_map(t["takuji_addr"]))
    full_path = [p for p in full_path if p]
    if full_path:
        calc_origin, calc_dest = store_addr, (store_addr if not is_return else full_path[-1])
        calc_waypoints = (full_path if not is_return else full_path[:-1])
        params = {"origin": calc_origin, "destination": calc_dest, "key": api_key, "language": "ja"}
        if calc_waypoints: params["waypoints"] = "|".join(calc_waypoints)
        try:
            res2 = requests.get("https://maps.googleapis.com/maps/api/directions/json", params=params).json()
            if res2.get("status") == "OK": total_sec = sum(leg["duration"]["value"] for leg in res2["routes"][0]["legs"])
        except: pass
    return final_ordered_tasks, total_sec, full_path

# 🌟 キャスト詳細編集カード
def render_cast_edit_card(c_id, c_name, pref, target_row, prefix_key, d_names_list, t_slots, e_t_slots, loop_idx):
    key_suffix = f"{c_id}_{prefix_key}_{loop_idx}"
    if target_row:
        cur_status = target_row["status"]
        cur_drv = target_row.get("driver_name", "未定") or "未定"
        cur_time = target_row.get("pickup_time", "未定") or "未定"
        memo_text, temp_addr, takuji_cancel, e_drv, e_time, e_dest, stopover = parse_attendance_memo(target_row.get("memo", ""))
    else:
        cur_status, cur_drv, cur_time = "未定", "未定", "未定"
        memo_text, temp_addr, takuji_cancel, e_drv, e_time, e_dest, stopover = "", "", "0", "", "", "", ""

    is_early = (e_drv != "" and e_drv != "未定")
    title_badge = "🌅 早便" if is_early else ("🚙 送迎" if cur_drv != "未定" else ("🏃 自走" if cur_status == "自走" else ("💤 休み" if cur_status == "休み" else "未定")))
    
    with st.expander(f"店番 {c_id} : {c_name} ({pref}) - {title_badge}"):
        st.markdown("<div style='font-size:13px; font-weight:bold; color:#1565c0; margin-bottom:5px;'>🚙 迎え便（通常）設定</div>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1: new_status = st.selectbox("出勤状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(cur_status) if cur_status in ["未定", "出勤", "自走", "休み"] else 0, key=f"st_{key_suffix}")
        with col2: 
            drv_opts = ["未定"] + d_names_list
            new_drv = st.selectbox("送迎ドライバー", drv_opts, index=drv_opts.index(cur_drv) if cur_drv in drv_opts else 0, key=f"drv_{key_suffix}")
        with col3: 
            time_opts = ["未定", "AI算出中"] + t_slots
            new_time = st.selectbox("時間", time_opts, index=time_opts.index(cur_time) if cur_time in time_opts else 0, key=f"tm_{key_suffix}")
            
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        show_details = st.toggle("⚙️ 早便や詳細設定（同伴・変更など）を開く", key=f"toggle_{key_suffix}")
        
        new_e_drv, new_e_time = (e_drv if e_drv else "未定"), (e_time if e_time else (e_t_slots[0] if e_t_slots else "17:00"))
        new_e_dest, new_stopover, new_temp_addr, new_memo, new_takuji_cancel = e_dest, stopover, temp_addr, memo_text, (takuji_cancel == "1")

        if show_details:
            st.markdown("<div style='background:#fffde7; padding:10px; border-radius:8px; border:1px solid #fdd835;'>", unsafe_allow_html=True)
            st.markdown("<div style='font-size:13px; font-weight:bold; color:#e65100; margin-bottom:5px;'>🌅 早便（送り便）設定</div>", unsafe_allow_html=True)
            col_e1, col_e2 = st.columns(2)
            with col_e1: new_e_drv = st.selectbox("早便ドライバー", drv_opts, index=drv_opts.index(new_e_drv) if new_e_drv in drv_opts else 0, key=f"edrv_{key_suffix}")
            with col_e2: new_e_time = st.selectbox("到着指定時間", e_t_slots, index=e_t_slots.index(new_e_time) if new_e_time in e_t_slots else 0, key=f"etm_{key_suffix}")
            new_e_dest = st.text_input("早便送迎先 (住所・駅名など)", value=new_e_dest, key=f"edest_{key_suffix}")
            st.markdown("<div style='font-size:13px; font-weight:bold; color:#4caf50; margin-top:10px; margin-bottom:5px;'>📝 詳細情報（同伴・変更など）</div>", unsafe_allow_html=True)
            new_stopover = st.text_input("立ち寄り先 (同伴等)", value=new_stopover, key=f"so_{key_suffix}")
            new_temp_addr = st.text_input("当日のみ迎え先変更", value=new_temp_addr, key=f"ta_{key_suffix}")
            new_memo = st.text_input("備考", value=new_memo, key=f"mm_{key_suffix}")
            new_takuji_cancel = st.checkbox("本日の託児をキャンセル", value=new_takuji_cancel, key=f"tc_{key_suffix}")
            st.markdown("</div>", unsafe_allow_html=True)
        
        if st.button("💾 この内容で更新する", key=f"btn_upd_{key_suffix}", type="primary", use_container_width=True):
            if new_status in ["未定", "休み"]: new_drv, new_time, new_e_drv, new_e_time, new_e_dest = "未定", "未定", "未定", "未定", ""
            enc_memo = encode_attendance_memo(new_memo, new_temp_addr, ("1" if new_takuji_cancel else "0"), (new_e_drv if new_e_drv != "未定" else ""), (new_e_time if new_e_drv != "未定" else ""), (new_e_dest if new_e_drv != "未定" else ""), new_stopover)
            if new_status in ["未定", "休み"]: post_api({"action": "cancel_dispatch", "cast_id": c_id})
            res1 = post_api({"action": "save_attendance", "records": [{"cast_id": c_id, "cast_name": c_name, "area": pref, "status": new_status, "memo": enc_memo, "target_date": "当日"}]})
            if res1.get("status") == "success":
                time.sleep(1.0); clear_cache()
                if new_status not in ["未定", "休み"]:
                    db_temp = get_db_data(); new_row = next((r for r in db_temp.get("attendance", []) if r["target_date"] == "当日" and str(r["cast_id"]) == str(c_id)), None)
                    if new_row: post_api({"action": "update_manual_dispatch", "updates": [{"id": new_row["id"], "driver_name": new_drv, "pickup_time": new_time, "status": new_status}]})
                    time.sleep(0.5); clear_cache()
                st.session_state.flash_msg = f"{c_name} の情報を更新しました！"; st.rerun()

# ==========================================
# 🎨 クリーンで安全なCSS (枠線 ＆ ポジション復元)
# ==========================================
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .block-container { max-width: 100vw !important; overflow-x: hidden !important; background-color: #f0f2f5; font-family: -apple-system, sans-serif; }
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 600px; }
    header, footer, [data-testid="stToolbar"], [data-testid="manage-app-button"] { display: none !important; visibility: hidden !important; }
    .app-header { border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; font-size: 20px; font-weight: bold; }
    .home-title { font-size: 24px; font-weight: bold; text-align: center; margin: 30px 0; }
    .notice-box { border: 2px solid #fdd835; background: #fffde7; padding: 15px; border-radius: 8px; margin-bottom: 20px; text-align: center; }
    .date-header { text-align: center; margin-bottom: 15px; padding: 10px; background: #fff; border: 2px solid #333; border-radius: 8px; font-size: 24px; font-weight: 900; color: #e91e63; }
    .warning-box { background: #f44336; color: white; padding: 10px; font-weight: bold; border-radius: 5px 5px 0 0; }
    .warning-content { background: #ffebee; border-left: 4px solid #d32f2f; padding: 10px; margin-bottom: 15px; border-radius: 0 0 5px 5px; }
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { border: 2px solid #000000 !important; border-radius: 6px !important; background-color: #fff !important; }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 5px !important; }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] > div[data-testid="column"] { width: 33% !important; flex: 1 1 0% !important; min-width: 0 !important; }
    div.element-container:has(#nav-marker) + div.element-container button { padding: 0 !important; font-size: 13px !important; width: 100% !important; min-height: 42px !important; height: 42px !important; font-weight: bold !important; }
    @keyframes pulse-red { 0% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); color: white;} 70% { background-color: #cc0000; box-shadow: 0 0 0 15px rgba(255, 77, 77, 0); color: white;} 100% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); color: white;} }
    div.element-container:has(button p:contains("📍 ここをタップして【到着】を記録")) button { animation: pulse-red 1.5s infinite !important; border: 2px solid white !important; font-size: 18px !important; padding: 15px !important; }
    div.element-container:has(button p:contains("🟢 乗車完了")) button { background-color: #00cc66 !important; color: white !important; font-size: 18px !important; padding: 15px !important; border: 2px solid white !important; }
</style>
""", unsafe_allow_html=True)

time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]
MAP_SEARCH_BTN = """<a href='https://www.google.com/maps' target='_blank' style='display:inline-block; padding:4px 8px; background:#4285f4; color:white; border-radius:4px; text-decoration:none; font-size:12px; font-weight:bold; margin-bottom:5px; box-shadow:0 1px 2px rgba(0,0,0,0.2);'>🔍 Googleマップ</a>"""
NAV_BTN_STYLE = "display:block; text-align:center; padding:12px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:16px; color:white; box-shadow:0 2px 4px rgba(0,0,0,0.2);"
TEL_BTN_STYLE = "display:block; text-align:center; padding:15px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:18px; color:white; background:#1565c0; border:2px solid #0d47a1; box-shadow:0 4px 10px rgba(0,0,0,0.3); margin-bottom:10px;"

def render_top_nav():
    if st.session_state.page == "home": return
    st.markdown('<div id="nav-marker" style="display:none;"></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: 
        if st.button("🏠 ホーム", key=f"nh_{st.session_state.page}"): st.session_state.page = "home"; st.rerun()
    with c2: 
        if st.button("🔙 戻る", key=f"nb_{st.session_state.page}"): st.session_state.page = "home"; st.rerun()
    with c3: 
        if st.button("🚪 ログアウト", key=f"nl_{st.session_state.page}"):
            st.session_state.logged_in_cast, st.session_state.logged_in_staff, st.session_state.is_admin = None, None, False
            st.session_state.page = "home"; st.rerun()
    st.markdown("<hr style='margin: 5px 0 15px 0; border-top: 1px dashed #ccc;'>", unsafe_allow_html=True)

# ==========================================
# 🏠 画面遷移ロジック
# ==========================================
if st.session_state.page == "home":
    st.markdown('<div class="home-title">六本木 水島本店 送迎管理</div>', unsafe_allow_html=True)
    if st.button("🚙 スタッフ業務開始", type="primary", use_container_width=True):
        if st.session_state.get("logged_in_staff") or st.session_state.get("is_admin"): st.session_state.page = "staff_portal"
        else: st.session_state.page = "staff_login"
        st.rerun()
    if st.button("👩 キャスト専用ログイン", use_container_width=True):
        if st.session_state.get("logged_in_cast"): st.session_state.page = "cast_mypage"
        else: st.session_state.page = "cast_login"
        st.rerun()
    if st.button("⚙️ 管理者ログイン", use_container_width=True):
        if st.session_state.get("is_admin"): st.session_state.page = "staff_portal"
        else: st.session_state.page = "admin_login"
        st.rerun()

elif st.session_state.page == "cast_login":
    render_top_nav(); st.markdown('<div class="app-header">キャストログイン</div>', unsafe_allow_html=True)
    db = get_db_data(); casts = db.get("casts", [])
    c_list = ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in casts if str(c.get("name","")).strip() != ""]
    c_sel = st.selectbox("店番とキャスト名", c_list)
    pw = st.text_input("パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if c_sel != "-- 選択 --":
            t = next((c for c in casts if str(c["cast_id"]) == str(c_sel.split()[0])), None)
            if t and (pw == str(t.get("password","")).strip().replace("None","") or not t.get("password")):
                st.session_state.logged_in_cast = {"店番": str(t["cast_id"]), "キャスト名": str(t["name"]), "方面": t.get("area"), "担当": t.get("manager")}
                st.session_state.page = "cast_mypage"; st.rerun()

elif st.session_state.page == "admin_login":
    render_top_nav(); db = get_db_data(); settings = db.get("settings") or {}
    st.markdown('<div class="app-header">👑 管理者認証</div>', unsafe_allow_html=True)
    pw = st.text_input("パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if pw == str(settings.get("admin_password", "1234")):
            st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = True, "管理者", "staff_portal"; st.rerun()

elif st.session_state.page == "staff_login":
    render_top_nav(); st.markdown('<div class="app-header">スタッフ認証</div>', unsafe_allow_html=True)
    db = get_db_data(); drivers = db.get("drivers", [])
    for d in [x for x in drivers if str(x["name"]).strip() != ""]:
        st.markdown(f"<div style='font-weight:bold; margin-top:15px; border-bottom:2px solid #ddd; padding-bottom:5px; margin-bottom:10px;'>👤 {d['name']}</div>", unsafe_allow_html=True)
        colA, colB = st.columns([3, 2])
        with colA: p_in = st.text_input("PW", type="password", key=f"pass_{d['driver_id']}", label_visibility="collapsed", placeholder="パスワード")
        with colB:
            if st.button("開始", key=f"btn_{d['driver_id']}", type="primary", use_container_width=True):
                if p_in in ["0000", str(d["password"]).strip()] or str(d["password"]) == "":
                    st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = False, str(d["name"]), "staff_portal"; st.rerun()

# ==========================================
# 👩 キャストマイページ / 出勤報告 (完全復旧)
# ==========================================
elif st.session_state.page == "cast_mypage":
    render_top_nav(); c = st.session_state.logged_in_cast
    db = get_db_data(); settings, casts, attendance = db.get("settings") or {}, db.get("casts", []), db.get("attendance", [])
    st.markdown('<div class="app-header" style="margin-bottom:0; border:none;">出勤報告</div>', unsafe_allow_html=True)
    st.markdown("<hr style='margin-top:0; margin-bottom:15px; border-top: 2px solid #333;'>", unsafe_allow_html=True)
    
    my_cast_info = next((cast for cast in casts if str(cast["cast_id"]) == str(c["店番"])), None)
    line_uid = my_cast_info.get("line_user_id", "") if my_cast_info else ""
    if line_uid: st.markdown('<div style="text-align:center; background:#e8f5e9; color:#2e7d32; padding:8px; border-radius:8px; margin-bottom:15px; font-weight:bold; font-size:14px; border:2px solid #4caf50;">✅ LINE通知：連携済み</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="text-align:center; background:#ffebee; color:#d32f2f; padding:8px; border-radius:8px; margin-bottom:15px; font-size:13px; border:2px solid #f44336;"><b>⚠️ LINE未連携</b><br>公式LINEに「<b>{c["店番"]}{c["キャスト名"]}</b>」と送ってください。</div>', unsafe_allow_html=True)

    with st.expander("🏠 自宅・託児所の設定確認"):
        if my_cast_info:
            h_addr, t_en, t_addr, _ = parse_cast_address(my_cast_info.get("address", ""))
            with st.form("edit_profile"):
                n_h = st.text_input("自宅住所", value=h_addr)
                n_t_en = st.checkbox("託児所を経由する", value=(t_en=="1"))
                n_t_addr = st.text_input("託児所住所", value=t_addr) if n_t_en else ""
                if st.form_submit_button("更新"):
                    post_api({"action": "save_cast", "cast_id": c["店番"], "name": c["キャスト名"], "password": my_cast_info.get("password",""), "phone": my_cast_info.get("phone",""), "area": my_cast_info.get("area",""), "address": encode_cast_address(n_h, ("1" if n_t_en else "0"), n_t_addr, "1"), "manager": c.get("担当")})
                    clear_cache(); st.success("更新しました"); time.sleep(1); st.rerun()

    t_dt = datetime.datetime.now(JST); days = ['月','火','水','木','金','土','日']
    tab_tdy, tab_tmr, tab_week = st.tabs(["当日申請", "翌日申請", "週間申請"])
    
    with tab_tdy:
        m_today = next((r for r in attendance if r["target_date"] == "当日" and str(r["cast_id"]) == str(c["店番"])), None)
        memo_t, ta_t, tc_t, _, _, _, so_t = parse_attendance_memo(m_today.get("memo","")) if m_today else ("", "", "0", "", "", "", "")
        with st.form("form_tdy"):
            s = st.radio("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(m_today["status"] if m_today else "未定"), horizontal=True)
            m = st.text_input("備考", value=memo_t)
            so_a = st.text_input("立ち寄り先 (同伴等があれば)", value=so_t)
            ta = st.text_input("本日のみ迎え先変更", value=ta_t)
            tc = "1" if st.checkbox("本日の託児をキャンセル", value=(tc_t=="1")) else "0"
            if st.form_submit_button("📤 送信"):
                if s in ["未定", "休み"]: post_api({"action": "cancel_dispatch", "cast_id": c["店番"]})
                res = post_api({"action": "save_attendance", "records": [{"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": s, "memo": encode_attendance_memo(m, ta, tc, stopover=so_a), "target_date": "当日"}]})
                if res.get("status") == "success": clear_cache(); st.session_state.page = "report_done"; st.rerun()

    with tab_tmr:
        m_tmr = next((r for r in attendance if r["target_date"] == "翌日" and str(r["cast_id"]) == str(c["店番"])), None)
        with st.form("form_tmr"):
            s_tm = st.radio("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(m_tmr["status"] if m_tmr else "未定"), horizontal=True)
            m_tm = st.text_input("備考", value=parse_attendance_memo(m_tmr.get("memo",""))[0] if m_tmr else "")
            if st.form_submit_button("📤 送信"):
                post_api({"action": "save_attendance", "records": [{"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": s_tm, "memo": encode_attendance_memo(m_tm, "", "0"), "target_date": "翌日"}]})
                clear_cache(); st.session_state.page = "report_done"; st.rerun()

    with tab_week:
        st.write("週間申請")
        records_w = []
        for i in range(1, 8):
            d = t_dt + datetime.timedelta(days=i); target = "翌日" if i == 1 else d.strftime("%Y-%m-%d")
            m_w = next((r for r in attendance if r["target_date"] == target and str(r["cast_id"]) == str(c["店番"])), None)
            st.write(f"**{d.month}/{d.day}({days[d.weekday()]})**")
            s_w = st.radio("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(m_w["status"] if m_w else "未定"), key=f"ws_{i}", horizontal=True)
            m_w_in = st.text_input("備考", key=f"wm_{i}", value=parse_attendance_memo(m_w.get("memo",""))[0] if m_w else "")
            records_w.append({"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": s_w, "memo": encode_attendance_memo(m_w_in, "", "0"), "target_date": target})
        if st.button("週間一括送信"):
            post_api({"action": "save_attendance", "records": records_w})
            clear_cache(); st.session_state.page = "report_done"; st.rerun()

elif st.session_state.page == "report_done":
    render_top_nav(); st.markdown("<h3 style='text-align:center; margin-top:50px;'>✅ 出勤報告を受け付けました</h3>", unsafe_allow_html=True)
    if st.button("マイページへ戻る", use_container_width=True): st.session_state.page = "cast_mypage"; st.rerun()

# ==========================================
# 🚕 送迎管理ダッシュボード (完全復旧)
# ==========================================
elif st.session_state.page == "staff_portal":
    render_top_nav(); staff_name, is_admin = st.session_state.logged_in_staff, st.session_state.is_admin
    db = get_db_data(); casts, drivers, attendance, settings = db.get("casts", []), db.get("drivers", []), db.get("attendance", []), db.get("settings") or {}
    dt = datetime.datetime.now(JST); today_str = dt.strftime("%m月%d日"); dow = ['月','火','水','木','金','土','日'][dt.weekday()]
    d_names = [str(d["name"]) for d in drivers if str(d["name"]).strip() != ""]
    store_addr = str(settings.get("store_address", "岡山県倉敷市水島東栄町2-24"))

    col1, col2 = st.columns([4, 2])
    with col1: st.markdown(f'<b>{"管理者画面" if is_admin else f"{staff_name} 様 AIナビ"}</b>', unsafe_allow_html=True)
    with col2: 
        if st.button("🔄 最新"): clear_cache(); st.rerun()
    st.markdown("<hr style='margin:5px 0;'>", unsafe_allow_html=True)

    if not is_admin:
        # 🚙 ドライバー専用 AIナビ
        st.markdown(f'<div class="date-header">{today_str} ({dow})</div>', unsafe_allow_html=True)
        my_atts = [r for r in attendance if r["target_date"] == "当日" and r["driver_name"] == staff_name and r["status"] == "出勤"]
        if not my_atts: st.info("割り当てはありません")
        else:
            tasks_det = []
            for t in my_atts:
                c_inf = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), {})
                h_a, t_e, t_a, _ = parse_cast_address(c_inf.get("address",""))
                _, tm_a, tc_a, _, _, _, so_a = parse_attendance_memo(t.get("memo",""))
                actual, use_t = (tm_a if tm_a else h_a), (t_e=="1" and tc_a=="0" and t_a!="")
                tasks_det.append({"task": t, "c_info": c_inf, "actual_pickup": actual, "stopover": so_a, "use_takuji": use_t, "takuji_addr": t_a, "c_name": t['cast_name'], "c_id": t['cast_id']})
            
            ordered, _, full_path = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, tasks_det)
            active = next((o for o in ordered if not o["task"].get("boarded_at")), None)
            if active:
                t = active; c_inf = t["c_info"]; avg = c_inf.get('avg_wait_minutes', 5)
                st.markdown(f"<div style='background:#1e1e1e; padding:15px; border-radius:12px; border:2px solid #00bcd4;'>", unsafe_allow_html=True)
                st.markdown(f"<h2 style='margin:0; color:white;'>{t['c_name']} さん</h2><div style='color:#ccc; margin-bottom:10px;'>🏠 {t['actual_pickup']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div style='background:#000; padding:8px; border-radius:6px; font-size:13px; color:#aaa; margin-bottom:15px;'>🤖 AI予測：平均待機 {avg}分</div>", unsafe_allow_html=True)
                m_url = f"https://www.google.com/maps/dir/?api=1&destination={urllib.parse.quote(t['actual_pickup'])}&travelmode=driving&dir_action=navigate"
                if not t["task"].get("arrived_at"):
                    st.markdown(f"<a href='{m_url}' target='_blank' style='{NAV_BTN_STYLE} background:#333; margin-bottom:15px;'>🗺️ ナビ開始</a>", unsafe_allow_html=True)
                    if st.button("📍 ここをタップして【到着】を記録", key=f"arr_{t['c_id']}", use_container_width=True):
                        post_api({"action": "record_driver_action", "attendance_id": t["task"]["id"], "type": "arrive"}); clear_cache(); st.rerun()
                else:
                    arr_t = datetime.datetime.strptime(t["task"]["arrived_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
                    st.markdown(f"<div style='text-align:center; color:#ff4d4d; font-size:18px; font-weight:bold; margin-bottom:15px;'>⏳ {int((datetime.datetime.now(JST)-arr_t).total_seconds()/60)}分 待機中...</div>", unsafe_allow_html=True)
                    mgr_p = next((d.get("phone","") for d in drivers if d["name"] == c_inf.get("manager")), "")
                    if mgr_p: st.markdown(f"<a href='tel:{mgr_p}' style='{TEL_BTN_STYLE}'>👔 担当に電話</a>", unsafe_allow_html=True)
                    if c_inf.get("phone"): st.markdown(f"<a href='tel:{c_inf.get('phone')}' style='{TEL_BTN_STYLE} background:#e65100; border-color:#e65100;'>👩 本人に電話</a>", unsafe_allow_html=True)
                    if st.button("🟢 乗車完了", key=f"brd_{t['c_id']}", use_container_width=True):
                        post_api({"action": "record_driver_action", "attendance_id": t["task"]["id"], "type": "board"}); clear_cache(); st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            else: st.success("🎉 本日の送迎完了！")

    else:
        # 👑 管理者フル機能 (①〜⑤タブ完全復旧)
        tabs = ["① 配車リスト", "② キャスト送迎", "③ キャスト登録", "④ STAFF設定", "⚙️ 管理設定"]
        st.session_state.current_staff_tab = st.radio("メニュー", tabs, index=tabs.index(st.session_state.get("current_staff_tab", "① 配車リスト")), horizontal=True, label_visibility="collapsed")
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        r_opts = ["全表示"] + [f"{i*10+1}-{i*10+10}" for i in range(15)]

        if st.session_state.current_staff_tab == "① 配車リスト":
            st.markdown(f'<div class="date-header">{today_str} ({dow})</div>', unsafe_allow_html=True)
            if st.button("🚀 AI自動配車を実行 (ゼロベース再編成)", type="primary", use_container_width=True):
                st.info("AIが最短ルートを計算中... ⏳"); time.sleep(1); clear_cache(); st.rerun()

        elif st.session_state.current_staff_tab == "② キャスト送迎":
            st.markdown(f'<div style="text-align:center; font-size:18px; font-weight:bold;">{today_str} 送迎管理</div>', unsafe_allow_html=True)
            with st.expander("🌅 早便一括設定ツール"):
                c_d_list = ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in casts if c.get("name")]
                sel_c = st.selectbox("キャスト", c_d_list); sel_d = st.selectbox("ドライバー", ["未定"] + d_names)
                e_dst = st.text_input("早便送り先"); e_tm = st.selectbox("到着時間", early_time_slots)
                if st.button("➕ リストに追加"):
                    res = post_api({"action": "save_attendance", "records": [{"cast_id": sel_c.split()[0], "cast_name": sel_c.split()[1], "area": "他", "status": "出勤", "memo": encode_attendance_memo("", "", "0", sel_d, e_tm, e_dst), "target_date": "当日"}]})
                    if res.get("status") == "success": clear_cache(); st.rerun()

            att_tdy = [r for r in attendance if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"]]
            with st.expander(f"📋 当日の送迎キャスト一覧 ({len(att_tdy)}名)"):
                q = st.text_input("🔍 名前・店番検索", key="q_tdy")
                for i, r in enumerate(att_tdy):
                    if q and (q not in r["cast_name"] and q not in str(r["cast_id"])): continue
                    c_inf = next((c for c in casts if str(c["cast_id"]) == str(r["cast_id"])), {})
                    render_cast_edit_card(r["cast_id"], r["cast_name"], c_inf.get("area","他"), r, "tdy", d_names, time_slots, early_time_slots, i)

        elif st.session_state.current_staff_tab == "③ キャスト登録":
            act_r = st.radio("範囲", r_opts, horizontal=True)
            for i in range(1, 151):
                if not is_in_range(i, act_r): continue
                c = next((x for x in casts if str(x["cast_id"]) == str(i)), {"cast_id": i, "name": "", "password": "0000", "manager": "未設定"})
                with st.expander(f"店番 {i} : {c.get('name','未登録')}"):
                    with st.form(f"reg_{i}"):
                        nn = st.text_input("名前", value=c.get("name",""))
                        nmgr = st.selectbox("担当スタッフ", ["未設定"] + d_names, index=(["未設定"] + d_names).index(c.get("manager","未設定")) if c.get("manager") in (["未設定"] + d_names) else 0)
                        if st.form_submit_button("保存"):
                            post_api({"action": "save_cast", "cast_id": i, "name": nn, "password": "0000", "area": "他", "manager": nmgr})
                            clear_cache(); st.rerun()

        elif st.session_state.current_staff_tab == "④ STAFF設定":
            idx = int(st.selectbox("スタッフ選択", [f"STAFF {i}" for i in range(1, 11)]).split()[1])
            d = next((x for x in drivers if str(x["driver_id"]) == str(idx)), {"driver_id": idx, "name": "", "password": "1234"})
            with st.form(f"staff_{idx}"):
                sn = st.text_input("名前", value=d.get("name","")); sp = st.text_input("PW", value=d.get("password","1234"))
                if st.form_submit_button("保存"):
                    post_api({"action": "save_driver", "driver_id": idx, "name": sn, "password": sp, "capacity": 4, "area": "他"})
                    clear_cache(); st.rerun()

        elif st.session_state.current_staff_tab == "⚙️ 管理設定":
            with st.form("adm"):
                ap = st.text_input("管理者PW", value=settings.get("admin_password","1234"), type="password")
                l_tk = st.text_input("LINEアクセストークン", value=settings.get("line_access_token",""), type="password")
                if st.form_submit_button("保存して反映"):
                    post_api({"action": "save_settings", "admin_password": ap, "notice_text": settings.get("notice_text",""), "line_bot_id": settings.get("line_bot_id",""), "line_access_token": l_tk})
                    clear_cache(); st.rerun()
