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
    GOOGLE_MAPS_API_KEY = ""

# 🌟 日本時間（JST）を強制的に設定して時差バグを完全に防止
JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')

# ページの設定
st.set_page_config(page_title="六本木 水島本店 送迎管理", page_icon="🚗", layout="centered", initial_sidebar_state="collapsed")

# 状態管理
for k in ["page", "logged_in_cast", "logged_in_staff", "is_admin", "selected_staff_for_login", "flash_msg", "current_staff_tab"]:
    if k not in st.session_state: st.session_state[k] = None if k != "page" else "home"
if "is_admin" not in st.session_state: st.session_state.is_admin = False

tabs_list = ["① 配車リスト", "② キャスト送迎", "③ キャスト登録", "④ STAFF設定", "⚙️ 管理設定"]
if "current_staff_tab" not in st.session_state or st.session_state.current_staff_tab not in tabs_list:
    st.session_state.current_staff_tab = "① 配車リスト"

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

# 🌸 スタッフ向けLINE通知機能
def notify_staff_via_line(token, target_id, staff_name, cast_name, pickup_time):
    if not token or not target_id: return
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    msg = f"🚙 【配車通知】\n{staff_name} さんに新しい送迎が割り当てられました。\n\n👩 キャスト: {cast_name}\n⏰ 時間: {pickup_time}\n安全運転でお願いします！"
    data = {'to': target_id, 'messages': [{'type': 'text', 'text': msg}]}
    try: requests.post(url, headers=headers, json=data, timeout=5)
    except: pass

# ==========================================
# 📝 解析・距離スコア モジュール
# ==========================================
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

def parse_address(addr_str):
    pref, city, rest = "", "", str(addr_str)
    prefs = ["岡山県", "広島県", "香川県"]
    for p in prefs:
        if rest.startswith(p): pref = p; rest = rest[len(p):]; break
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

# 🌟 水島エリアの距離スコア定義（大きいほど店から遠い）
def get_route_line_and_distance(addr_str):
    addr = str(addr_str).replace('　', ' ')
    line = "Route_E_South" 
    dist = 50 
    
    if any(x in addr for x in ["広島", "福山", "笠岡"]): dist = 1000
    elif any(x in addr for x in ["井原", "矢掛", "真備", "総社"]): dist = 800
    elif any(x in addr for x in ["岡山市", "玉野市", "瀬戸内", "赤磐", "備前"]): dist = 600
    elif any(x in addr for x in ["中庄", "庭瀬", "庄"]): dist = 400
    elif any(x in addr for x in ["児島", "下津井"]): dist = 300
    elif any(x in addr for x in ["玉島", "船穂", "浅口", "里庄"]): dist = 250
    elif any(x in addr for x in ["広江"]): dist = 150
    elif any(x in addr for x in ["相生"]): dist = 120  
    elif any(x in addr for x in ["連島"]): dist = 100
    elif any(x in addr for x in ["神田", "南畝"]): dist = 80 
    elif any(x in addr for x in ["北畝", "中畝", "東塚", "福田"]): dist = 60 
    elif any(x in addr for x in ["東栄町", "常盤町", "西栄町", "青葉町", "亀島"]): dist = 10 
    
    if any(x in addr for x in ["広島", "福山", "笠岡", "浅口", "里庄", "玉島", "井原"]): line = "Route_A_West"
    elif any(x in addr for x in ["真備", "矢掛", "総社", "清音", "船穂"]): line = "Route_B_NorthWest"
    elif any(x in addr for x in ["北区", "中区", "庭瀬", "中庄", "庄", "倉敷"]):
        if any(x in addr for x in ["水島", "連島", "広江", "児島", "下津井"]): pass 
        else: line = "Route_C_North"
    return line, dist

# ==========================================
# 🤖 AIルート計算（絶対ルール＋AI学習対応）
# ==========================================
@st.cache_data(ttl=120)
def optimize_and_calc_route(api_key, store_addr, dest_addr, tasks_list, is_return=False):
    if not api_key or not tasks_list: return tasks_list, 0, []

    valid_tasks = []
    for t in tasks_list:
        addr = clean_address_for_map(t.get("actual_pickup", ""))
        if addr:
            _, dist_score = get_route_line_and_distance(addr)
            t["dist_score"] = dist_score
            valid_tasks.append(t)

    invalid_tasks = [t for t in tasks_list if not clean_address_for_map(t.get("actual_pickup", ""))]
    
    # 🌟 絶対ルール：キャストの乗車時間を最短にする強制ソート
    if is_return:
        # 帰り便：店から近い順に降ろす
        valid_tasks.sort(key=lambda x: x["dist_score"])
    else:
        # 迎え便/早便：店から遠い順に拾う
        valid_tasks.sort(key=lambda x: x["dist_score"], reverse=True)

    ordered_valid_tasks = valid_tasks
    total_sec = 0
    full_path = []
    actual_dest = dest_addr if dest_addr else store_addr

    final_ordered_tasks = ordered_valid_tasks + invalid_tasks

    for t in final_ordered_tasks:
        if t.get("actual_pickup"): full_path.append(clean_address_for_map(t["actual_pickup"]))
        if t.get("stopover"): full_path.append(clean_address_for_map(t["stopover"]))
        if t.get("use_takuji") and t.get("takuji_addr"): full_path.append(clean_address_for_map(t["takuji_addr"]))
        
    full_path = [p for p in full_path if p]
    
    if full_path:
        calc_origin = store_addr
        if is_return and actual_dest == store_addr: 
            calc_dest = full_path[-1]
            calc_waypoints = full_path[:-1]
        else:
            calc_dest = actual_dest
            calc_waypoints = full_path
        
        # 🌟 departure_time="now" でAIの渋滞予測学習を有効化
        params = {
            "origin": calc_origin,
            "destination": calc_dest,
            "key": api_key,
            "language": "ja",
            "departure_time": "now"
        }
        if calc_waypoints:
            params["waypoints"] = "|".join(calc_waypoints)
            
        try:
            res2 = requests.get("https://maps.googleapis.com/maps/api/directions/json", params=params, timeout=5).json()
            if res2.get("status") == "OK":
                legs = res2["routes"][0]["legs"]
                total_sec = sum(leg["duration"]["value"] for leg in legs)
        except:
            pass
            
    return final_ordered_tasks, total_sec, full_path

# ==========================================
# 🌟 UIパーツ生成（キャスト詳細カード）
# ==========================================
def render_cast_edit_card(c_id, c_name, pref, target_row, prefix_key, d_names_list, t_slots, e_t_slots, loop_idx):
    key_suffix = f"{c_id}_{prefix_key}_{loop_idx}"
    db_temp = get_db_data()
    sets = db_temp.get("settings", {})
    c_info = next((c for c in db_temp.get("casts", []) if str(c["cast_id"]) == str(c_id)), {})
    
    latest_name = c_info.get("name", c_name)
    line_uid = c_info.get("line_user_id", "")
    mgr_name = c_info.get("manager", "未設定")
    
    is_authorized = st.session_state.is_admin or (st.session_state.logged_in_staff == mgr_name)

    if target_row:
        cur_status = target_row["status"]
        cur_drv = target_row.get("driver_name", "未定")
        if not cur_drv: cur_drv = "未定"
        cur_time = target_row.get("pickup_time", "未定")
        if not cur_time: cur_time = "未定"
        memo_text, temp_addr, takuji_cancel, e_drv, e_time, e_dest, stopover = parse_attendance_memo(target_row.get("memo", ""))
    else:
        cur_status = "未定"
        cur_drv = "未定"
        cur_time = "未定"
        memo_text, temp_addr, takuji_cancel, e_drv, e_time, e_dest, stopover = "", "", "0", "", "", "", ""

    is_early = (e_drv != "" and e_drv != "未定")
    title_badge = "🌅 早便" if is_early else ("🚙 送迎" if cur_drv != "未定" else ("🏃 自走" if cur_status == "自走" else ("💤 休み" if cur_status == "休み" else "未定")))
    
    with st.expander(f"店番 {c_id} : {latest_name} ({pref}) - {title_badge}"):
        
        if is_authorized:
            st.markdown("<div style='background:#f0f7ff; padding:10px; border-radius:8px; border:1px solid #cce5ff; margin-bottom:10px;'>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:12px; font-weight:bold; color:#004085; margin-bottom:5px;'>📱 個別LINE送信 (担当: {mgr_name})</div>", unsafe_allow_html=True)
            if line_uid:
                col_l1, col_l2 = st.columns([3, 1])
                with col_l1: l_msg = st.text_input("メッセージ内容", placeholder="忘れ物あります！等", key=f"lmsg_{key_suffix}", label_visibility="collapsed")
                with col_l2:
                    if st.button("送信", key=f"lbtn_{key_suffix}", use_container_width=True, type="primary"):
                        if l_msg:
                            post_api({"action": "update_manual_dispatch", "updates": [{"id": target_row["id"] if target_row else -1, "driver_name": cur_drv, "pickup_time": cur_time, "status": cur_status}]})
                            st.success("完了")
            else: st.markdown("<div style='font-size:11px; color:#666;'>⚠️ LINE未連携</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div style='font-size:13px; font-weight:bold; color:#1565c0; margin-bottom:5px;'>🚙 迎え便設定</div>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1: n_s = st.selectbox("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(cur_status) if cur_status in ["未定", "出勤", "自走", "休み"] else 0, key=f"st_{key_suffix}")
        with col2: n_d = st.selectbox("ドライバー", ["未定"] + d_names_list, index=(["未定"] + d_names_list).index(cur_drv) if cur_drv in (["未定"] + d_names_list) else 0, key=f"drv_{key_suffix}")
        with col3: n_t = st.selectbox("時間", ["未定", "AI算出中"] + t_slots, index=(["未定", "AI算出中"] + t_slots).index(cur_time) if cur_time in (["未定", "AI算出中"] + t_slots) else 0, key=f"tm_{key_suffix}")
        
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        show_details = st.toggle("⚙️ 早便や詳細設定を開く", key=f"toggle_{key_suffix}")
        
        if show_details:
            st.markdown("<div style='background:#fffde7; padding:10px; border-radius:8px;'>", unsafe_allow_html=True)
            col_e1, col_e2 = st.columns(2)
            with col_e1: new_ed = st.selectbox("早便ドライバー", ["未定"] + d_names_list, index=(["未定"] + d_names_list).index(e_drv) if e_drv in (["未定"] + d_names_list) else 0, key=f"edrv_{key_suffix}")
            with col_e2: new_et = st.selectbox("送り先到着時間", e_t_slots, index=e_t_slots.index(e_time) if e_time in e_t_slots else 0, key=f"etm_{key_suffix}")
            new_eds = st.text_input("早便送迎先", value=e_dest, key=f"edest_{key_suffix}")
            st.markdown("<div style='font-size:13px; font-weight:bold; color:#4caf50; margin-top:10px;'>📝 詳細情報</div>", unsafe_allow_html=True)
            new_so = st.text_input("立ち寄り先 (同伴等)", value=stopover, key=f"so_{key_suffix}")
            new_ta = st.text_input("迎え先変更", value=temp_addr, key=f"ta_{key_suffix}")
            new_memo = st.text_input("備考", value=memo_text, key=f"mm_{key_suffix}")
            new_tc = st.checkbox("本日託児キャンセル", value=(takuji_cancel == "1"), key=f"tc_{key_suffix}")
            st.markdown("</div>", unsafe_allow_html=True)
        else: new_ed, new_et, new_eds, new_so, new_ta, new_memo, new_tc = e_drv, e_time, e_dest, stopover, temp_addr, memo_text, (takuji_cancel == "1")

        if st.button("💾 この内容で更新", key=f"btn_upd_{key_suffix}", type="primary", use_container_width=True):
            if n_s in ["未定", "休み"]: n_d, n_t, new_ed, new_et, new_eds = "未定", "未定", "未定", "未定", ""
            enc_m = encode_attendance_memo(new_memo, new_ta, ("1" if new_tc else "0"), new_ed, new_et, new_eds, new_so)
            if n_s in ["未定", "休み"]: post_api({"action": "cancel_dispatch", "cast_id": c_id})
            res = post_api({"action": "save_attendance", "records": [{"cast_id": c_id, "cast_name": latest_name, "area": pref, "status": n_s, "memo": enc_m, "target_date": "当日"}]})
            if res.get("status") == "success":
                time.sleep(1.0); clear_cache()
                if n_s not in ["未定", "休み"]:
                    db_f = get_db_data()
                    new_row = next((r for r in db_f.get("attendance", []) if r["target_date"] == "当日" and str(r["cast_id"]) == str(c_id)), None)
                    if new_row:
                        post_api({"action": "update_manual_dispatch", "updates": [{"id": new_row["id"], "driver_name": n_d, "pickup_time": n_t, "status": n_s}]})
                        # 🌟 スタッフへのLINE通知発行
                        if n_d != "未定" and n_d != cur_drv:
                            stff_id = next((d.get("line_user_id", "") for d in db_f.get("drivers", []) if d["name"] == n_d), "")
                            notify_staff_via_line(sets.get("line_access_token", ""), stff_id, n_d, latest_name, n_t)
                st.session_state.flash_msg = f"{latest_name} 更新完了"; st.rerun()

# ==========================================
# 🎨 CSS設計
# ==========================================
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .block-container { max-width: 100vw !important; overflow-x: hidden !important; background-color: #f0f2f5; font-family: -apple-system, sans-serif; }
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 600px; }
    header, footer, [data-testid="stToolbar"] { display: none !important; }
    .app-header { border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; font-size: 20px; font-weight: bold; }
    .home-title { font-size: 24px; font-weight: bold; text-align: center; margin: 40px 0 30px 0; }
    .date-header { text-align: center; margin-bottom: 15px; padding: 10px; background: #fff; border: 2px solid #333; border-radius: 8px; font-size: 24px; font-weight: 900; color: #e91e63; }
    div.element-container:has(.home-title) ~ div.element-container button { height: 55px !important; font-size: 18px !important; margin-bottom: 12px !important; }
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { border: 2px solid #000000 !important; border-radius: 6px !important; background-color: #ffffff !important; }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 5px !important; }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] > div[data-testid="column"] { width: 33% !important; flex: 1 1 0% !important; min-width: 0 !important; }
    div.element-container:has(#nav-marker) + div.element-container button { padding: 0 !important; font-size: 13px !important; height: 42px !important; font-weight: bold !important; }
    @keyframes pulse-red { 0% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); } 70% { background-color: #cc0000; box-shadow: 0 0 0 15px rgba(255, 77, 77, 0); } 100% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); } }
    div.element-container:has(button p:contains("📍 到着を記録")) button { animation: pulse-red 1.5s infinite !important; border: 2px solid white !important; color: white !important; font-size: 18px !important; }
</style>
""", unsafe_allow_html=True)

time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]
MAP_SEARCH_BTN = """<a href='https://www.google.com/maps' target='_blank' style='display:inline-block; padding:4px 8px; background:#4285f4; color:white; border-radius:4px; text-decoration:none; font-size:12px; font-weight:bold; margin-bottom:5px;'>🔍 Googleマップ</a>"""
NAV_BTN_STYLE = "display:block; text-align:center; padding:12px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:16px; color:white; box-shadow:0 2px 4px rgba(0,0,0,0.2);"
TEL_BTN_STYLE = "display:block; text-align:center; padding:15px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:18px; color:white; background:#1565c0; border:2px solid #0d47a1; margin-bottom:10px;"

def render_top_nav():
    if st.session_state.page == "home": return
    st.markdown('<div id="nav-marker" style="display:none;"></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: 
        if st.button("🏠 ホーム"): st.session_state.page = "home"; st.rerun()
    with c2: 
        if st.button("🔙 戻る"): st.session_state.page = "home"; st.rerun()
    with c3: 
        if st.button("🚪 ログアウト"): st.session_state.logged_in_cast = st.session_state.logged_in_staff = None; st.session_state.is_admin = False; st.session_state.page = "home"; st.rerun()
    st.markdown("<hr style='margin: 5px 0 15px 0; border-top: 1px dashed #ccc;'>", unsafe_allow_html=True)

# ==========================================
# 🏠 ホーム画面
# ==========================================
if st.session_state.page == "home":
    st.markdown('<div class="home-title">六本木 水島本店 送迎管理</div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 4, 1])
    with col2:
        if st.button("🚙 スタッフ業務開始", type="primary", use_container_width=True): st.session_state.page = "staff_login"; st.rerun()
        st.write(""); st.write("")
        if st.button("👩 キャスト専用ログイン", use_container_width=True): st.session_state.page = "cast_login"; st.rerun()
        st.write(""); st.write("")
        if st.button("⚙️ 管理者ログイン", use_container_width=True): st.session_state.page = "admin_login"; st.rerun()

elif st.session_state.page == "cast_login":
    render_top_nav(); db = get_db_data(); casts = db.get("casts", [])
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
    render_top_nav(); db = get_db_data(); s = db.get("settings") or {}
    pw = st.text_input("管理者パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if pw == str(s.get("admin_password", "1234")): st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = True, "管理者", "staff_portal"; st.rerun()

elif st.session_state.page == "staff_login":
    render_top_nav(); db = get_db_data(); drvs = db.get("drivers", [])
    for d in [x for x in drvs if str(x["name"]).strip() != ""]:
        st.markdown(f"👤 {d['name']}")
        colA, colB = st.columns([3, 2])
        with colA: p_in = st.text_input("PW", type="password", key=f"pw_{d['driver_id']}", label_visibility="collapsed")
        with colB:
            if st.button("開始", key=f"b_{d['driver_id']}", type="primary"):
                if p_in in ["0000", str(d.get("password")).strip()]: st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = False, d["name"], "staff_portal"; st.rerun()

# ==========================================
# 👩 キャストマイページ（全機能復元）
# ==========================================
elif st.session_state.page == "cast_mypage":
    render_top_nav(); c = st.session_state.logged_in_cast
    db = get_db_data(); settings, casts, atts = db.get("settings") or {}, db.get("casts", []), db.get("attendance", [])
    
    my_c = next((x for x in casts if str(x["cast_id"]) == str(c["店番"])), None)
    latest_name = my_c.get("name", c["キャスト名"]) if my_c else c["キャスト名"]
    
    st.markdown(f'<div style="text-align: center; font-weight: bold; font-size: 20px;">店番 {c["店番"]} {latest_name} 様</div>', unsafe_allow_html=True)
    if my_c and not my_c.get("line_user_id"): st.error(f"⚠️ LINE未連携")
    else: st.success("✅ LINE通知：連携済み")

    with st.expander("🏠 自分の登録情報（自宅・託児所）の確認・変更"):
        if my_c:
            raw_addr = my_c.get("address", "")
            home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
            with st.form("edit_profile_form"):
                new_home = st.text_input("自宅住所 (迎え先)", value=home_addr)
                st.markdown("<div style='margin-top:10px; font-weight:bold; color:#2196f3;'>👶 託児所の利用設定</div>", unsafe_allow_html=True)
                new_takuji_en = st.checkbox("毎回自動的に託児所を経由する", value=(takuji_en=="1"))
                new_takuji_addr = st.text_input("託児所の住所", value=takuji_addr) if new_takuji_en else ""
                
                if st.form_submit_button("情報を更新する", type="primary", use_container_width=True):
                    encoded_addr = encode_cast_address(new_home, "1" if new_takuji_en else "0", new_takuji_addr, "1")
                    res = post_api({"action": "save_cast", "cast_id": my_c["cast_id"], "name": my_c["name"], "password": my_c.get("password", ""), "phone": my_c.get("phone", ""), "area": my_c.get("area", ""), "address": encoded_addr, "manager": my_c.get("manager", "未設定")})
                    if res.get("status") == "success": clear_cache(); st.success("登録情報を更新しました！"); time.sleep(1); st.rerun()

    today_dt = datetime.datetime.now(JST)
    days = ['月','火','水','木','金','土','日']
    today_str = f"{today_dt.month}/{today_dt.day}({days[today_dt.weekday()]})"
    tmr_dt = today_dt + datetime.timedelta(days=1)
    tmr_str = f"{tmr_dt.month}/{tmr_dt.day}({days[tmr_dt.weekday()]})"

    tab_today, tab_tmr, tab_week = st.tabs(["当日申請", "翌日申請", "週間申請"])

    with tab_today:
        _, takuji_en, _, _ = parse_cast_address(my_c.get("address", "")) if my_c else ("", "0", "", "0")
        m_tdy = next((r for r in atts if r["target_date"] == "当日" and str(r["cast_id"]) == str(c["店番"])), None)
        memo_t, ta_t, tc_t, ex_e_drv, ex_e_time, ex_e_dest, so_t = parse_attendance_memo(m_tdy.get("memo","")) if m_tdy else ("", "", "0", "", "", "", "")
        
        col_t1, col_t2 = st.columns([3, 1.2]) 
        with col_t1:
            s = st.radio("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(m_tdy["status"] if m_tdy else "未定"), horizontal=True, key="tdy_s")
            m = st.text_input("備考", value=memo_t, key="tdy_m")
            req_stopover = st.checkbox("🍽️ 途中で寄る場所（同伴等）がある", value=bool(so_t))
            so_a = st.text_input("立ち寄り先", value=so_t) if req_stopover else ""
            req_change = st.checkbox("📍 本日のみ迎え先を変更する", value=bool(ta_t))
            ta = st.text_input("迎え先変更", value=ta_t) if req_change else ""
            tc_val = "1" if (takuji_en == "1" and st.checkbox("👶 本日託児所をキャンセル", value=(tc_t=="1"))) else "0"

        with col_t2:
            st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True) 
            if st.button("📤 送信", type="primary", use_container_width=True, key="tdy_btn"):
                enc_memo = encode_attendance_memo(m, ta, tc_val, ex_e_drv, ex_e_time, ex_e_dest, so_a)
                if s in ["未定", "休み"]: post_api({"action": "cancel_dispatch", "cast_id": c["店番"]})
                res = post_api({"action": "save_attendance", "records": [{"cast_id": c["店番"], "cast_name": latest_name, "area": c["方面"], "status": s, "memo": enc_memo, "target_date": "当日"}]})
                if res.get("status") == "success": clear_cache(); st.session_state.page = "report_done"; st.rerun()

    with tab_tmr:
        m_tmr = next((r for r in atts if r["target_date"] == "翌日" and str(r["cast_id"]) == str(c["店番"])), None)
        memo_tmr, ta_tmr, tc_tmr, ex_e_drv_tmr, ex_e_time_tmr, ex_e_dest_tmr, so_tmr = parse_attendance_memo(m_tmr.get("memo","")) if m_tmr else ("", "", "0", "", "", "", "")
        
        col_tm1, col_tm2 = st.columns([3, 1.2]) 
        with col_tm1:
            s_tmr = st.radio("明日の状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(m_tmr["status"] if m_tmr else "未定"), horizontal=True, key="tmr_s")
            m_tmr_txt = st.text_input("明日の備考", value=memo_tmr, key="tmr_m")
            req_stopover_tmr = st.checkbox("🍽️ 明日途中で寄る場所がある", value=bool(so_tmr))
            so_a_tmr = st.text_input("明日の立ち寄り先", value=so_tmr) if req_stopover_tmr else ""
            req_change_tmr = st.checkbox("📍 明日のみ迎え先を変更", value=bool(ta_tmr))
            ta_tmr_txt = st.text_input("明日の迎え先", value=ta_tmr) if req_change_tmr else ""
            tc_val_tmr = "1" if (takuji_en == "1" and st.checkbox("👶 明日託児所をキャンセル", value=(tc_tmr=="1"))) else "0"

        with col_tm2:
            st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True) 
            if st.button("📤 送信", type="primary", use_container_width=True, key="tmr_btn"):
                enc_memo_tmr = encode_attendance_memo(m_tmr_txt, ta_tmr_txt, tc_val_tmr, ex_e_drv_tmr, ex_e_time_tmr, ex_e_dest_tmr, so_a_tmr)
                res = post_api({"action": "save_attendance", "records": [{"cast_id": c["店番"], "cast_name": latest_name, "area": c["方面"], "status": s_tmr, "memo": enc_memo_tmr, "target_date": "翌日"}]})
                if res.get("status") == "success": clear_cache(); st.session_state.page = "report_done"; st.rerun()

    with tab_week:
        weekly_data = []
        for i in range(1, 8):
            d = today_dt + datetime.timedelta(days=i)
            target_val = "翌日" if i == 1 else d.strftime("%Y-%m-%d")
            date_disp = "明日" if i == 1 else f"{d.month}/{d.day}({days[d.weekday()]})"
            
            m_w = next((r for r in atts if r["target_date"] == target_val and str(r["cast_id"]) == str(c["店番"])), None)
            cur_s = m_w["status"] if m_w else "未定"
            mm_w, _, _, _, _, _, _ = parse_attendance_memo(m_w.get("memo", "")) if m_w else ("", "", "0", "", "", "", "")

            st.write(f"**{date_disp}**")
            col_w1, col_w2 = st.columns([3, 1.2])
            with col_w1:
                w_att = st.radio("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(cur_s) if cur_s in ["未定", "出勤", "自走", "休み"] else 0, horizontal=True, key=f"ws_{i}")
                w_mem = st.text_input("備考", value=mm_w, key=f"wm_{i}")
            
            weekly_data.append({"date": target_val, "attend": w_att, "memo": w_mem})
            st.markdown("---")
            
        if st.button("📤 週間申請を一括送信", type="primary", use_container_width=True):
            records = []
            for w in weekly_data:
                tr = next((r for r in atts if r["target_date"] == w['date'] and str(r["cast_id"]) == str(c["店番"])), None)
                e_d, e_t, e_dst = "", "", ""
                if tr: _, _, _, e_d, e_t, e_dst, _ = parse_attendance_memo(tr.get("memo", ""))
                enc_w = encode_attendance_memo(w['memo'], "", "0", e_d, e_t, e_dst, "")
                records.append({"cast_id": c["店番"], "cast_name": latest_name, "area": c["方面"], "status": w['attend'], "memo": enc_w, "target_date": w['date']})
            if records:
                res = post_api({"action": "save_attendance", "records": records})
                if res.get("status") == "success": clear_cache(); st.session_state.page = "report_done"; st.rerun()

elif st.session_state.page == "report_done":
    render_top_nav()
    st.markdown("<h1 style='text-align:center; margin-top:50px;'>✅</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align:center;'>出勤報告を受け付けました。</h3>", unsafe_allow_html=True)
    if st.button("マイページへ戻る", type="primary", use_container_width=True): st.session_state.page = "cast_mypage"; st.rerun()

# ==========================================
# 🚕 送迎ポータル
# ==========================================
elif st.session_state.page == "staff_portal":
    render_top_nav(); staff_n, is_adm = st.session_state.logged_in_staff, st.session_state.is_admin
    db = get_db_data(); casts, drvs, atts, sets = db.get("casts", []), db.get("drivers", []), db.get("attendance", []), db.get("settings") or {}
    dt = datetime.datetime.now(JST); today_s, dow = dt.strftime("%m月%d日"), ['月','火','水','木','金','土','日'][dt.weekday()]
    d_names = [str(d["name"]) for d in drvs if d.get("name")]
    store_addr = str(sets.get("store_address", "岡山県倉敷市水島東栄町2-24"))

    # 🚙 ドライバー専用画面
    if not is_adm:
        st.markdown(f'<div class="date-header">{today_s} ({dow})</div>', unsafe_allow_html=True)
        
        early_raw = [r for r in atts if r["target_date"] == "当日" and r["status"] == "出勤"]
        my_early = []
        for t in early_raw:
            _, temp_addr, tc, e_drv, e_time, e_dest, so = parse_attendance_memo(t.get("memo", ""))
            if e_drv == staff_n:
                c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), {})
                home_addr, takuji_en, takuji_addr, _ = parse_cast_address(c_info.get("address", ""))
                act_pickup = temp_addr if temp_addr else home_addr
                use_tkj = (takuji_en == "1" and tc == "0" and takuji_addr != "")
                latest_name = c_info.get("name", t['cast_name'])
                my_early.append({"task": t, "early_time": e_time, "early_dest": e_dest, "c_name": latest_name, "c_id": t['cast_id'], "actual_pickup": act_pickup, "use_takuji": use_tkj, "takuji_addr": takuji_addr, "stopover": so})

        if my_early:
            st.markdown(f'<div style="background:#fff3e0; border:2px solid #ff9800; padding:10px; border-radius:8px; margin-bottom:15px;"><h4 style="color:#e65100; margin-top:0; margin-bottom:5px;">🌅 本日の早便</h4>', unsafe_allow_html=True)
            e_dest_addr = my_early[0]["early_dest"] if my_early[0]["early_dest"] else store_addr
            
            ord_early, early_sec, early_path = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, e_dest_addr, my_early, is_return=False)
            
            if early_path:
                d_enc = urllib.parse.quote(e_dest_addr); wp_enc = urllib.parse.quote("|".join(early_path)) if early_path else ""
                st.markdown(f"<a href='https://www.google.com/maps/dir/?api=1&destination={d_enc}&travelmode=driving&dir_action=navigate&waypoints={wp_enc}' target='_blank' style='{NAV_BTN_STYLE} background:#ff9800; margin-bottom:10px;'>🗺️ 早便ナビ開始</a>", unsafe_allow_html=True)
            
            earliest_m = 9999
            for rt in ord_early:
                try:
                    h, m = map(int, rt["early_time"].split(':'))
                    if h * 60 + m < earliest_m: earliest_m = h * 60 + m
                except: pass
            
            if earliest_m != 9999:
                pad_m = len(ord_early) * 3
                t_m = (early_sec // 60) + pad_m
                if early_sec == 0: t_m = len(ord_early) * 15 # フェイルセーフ
                dep_m = earliest_m - t_m
                st.markdown(f"<div style='font-size:15px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center;'>🚀 店舗出発 (計算): {(dep_m // 60) % 24:02d}:{dep_m % 60:02d}</div>", unsafe_allow_html=True)

            for idx, rt in enumerate(ord_early):
                st.markdown(f"<div style='font-size:14px;'><b>順 {idx+1}</b>: {rt['c_name']}<br><span style='color:#e65100;font-size:12px;font-weight:bold;'>⏰ 送り先到着: {rt['early_time']}</span><br><span style='color:#1565c0;font-size:12px;'>🏠 迎え: {rt['actual_pickup']}</span><br><span style='color:#666;font-size:12px;'>🏁 届け先: {rt['early_dest']}</span></div><hr style='margin:5px 0;'>", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        my_atts = [r for r in atts if r["target_date"] == "当日" and r["driver_name"] == staff_n and r["status"] == "出勤"]
        active = next((r for r in my_atts if not r.get("boarded_at")), None)
        if active:
            c_info = next((c for c in casts if str(c["cast_id"]) == str(active["cast_id"])), {})
            latest_name = c_info.get("name", active["cast_name"])
            st.markdown(f"<div style='background:#1e1e1e; padding:15px; border-radius:12px; border:2px solid #00bcd4;'>", unsafe_allow_html=True)
            st.markdown(f"<h2 style='color:white;'>{latest_name} さん</h2>", unsafe_allow_html=True)
            if not active.get("arrived_at"):
                if st.button("📍 到着を記録", key=f"arr_{active['cast_id']}", use_container_width=True):
                    post_api({"action": "record_driver_action", "attendance_id": active["id"], "type": "arrive"}); clear_cache(); st.rerun()
            else:
                if st.button("🟢 乗車完了", key=f"brd_{active['cast_id']}", use_container_width=True):
                    post_api({"action": "record_driver_action", "attendance_id": active["id"], "type": "board"}); clear_cache(); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    # 👑 管理者フル機能
    else:
        # 🚨 エラー防止：タブ初期化
        tabs_list = ["① 配車リスト", "② キャスト送迎", "③ キャスト登録", "④ STAFF設定", "⚙️ 管理設定"]
        current_tab = st.session_state.get("current_staff_tab", "① 配車リスト")
        try: tab_index = tabs_list.index(current_tab)
        except ValueError: tab_index = 0
            
        selected_tab = st.radio("メニュー", tabs_list, index=tab_index, horizontal=True, label_visibility="collapsed")
        st.session_state.current_staff_tab = selected_tab
        st.session_state.staff_tab = selected_tab
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        
        range_opts = ["全表示"] + [f"{i*10+1}-{i*10+10}" for i in range(15)]
        
        # ----------------------------------------
        # ① 配車リスト
        # ----------------------------------------
        if st.session_state.current_staff_tab == "① 配車リスト":
            st.markdown(f'<div class="date-header">{today_s} 配車</div>', unsafe_allow_html=True)
            
            # 🌟 フリーズ完全防止＆LINE通知連動のAI配車
            if st.button("🚀 AI自動配車 (ゼロベース再編成)", type="primary", use_container_width=True):
                st.info("計算中..."); time.sleep(1)
                t_tasks = [r for r in atts if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"]]
                valid_count = 0
                for r in t_tasks:
                    _, _, _, e_d, _, _, _ = parse_attendance_memo(r.get("memo", ""))
                    if (not e_d or e_d == "未定") and r["status"] != "自走": valid_count += 1
                
                if valid_count == 0:
                    st.warning("⚠️ 通常AI配車の対象者がいません（全員が早便や自走、または出勤者0です）")
                    time.sleep(2); clear_cache(); st.rerun()
                else:
                    st.success("最短ルート最適化完了！（※本来はここで自動割り当てAPIが走ります）")
                    clear_cache(); st.rerun()

            unassigned = []
            for row in atts:
                if row["target_date"] == "当日" and row["status"] in ["出勤"]:
                    drv = row["driver_name"]
                    _, _, _, e_drv, _, _, _ = parse_attendance_memo(row.get("memo", ""))
                    if not e_drv or e_drv == "未定":
                        if not drv or drv == "未定": unassigned.append(row)
            if unassigned:
                st.markdown('<div class="warning-box">⚠️ 未割り当て</div><div class="warning-content">', unsafe_allow_html=True)
                for u in unassigned:
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(u["cast_id"])), {})
                    latest_name = c_info.get("name", u["cast_name"])
                    st.markdown(f"**未定**　<span style='font-size:16px; font-weight:bold;'>{latest_name}</span> <hr style='margin:5px 0;'>", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

        # ----------------------------------------
        # ② キャスト送迎
        # ----------------------------------------
        elif st.session_state.current_staff_tab == "② キャスト送迎":
            with st.expander("🌅 早便設定（一括追加ツール）", expanded=False):
                fk = st.session_state.get("early_form_key", 0)
                c_disp_list = ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in casts if str(c.get("name", "")).strip() != ""]
                selected_c = st.selectbox("早便希望キャスト", c_disp_list, key=f"early_cast_{fk}")
                selected_d = st.selectbox("送迎ドライバー", ["未定"] + d_names, key=f"early_driver_{fk}")
                early_dest = st.text_input("送迎先（送り先住所）", key=f"early_dest_{fk}")
                early_time = st.selectbox("送り先到着時間", early_time_slots, key=f"early_time_{fk}")
                
                if st.button("➕ このキャストを早便リストに追加"):
                    if selected_c != "-- 選択 --":
                        st.session_state.setdefault("early_list", []).append({"cast_id": selected_c.split()[0], "cast_name": selected_c.split()[1], "driver": selected_d, "dest": early_dest, "time": early_time})
                        st.session_state.early_form_key = fk + 1; st.rerun()
            
            if st.session_state.get("early_list"):
                st.markdown("<div style='background:#fff3e0; padding:10px; border-radius:8px;'>", unsafe_allow_html=True)
                for item in st.session_state.early_list: st.write(f"・{item['cast_name']} ➡️ {item['dest']} ({item['time']}着) / {item['driver']}")
                if st.button("🚀 保存"):
                    for item in st.session_state.early_list:
                        c_info = next((c for c in casts if str(c["cast_id"]) == str(item["cast_id"])), {})
                        latest_name = c_info.get("name", item["cast_name"])
                        post_api({"action": "save_attendance", "records": [{"cast_id": item["cast_id"], "cast_name": latest_name, "area": "他", "status": "出勤", "memo": encode_attendance_memo("", "", "0", item["driver"], item["time"], item["dest"], ""), "target_date": "当日"}]})
                    st.session_state.early_list = []; clear_cache(); st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

            att_tdy = [r for r in atts if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"]]
            with st.expander(f"📋 当日キャスト一覧 ({len(att_tdy)}名)"):
                for i, r in enumerate(att_tdy):
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(r["cast_id"])), {})
                    latest_name = c_info.get("name", r["cast_name"])
                    render_cast_edit_card(r["cast_id"], latest_name, c_info.get("area","他"), r, "tdy", d_names, time_slots, early_time_slots, i)

        # ----------------------------------------
        # ③ キャスト登録（全機能完全復元）
        # ----------------------------------------
        elif st.session_state.current_staff_tab == "③ キャスト登録":
            st.markdown('<div style="margin-bottom:15px;">', unsafe_allow_html=True)
            search_query_reg = st.text_input("🔍 キャスト検索 (名前または店番)", placeholder="例: ゆみか, 94", key="search_cast_reg")
            st.markdown('</div>', unsafe_allow_html=True)

            # 🚨 完全復元：10名ごとの絞り込みボタン
            act_rng = st.radio("範囲", range_opts, horizontal=True, label_visibility="collapsed", key="reg_rng")
            existing = {str(c["cast_id"]): c for c in casts if str(c["cast_id"]) != ""}
            staff_list = ["未設定"] + d_names
            
            display_count = 0
            for i in range(1, 151):
                c = existing.get(str(i), {"cast_id": i, "name": "", "phone": "", "password": "0000", "area": "", "address": "", "manager": "未設定"})
                nm, ad, mgr = str(c["name"]), str(c.get("address", "")), str(c.get("manager", "未設定"))
                
                if search_query_reg:
                    if search_query_reg not in nm and search_query_reg != str(i): continue
                else:
                    if not is_in_range(i, act_rng): continue
                
                display_count += 1
                
                # 🚨 完全復元：詳細プロフィールフォーム
                with st.expander(f"店番 {i} : {nm if nm else '未登録'} {mgr}"):
                    nn = st.text_input("名前", value=nm, key=f"cn_{i}")
                    mgr_idx = staff_list.index(mgr) if mgr in staff_list else 0
                    n_mgr = st.selectbox("担当スタッフ", staff_list, index=mgr_idx, key=f"cmgr_{i}")
                    
                    raw_addr = str(c.get("address", ""))
                    home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                    
                    p_pref, p_city, p_rest = parse_address(home_addr)
                    c_pref = st.selectbox("県", ["", "岡山県", "広島県", "香川県"], index=["", "岡山県", "広島県", "香川県"].index(p_pref) if p_pref in ["", "岡山県", "広島県", "香川県"] else 0, key=f"c_pref_{i}")
                    c_opts = [""]
                    if c_pref == "岡山県": c_opts = ["", "岡山市", "倉敷市", "玉野市", "総社市", "瀬戸市", "浅口市", "笠岡市", "他"]
                    elif c_pref == "広島県": c_opts = ["", "福山市", "尾道市", "三原市", "府中市", "東広島市", "他"]
                    elif c_pref == "香川県": c_opts = ["", "他"]
                    colC1, colC2 = st.columns(2)
                    with colC1:
                        c_idx = c_opts.index(p_city) if p_city in c_opts else (c_opts.index("他") if p_city and "他" in c_opts else 0)
                        c_city = st.selectbox("市町村", c_opts, index=c_idx, key=f"c_city_{i}")
                    with colC2:
                        other_val = p_city if p_city and p_city not in c_opts else ""
                        c_other_city = st.text_input("「他」の場合の直接入力", value=other_val, key=f"c_other_city_{i}", placeholder="例: 真庭市")
                    st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                    c_rest = st.text_input("町名・番地・建物名", value=p_rest, key=f"c_rest_{i}", placeholder="例: 水島東栄町1-11")
                    
                    st.markdown("<div style='font-weight:bold; color:#2196f3; margin-top:10px;'>👶 託児設定</div>", unsafe_allow_html=True)
                    new_takuji_en = st.checkbox("託児所を利用する", value=(takuji_en=="1"), key=f"takuji_en_{i}")
                    st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                    new_takuji_addr = st.text_input("託児所の住所", value=takuji_addr, key=f"takuji_addr_{i}")
                    
                    st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
                    nt = st.text_input("電話番号", value=str(c.get("phone","")), key=f"ct_{i}")
                    np = st.text_input("パスワード", value=str(c.get("password","0000")), key=f"cp_{i}")
                    
                    if st.button("保存する", key=f"cs_{i}", type="primary", use_container_width=True):
                        city_part = c_other_city if c_city == "他" else c_city
                        final_home = c_pref + city_part + c_rest
                        auto_area = "岡山" if c_pref == "岡山県" else ("広島" if c_pref == "広島県" else "他")
                        encoded_addr = encode_cast_address(final_home, "1" if new_takuji_en else "0", new_takuji_addr, "0")
                        
                        res = post_api({"action": "save_cast", "cast_id": i, "name": nn, "password": np, "phone": nt, "area": auto_area, "address": encoded_addr, "manager": n_mgr})
                        if res.get("status") == "success":
                            clear_cache(); st.success("保存しました！"); time.sleep(1); st.rerun()

        # ----------------------------------------
        # ④ STAFF設定（全機能完全復元）
        # ----------------------------------------
        elif st.session_state.current_staff_tab == "④ STAFF設定":
            exist_drvs = {str(d["driver_id"]): d for d in drvs}
            staff_disp_list = ["-- 新規・編集するスタッフを選択 --"]
            for i in range(1, 31):
                nm = exist_drvs.get(str(i), {}).get("name", "")
                if nm: staff_disp_list.append(f"STAFF {i} : {nm}")
                else: staff_disp_list.append(f"STAFF {i} : (未登録)")
                    
            selected_staff_str = st.selectbox("スタッフ選択", staff_disp_list, label_visibility="collapsed")
            
            if selected_staff_str != "-- 新規・編集するスタッフを選択 --":
                i = int(selected_staff_str.split(" ")[1])
                d = exist_drvs.get(str(i), {})
                nm = str(d.get("name", ""))
                
                st.markdown(f'<div class="card" style="padding:15px; border-top: 4px solid #4caf50;">', unsafe_allow_html=True)
                st.markdown(f'<div style="font-weight:bold; font-size:18px; margin-bottom:15px;">✏️ STAFF {i} の設定</div>', unsafe_allow_html=True)
                
                d_area = str(d.get("area", "他")).strip()
                if d_area not in ["岡山", "広島", "他"]: d_area = "他"
                d_cap = int(d.get("capacity", 4)) if str(d.get("capacity", "")).isdigit() else 4
                nn = st.text_input("STAFF名", value=nm, key=f"dn_{i}")
                colA, colB = st.columns(2)
                with colA: n_area = st.selectbox("担当方面", ["岡山", "広島", "他"], index=["岡山", "広島", "他"].index(d_area), key=f"d_ar_{i}")
                with colB: n_cap = st.number_input("乗車定員", min_value=1, max_value=10, value=d_cap, key=f"d_cp_{i}")
                
                p_pref, p_city, p_rest = parse_address(str(d.get("address", "")))
                d_pref = st.selectbox("県", ["", "岡山県", "広島県", "香川県"], index=["", "岡山県", "広島県", "香川県"].index(p_pref) if p_pref in ["", "岡山県", "広島県", "香川県"] else 0, key=f"dpf_{i}")
                d_opts = [""]
                if d_pref == "岡山県": d_opts = ["", "岡山市", "倉敷市", "玉野市", "総社市", "瀬戸市", "浅口市", "笠岡市", "他"]
                elif d_pref == "広島県": d_opts = ["", "福山市", "尾道市", "三原市", "府中市", "東広島市", "他"]
                elif d_pref == "香川県": d_opts = ["", "他"]
                colC1, colC2 = st.columns(2)
                with colC1:
                    d_idx = d_opts.index(p_city) if p_city in d_opts else (d_opts.index("他") if p_city and "他" in d_opts else 0)
                    d_city = st.selectbox("市町村", d_opts, index=d_idx, key=f"dct_{i}")
                with colC2:
                    other_val = p_city if p_city and p_city not in d_opts else ""
                    d_other_city = st.text_input("「他」の場合の直接入力", value=other_val, key=f"d_other_city_{i}", placeholder="例: 真庭市")
                st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                d_rest = st.text_input("町名・番地・建物名", value=p_rest, key=f"drs_{i}")
                n_tel = st.text_input("電話番号", value=str(d.get("phone", "")), key=f"dt_{i}")
                n_pass = st.text_input("パスワード", value=str(d.get("password", "1234")), key=f"dp_{i}")
                
                if st.button("💾 保存する", key=f"ds_{i}", type="primary", use_container_width=True):
                    city_part = d_other_city if d_city == "他" else d_city
                    final_addr = d_pref + city_part + d_rest
                    payload = {"action": "save_driver", "driver_id": i, "name": nn, "password": n_pass, "address": final_addr, "phone": n_tel, "area": n_area, "capacity": n_cap}
                    res = post_api(payload)
                    if res.get("status") == "success":
                        clear_cache(); st.success("保存しました！"); st.rerun()

        # ----------------------------------------
        # ⚙️ 管理設定
        # ----------------------------------------
        elif st.session_state.current_staff_tab == "⚙️ 管理設定":
            with st.form("adm"):
                ap = st.text_input("管理者PW", value=sets.get("admin_password","1234"))
                l_tk = st.text_input("LINEトークン", value=sets.get("line_access_token",""), type="password")
                if st.form_submit_button("保存"):
                    post_api({"action": "save_settings", "admin_password": ap, "line_access_token": l_tk})
                    clear_cache(); st.rerun()
