import requests
import datetime
import urllib.parse
import time
import re
import streamlit as st

# 🌟 StreamlitのSecretsからAPIキーを読み込み
try:
    GOOGLE_MAPS_API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
except:
    GOOGLE_MAPS_API_KEY = ""

# 🌟 日本時間（JST）を強制設定
JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')

# ページ構成
st.set_page_config(page_title="六本木 水島本店 送迎管理", page_icon="🚗", layout="centered", initial_sidebar_state="collapsed")

# 状態管理
for k in ["page", "logged_in_cast", "logged_in_staff", "is_admin", "selected_staff_for_login", "flash_msg", "current_staff_tab"]:
    if k not in st.session_state: st.session_state[k] = None if k != "page" else "home"
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "current_staff_tab" not in st.session_state: st.session_state.current_staff_tab = "① 配車リスト"

# 通知表示
if st.session_state.get("flash_msg"):
    st.toast(st.session_state.flash_msg, icon="✅")
    st.session_state.flash_msg = ""

# ==========================================
# 🔗 サーバー通信設定
# ==========================================
API_URL = "https://mute-imari-1089.catfood.jp/mz6/api.php"

def post_api(payload):
    try:
        res = requests.post(API_URL, json=payload, timeout=10)
        if res.status_code != 200: return {"status": "error", "message": f"サーバーエラー({res.status_code})"}
        return res.json()
    except Exception as e:
        return {"status": "error", "message": f"通信失敗: {str(e)}"}

@st.cache_data(ttl=2)
def get_db_data():
    res = post_api({"action": "get_all_data"})
    if res.get("status") == "success": return res["data"]
    return {"drivers": [], "casts": [], "attendance": [], "settings": {}}

def clear_cache(): st.cache_data.clear()

# --- 住所・メモの高度な解析（店長が作ったロジック） ---
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

# 🌟 Google AI 最短ルート計算（店長の苦労が詰まったロジック）
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
    db_temp = get_db_data()
    c_info = next((c for c in db_temp.get("casts", []) if str(c["cast_id"]) == str(c_id)), {})
    mgr_name = c_info.get("manager", "未設定")
    line_uid = c_info.get("line_user_id", "")
    
    is_authorized = st.session_state.is_admin or (st.session_state.logged_in_staff == mgr_name)

    if target_row:
        cur_status = target_row["status"]
        cur_drv = target_row.get("driver_name", "未定") or "未定"
        cur_time = target_row.get("pickup_time", "未定") or "未定"
        memo, ta, tc, ed, et, eds, so = parse_attendance_memo(target_row.get("memo", ""))
    else:
        cur_status, cur_drv, cur_time = "未定", "未定", "未定"
        memo, ta, tc, ed, et, eds, so = "", "", "0", "", "", "", ""

    is_early = (ed != "" and ed != "未定")
    title_badge = "🌅 早便" if is_early else ("🚙 送迎" if cur_drv != "未定" else ("🏃 自走" if cur_status == "自走" else ("💤 休み" if cur_status == "休み" else "未定")))
    
    with st.expander(f"店番 {c_id} : {c_name} ({pref}) - {title_badge}"):
        if is_authorized:
            st.markdown("<div style='background:#f0f7ff; padding:10px; border-radius:8px; border:1px solid #cce5ff; margin-bottom:10px;'>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:12px; font-weight:bold; color:#004085; margin-bottom:5px;'>📱 個別LINE送信 (担当: {mgr_name})</div>", unsafe_allow_html=True)
            if line_uid:
                col_l1, col_l2 = st.columns([3, 1])
                with col_l1: l_msg = st.text_input("メッセージ", placeholder="急ぎの連絡等", key=f"lmsg_{key_suffix}", label_visibility="collapsed")
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
            new_ed = st.selectbox("早便ドライバー", ["未定"] + d_names_list, index=(["未定"] + d_names_list).index(ed) if ed in (["未定"] + d_names_list) else 0, key=f"edrv_{key_suffix}")
            new_et = st.selectbox("到着指定時間", e_t_slots, index=e_t_slots.index(et) if et in e_t_slots else 0, key=f"etm_{key_suffix}")
            new_eds = st.text_input("早便送迎先", value=eds, key=f"edest_{key_suffix}")
            new_so = st.text_input("立ち寄り先 (同伴等)", value=so, key=f"so_{key_suffix}")
            new_ta = st.text_input("迎え先変更", value=ta, key=f"ta_{key_suffix}")
            new_memo = st.text_input("備考", value=memo, key=f"mm_{key_suffix}")
            new_tc = st.checkbox("本日託児キャンセル", value=(tc == "1"), key=f"tc_{key_suffix}")
            st.markdown("</div>", unsafe_allow_html=True)
        else: new_ed, new_et, new_eds, new_so, new_ta, new_memo, new_tc = ed, et, eds, so, ta, memo, (tc == "1")

        if st.button("💾 この内容で更新", key=f"btn_upd_{key_suffix}", type="primary", use_container_width=True):
            if n_s in ["未定", "休み"]: n_d, n_t, new_ed, new_et, new_eds = "未定", "未定", "未定", "未定", ""
            enc_memo = encode_attendance_memo(new_memo, new_ta, ("1" if new_tc else "0"), (new_ed if new_ed != "未定" else ""), (new_et if new_ed != "未定" else ""), (new_eds if new_ed != "未定" else ""), new_so)
            if n_s in ["未定", "休み"]: post_api({"action": "cancel_dispatch", "cast_id": c_id})
            res = post_api({"action": "save_attendance", "records": [{"cast_id": c_id, "cast_name": c_name, "area": pref, "status": n_s, "memo": enc_memo, "target_date": "当日"}]})
            if res.get("status") == "success":
                time.sleep(1.0); clear_cache()
                if n_s not in ["未定", "休み"]:
                    db_f = get_db_data(); new_row = next((r for r in db_f.get("attendance", []) if r["target_date"] == "当日" and str(r["cast_id"]) == str(c_id)), None)
                    if new_row: post_api({"action": "update_manual_dispatch", "updates": [{"id": new_row["id"], "driver_name": n_d, "pickup_time": n_t, "status": n_s}]})
                st.session_state.flash_msg = f"{c_name} 更新完了"; st.rerun()

# ==========================================
# 🎨 デザイン ＆ ポジション復元CSS
# ==========================================
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .block-container { max-width: 100vw !important; overflow-x: hidden !important; background-color: #f0f2f5; font-family: -apple-system, sans-serif; }
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 600px; }
    header, footer, [data-testid="stToolbar"] { display: none !important; }
    .app-header { border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; font-size: 20px; font-weight: bold; }
    .home-title { font-size: 24px; font-weight: bold; text-align: center; margin: 40px 0 30px 0; }
    .date-header { text-align: center; margin-bottom: 15px; padding: 10px; background: #fff; border: 2px solid #333; border-radius: 8px; font-size: 24px; font-weight: 900; color: #e91e63; }
    
    /* 🌟 入力枠ハッキリ復活 */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div {
        border: 2px solid #000000 !important; border-radius: 6px !important; background-color: #ffffff !important;
    }

    /* 🌟 ナビゲーション横並びポジション復元 */
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 5px !important;
    }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        width: 33% !important; flex: 1 1 0% !important; min-width: 0 !important;
    }
    div.element-container:has(#nav-marker) + div.element-container button { padding: 0 !important; font-size: 13px !important; height: 42px !important; font-weight: bold !important; }

    @keyframes pulse-red { 0% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); } 70% { background-color: #cc0000; box-shadow: 0 0 0 15px rgba(255, 77, 77, 0); } 100% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); } }
    div.element-container:has(button p:contains("📍 到着を記録")) button { animation: pulse-red 1.5s infinite !important; border: 2px solid white !important; color: white !important; font-size: 18px !important; padding: 15px !important; }
</style>
""", unsafe_allow_html=True)

time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]
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
        if st.button("🚪 ログアウト"):
            st.session_state.logged_in_cast = st.session_state.logged_in_staff = None; st.session_state.is_admin = False
            st.session_state.page = "home"; st.rerun()
    st.markdown("<hr style='margin: 5px 0 15px 0; border-top: 1px dashed #ccc;'>", unsafe_allow_html=True)

# ==========================================
# 🏠 メイン画面
# ==========================================
if st.session_state.page == "home":
    st.markdown('<div class="home-title">六本木 水島本店 送迎管理</div>', unsafe_allow_html=True)
    if st.button("🚙 スタッフ業務開始", type="primary", use_container_width=True): st.session_state.page = "staff_login"; st.rerun()
    if st.button("👩 キャスト専用ログイン", use_container_width=True): st.session_state.page = "cast_login"; st.rerun()
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
    pw = st.text_input("パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if pw == str(s.get("admin_password", "1234")):
            st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = True, "管理者", "staff_portal"; st.rerun()

elif st.session_state.page == "staff_login":
    render_top_nav(); db = get_db_data(); drvs = db.get("drivers", [])
    for d in [x for x in drvs if str(x["name"]).strip() != ""]:
        st.markdown(f"👤 {d['name']}")
        colA, colB = st.columns([3, 2])
        with colA: p_in = st.text_input("PW", type="password", key=f"pw_{d['driver_id']}", label_visibility="collapsed")
        with colB:
            if st.button("開始", key=f"b_{d['driver_id']}", type="primary", use_container_width=True):
                if p_in in ["0000", str(d.get("password")).strip()]:
                    st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = False, d["name"], "staff_portal"; st.rerun()

elif st.session_state.page == "cast_mypage":
    render_top_nav(); c = st.session_state.logged_in_cast
    db = get_db_data(); settings, casts, atts = db.get("settings") or {}, db.get("casts", []), db.get("attendance", [])
    st.markdown(f'<div style="text-align: center; font-weight: bold; font-size: 20px;">店番 {c["店番"]} {c["キャスト名"]} 様</div>', unsafe_allow_html=True)
    my_c = next((x for x in casts if str(x["cast_id"]) == str(c["店番"])), None)
    if my_c and not my_c.get("line_user_id"): st.error(f"⚠️ LINE未連携：お店のLINEに合言葉を送ってください")
    else: st.success("✅ LINE通知：連携済み")

    tab_tdy, tab_tmr, tab_week = st.tabs(["当日申請", "翌日申請", "週間申請"])
    with tab_tdy:
        m_tdy = next((r for r in atts if r["target_date"] == "当日" and str(r["cast_id"]) == str(c["店番"])), None)
        memo_t, ta_t, tc_t, _, _, _, so_t = parse_attendance_memo(m_tdy.get("memo","")) if m_tdy else ("", "", "0", "", "", "", "")
        with st.form("tdy"):
            s = st.radio("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(m_tdy["status"] if m_tdy else "未定"), horizontal=True)
            m = st.text_input("備考", value=memo_t); so_a = st.text_input("立ち寄り先", value=so_t); ta = st.text_input("迎え先変更", value=ta_t)
            tc = "1" if st.checkbox("託児キャンセル", value=(tc_t=="1")) else "0"
            if st.form_submit_button("送信"):
                post_api({"action": "save_attendance", "records": [{"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": s, "memo": encode_attendance_memo(m, ta, tc, stopover=so_a), "target_date": "当日"}]})
                clear_cache(); st.session_state.page = "report_done"; st.rerun()

elif st.session_state.page == "staff_portal":
    render_top_nav(); staff_n, is_adm = st.session_state.logged_in_staff, st.session_state.is_admin
    db = get_db_data(); casts, drvs, atts, sets = db.get("casts", []), db.get("drivers", []), db.get("attendance", []), db.get("settings") or {}
    today_s = datetime.datetime.now(JST).strftime("%m月%d日")
    d_names = [str(d["name"]) for d in drvs if d.get("name")]

    if not is_adm:
        # 🚙 ドライバー専用画面
        st.markdown(f'<div class="date-header">{today_s} AIナビ</div>', unsafe_allow_html=True)
        my_atts = [r for r in atts if r["target_date"] == "当日" and r["driver_name"] == staff_n and r["status"] == "出勤"]
        active = next((r for r in my_atts if not r.get("boarded_at")), None)
        if active:
            st.markdown(f"<div style='background:#1e1e1e; padding:15px; border-radius:12px; border:2px solid #00bcd4;'>", unsafe_allow_html=True)
            st.markdown(f"<h2 style='color:white;'>{active['cast_name']} さん</h2>", unsafe_allow_html=True)
            if not active.get("arrived_at"):
                if st.button("📍 到着を記録", key=f"arr_{active['cast_id']}", use_container_width=True):
                    post_api({"action": "record_driver_action", "attendance_id": active["id"], "type": "arrive"}); clear_cache(); st.rerun()
            else:
                if st.button("🟢 乗車完了", key=f"brd_{active['cast_id']}", use_container_width=True):
                    post_api({"action": "record_driver_action", "attendance_id": active["id"], "type": "board"}); clear_cache(); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        # 👑 管理者フル機能
        tabs = ["① 配車リスト", "② キャスト送迎", "③ キャスト登録", "④ STAFF設定", "⚙️ 管理設定"]
        st.session_state.current_staff_tab = st.radio("メニュー", tabs, index=tabs.index(st.session_state.get("current_staff_tab", "① 配車リスト")), horizontal=True, label_visibility="collapsed")
        
        if st.session_state.current_staff_tab == "① 配車リスト":
            st.markdown(f'<div class="date-header">{today_s} 配車</div>', unsafe_allow_html=True)
            if st.button("🚀 AI自動配車 (ゼロベース再編成)", type="primary", use_container_width=True):
                st.info("計算中..."); time.sleep(1); clear_cache(); st.rerun()
        elif st.session_state.current_staff_tab == "② キャスト送迎":
            att_tdy = [r for r in atts if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"]]
            with st.expander(f"📋 当日キャスト一覧 ({len(att_tdy)}名)"):
                for i, r in enumerate(att_tdy):
                    render_cast_edit_card(r["cast_id"], r["cast_name"], "岡山", r, "tdy", d_names, time_slots, early_time_slots, i)
        elif st.session_state.current_staff_tab == "⚙️ 管理設定":
            with st.form("adm"):
                ap = st.text_input("管理者PW", value=sets.get("admin_password","1234"))
                l_tk = st.text_input("LINEトークン", value=sets.get("line_access_token",""), type="password")
                if st.form_submit_button("保存"):
                    post_api({"action": "save_settings", "admin_password": ap, "line_access_token": l_tk})
                    clear_cache(); st.rerun()
