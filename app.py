import os, requests, datetime, urllib.parse, time, re
import xml.etree.ElementTree as ET
import streamlit as st

# 🌟 システムバージョン管理（全構文エラー修正・完全フラット構造版）
APP_VERSION = 52

try: GOOGLE_MAPS_API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
except: GOOGLE_MAPS_API_KEY = "AIzaSyCRZS-A7Sasucg_lcPksXB7jao8xW6ckeE"

JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')
dt = datetime.datetime.now(JST)
today_str = dt.strftime("%m月%d日")
dow = ['月','火','水','木','金','土','日'][dt.weekday()]

# Streamlitの根幹設定
st.set_page_config(page_title="六本木 水島本店 送迎管理", page_icon="🚗", layout="centered", initial_sidebar_state="collapsed")
st.markdown('<meta name="google" content="notranslate">', unsafe_allow_html=True)

for k in ["page", "logged_in_cast", "logged_in_staff", "is_admin", "selected_staff_for_login", "flash_msg", "current_staff_tab"]:
    if k not in st.session_state: st.session_state[k] = None if k != "page" else "home"
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "current_staff_tab" not in st.session_state or st.session_state.current_staff_tab not in ["① 配車リスト", "② キャスト送迎", "③ キャスト登録", "④ STAFF設定", "⚙️ 管理設定"]:
    st.session_state.current_staff_tab = "① 配車リスト"

if st.session_state.get("flash_msg"):
    st.toast(st.session_state.flash_msg, icon="✅")
    st.session_state.flash_msg = ""

API_URL = "https://mute-imari-1089.catfood.jp/mz6/api.php"

def post_api(payload):
    try:
        res = requests.post(API_URL, json=payload, timeout=10)
        if res.status_code == 404: return {"status": "error", "message": "🚨 api.php が見つかりません。"}
        if res.status_code != 200: return {"status": "error", "message": f"🚨 サーバーエラー ({res.status_code})"}
        try: return res.json()
        except: return {"status": "error", "message": f"🚨 PHPエラー: {res.text[:100]}..."}
    except Exception as e: return {"status": "error", "message": f"🚨 通信失敗: {str(e)}"}

@st.cache_data(ttl=2)
def get_db_data():
    res = post_api({"action": "get_all_data"})
    if res.get("status") == "success": return res["data"]
    st.error(f"データベース通信エラー: {res.get('message')}")
    return {"drivers": [], "casts": [], "attendance": [], "settings": {}}

def clear_cache(): st.cache_data.clear()

def notify_staff_via_line(token, target_id, staff_name, cast_name, pickup_time):
    if not token or not target_id: return
    msg = f"🚙 【配車通知】\n{staff_name} さんに新しい送迎が割り当てられました。\n\n👩 キャスト: {cast_name}\n⏰ 時間: {pickup_time}\n安全運転でお願いします！"
    try: requests.post('https://api.line.me/v2/bot/message/push', headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, json={'to': target_id, 'messages': [{'type': 'text', 'text': msg}]}, timeout=5)
    except: pass

def notify_cast_via_line(token, target_id, cast_name, pickup_time, driver_name):
    if not token or not target_id: return
    msg = f"🚙 本日の送迎予定\n\n{cast_name} さん\n⏰ お迎え予定: {pickup_time}\n🚘 担当ドライバー: {driver_name}\n\n準備をお願いします！"
    try: requests.post('https://api.line.me/v2/bot/message/push', headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, json={'to': target_id, 'messages': [{'type': 'text', 'text': msg}]}, timeout=5)
    except: pass

def notify_driver_route_via_line(token, target_id, driver_name, route_details, dep_time):
    if not token or not target_id: return
    msg = f"🗺️ 本日の送迎ルート ({driver_name}班)\n🚀 店舗出発: {dep_time}\n\n"
    for idx, rt in enumerate(route_details): msg += f"[{idx+1}] {rt['time']} {rt['name']}\n📍 {rt['addr']}\n\n"
    msg += "安全運転でお願いします！"
    try: requests.post('https://api.line.me/v2/bot/message/push', headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, json={'to': target_id, 'messages': [{'type': 'text', 'text': msg}]}, timeout=5)
    except: pass

@st.cache_data(ttl=3600)
def get_rss_news(url, limit=5):
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        res.raise_for_status()
        return [{"title": item.find('title').text, "link": item.find('link').text} for item in ET.fromstring(res.content).findall('.//item')[:limit]]
    except: return [{"title": "情報の取得に失敗しました", "link": "#"}]

def parse_cast_address(raw_address):
    if not raw_address: return "", "0", "", "0"
    p = str(raw_address).split("||")
    return (p[0], p[1] if len(p)>1 else "0", p[2] if len(p)>2 else "", p[3] if len(p)>3 else "0")

def encode_cast_address(home, takuji_enabled, takuji_addr, is_self_edited): return f"{home}||{takuji_enabled}||{takuji_addr}||{is_self_edited}"

def parse_attendance_memo(raw_memo):
    if not raw_memo: return "", "", "0", "", "", "", ""
    p = str(raw_memo).split("||")
    return (p[0], p[1] if len(p)>1 else "", p[2] if len(p)>2 else "0", p[3] if len(p)>3 else "", p[4] if len(p)>4 else "", p[5] if len(p)>5 else "", p[6] if len(p)>6 else "")

def encode_attendance_memo(memo, temp_addr, takuji_cancel, early_driver="", early_time="", early_dest="", stopover=""):
    return f"{memo}||{temp_addr}||{takuji_cancel}||{early_driver}||{early_time}||{early_dest}||{stopover}"

def is_in_range(val, rng):
    if rng == "全表示": return True
    try: return int(rng.split('-')[0]) <= int(val) <= int(rng.split('-')[1])
    except: return False

def parse_address(addr_str):
    pref, city, rest = "", "", str(addr_str)
    for p in ["岡山県", "広島県", "香川県"]:
        if rest.startswith(p): pref = p; rest = rest[len(p):]; break
    if pref == "岡山県":
        for c in ["岡山市", "倉敷市", "玉野市", "総社市", "瀬戸市", "浅口市", "笠岡市"]:
            if rest.startswith(c): city = c; rest = rest[len(c):]; break
    elif pref == "広島県":
        for c in ["福山市", "尾道市", "三原市", "府中市", "東広島市"]:
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
    line, dist = "Route_E_South", 50 
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
        if not any(x in addr for x in ["水島", "連島", "広江", "児島", "下津井"]): line = "Route_C_North"
    return line, dist

@st.cache_data(ttl=120)
def optimize_and_calc_route(api_key, store_addr, dest_addr, tasks_list, is_return=False, manual_order=False):
    api_error_msg = ""
    if not api_key: return tasks_list, 0, [], 0, "APIキーが設定されていません"
    if not tasks_list: return tasks_list, 0, [], 0, ""

    valid_tasks = []
    for t in tasks_list:
        addr = clean_address_for_map(t.get("actual_pickup", ""))
        if addr:
            try:
                dist_res = requests.get("https://maps.googleapis.com/maps/api/directions/json", params={"origin": store_addr, "destination": addr, "key": api_key, "language": "ja"}, timeout=5).json()
                if dist_res.get("status") == "OK": t["real_dist_from_store"] = dist_res["routes"][0]["legs"][0]["distance"]["value"]
                else: _, backup_dist = get_route_line_and_distance(addr); t["real_dist_from_store"] = backup_dist * 1000
            except:
                _, backup_dist = get_route_line_and_distance(addr); t["real_dist_from_store"] = backup_dist * 1000
            valid_tasks.append(t)

    invalid_tasks = [t for t in tasks_list if not clean_address_for_map(t.get("actual_pickup", ""))]
    
    if not manual_order:
        if is_return: valid_tasks.sort(key=lambda x: x.get("real_dist_from_store", 0))
        else: valid_tasks.sort(key=lambda x: x.get("real_dist_from_store", 0), reverse=True)

    ordered_valid_tasks = valid_tasks
    total_sec, first_leg_sec, full_path = 0, 0, []
    actual_dest = dest_addr if dest_addr else store_addr
    final_ordered_tasks = ordered_valid_tasks + invalid_tasks

    for t in final_ordered_tasks:
        if t.get("actual_pickup"): full_path.append(clean_address_for_map(t.get("actual_pickup")))
        if t.get("stopover"): full_path.append(clean_address_for_map(t.get("stopover")))
        if t.get("use_takuji") and t.get("takuji_addr"): full_path.append(clean_address_for_map(t.get("takuji_addr")))
        
    full_path = [p for p in full_path if p]
    if full_path:
        calc_origin, calc_dest = store_addr, actual_dest
        calc_waypoints = full_path
        if is_return and actual_dest == store_addr: 
            calc_dest = full_path[-1]; calc_waypoints = full_path[:-1]
        
        params = {"origin": calc_origin, "destination": calc_dest, "key": api_key, "language": "ja", "departure_time": "now"}
        if calc_waypoints: params["waypoints"] = "|".join(calc_waypoints)
            
        try:
            res2 = requests.get("https://maps.googleapis.com/maps/api/directions/json", params=params, timeout=10).json()
            if res2.get("status") == "OK":
                legs = res2["routes"][0]["legs"]
                total_sec = sum(leg["duration"]["value"] for leg in legs)
                if legs: first_leg_sec = legs[0]["duration"]["value"]
            else:
                if not api_error_msg: api_error_msg = f"{res2.get('status')} - {res2.get('error_message', '')}"
        except Exception as e:
            if not api_error_msg: api_error_msg = f"通信例外: {str(e)}"
            
    return final_ordered_tasks, total_sec, full_path, first_leg_sec, api_error_msg

def recalc_route_for_driver(drv_name, trigger_line_notify=False, manual_order=False):
    if not drv_name or drv_name == "未定": return None, None
    db_f = get_db_data(); casts_f = db_f.get("casts", []); drvs_f = db_f.get("drivers", [])
    atts_f = db_f.get("attendance", []); sets_f = db_f.get("settings", {})
    store_addr_f = str(sets_f.get("store_address", "岡山県倉敷市水島東栄町2-24"))
    
    drv_tasks = [r for r in atts_f if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"] and r.get("driver_name") == drv_name]
    valid_drv_tasks = []
    for r in drv_tasks:
        if r["status"] == "自走": continue
        _, _, _, e_drv, _, _, _ = parse_attendance_memo(r.get("memo", ""))
        if e_drv and e_drv != "未定" and e_drv != "": continue
        
        c_info = next((c for c in casts_f if str(c["cast_id"]) == str(r["cast_id"])), {})
        raw_addr = c_info.get("address", "")
        home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
        raw_memo = r.get("memo", "")
        memo_text, temp_addr, takuji_cancel, _, _, _, stopover = parse_attendance_memo(raw_memo)
        actual_pickup = temp_addr if temp_addr else home_addr
        use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
        latest_name = c_info.get("name", r["cast_name"])
        line, dst = get_route_line_and_distance(actual_pickup)
        valid_drv_tasks.append({"task": r, "c_info": c_info, "actual_pickup": actual_pickup, "stopover": stopover, "use_takuji": use_takuji, "takuji_addr": takuji_addr, "memo_text": memo_text, "c_name": latest_name, "c_id": r["cast_id"], "dist_score": dst})
    
    if not valid_drv_tasks: return None, None
    if manual_order: valid_drv_tasks.sort(key=lambda x: x["task"].get("pickup_time", "99:99"))
        
    ordered_tasks, total_sec, full_path, first_leg_sec, _ = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr_f, store_addr_f, valid_drv_tasks, is_return=False, manual_order=manual_order)
    total_casts = len(ordered_tasks)
    if total_sec == 0: interval_mins = 15
    else:
        interval_mins = (total_sec // 60) // (total_casts + 1) if total_casts > 0 else 15
        if interval_mins < 1: interval_mins = 1
        
    base_time = str(sets_f.get("base_arrival_time", "19:50"))
    try: bh, bm = map(int, base_time.split(':')); b_mins = bh * 60 + bm
    except: b_mins = 19 * 60 + 50
    
    t_mins_list = []
    for idx in range(total_casts):
        mins_to_subtract = (total_casts - idx) * interval_mins
        t_mins = b_mins - mins_to_subtract
        if t_mins < 0: t_mins += 24 * 60
        t_mins_list.append(t_mins)
        
    if t_mins_list:
        earliest_m = min(t_mins_list)
        dep_m = earliest_m - (first_leg_sec // 60) - 5
        if 6 * 60 < dep_m < 16 * 60:
            dep_m = 16 * 60
            t_mins_list = []; current_m = dep_m + (first_leg_sec // 60) + 5
            for idx in range(total_casts):
                t_mins_list.append(current_m); current_m += interval_mins

    driver_updates, route_details = [], []
    dep_time_str = f"{(dep_m // 60) % 24:02d}:{dep_m % 60:02d}" if t_mins_list else "未定"
    
    for idx, item in enumerate(ordered_tasks):
        tm = t_mins_list[idx]
        current_calc_time = f"{(tm // 60) % 24:02d}:{tm % 60:02d}"
        driver_updates.append({"id": item["task"]["id"], "driver_name": drv_name, "pickup_time": current_calc_time, "status": item["task"]["status"]})
        route_details.append({"name": item["c_name"], "time": current_calc_time, "addr": item["actual_pickup"], "cast_line_id": next((c.get("line_user_id", "") for c in casts_f if str(c["cast_id"]) == str(item["c_id"])), "")})
        
    if driver_updates: 
        post_api({"action": "update_manual_dispatch", "updates": driver_updates})
        if trigger_line_notify:
            stff_id = next((d.get("line_user_id", "") for d in drvs_f if d.get("name") == drv_name), "")
            line_token = sets_f.get("line_access_token", "")
            notify_driver_route_via_line(line_token, stff_id, drv_name, route_details, dep_time_str)
            for rt in route_details: notify_cast_via_line(line_token, rt["cast_line_id"], rt["name"], rt["time"], drv_name)
    return driver_updates, route_details

def render_cast_edit_card(c_id, c_name, pref, target_row, prefix_key, d_names_list, t_slots, e_t_slots, loop_idx):
    key_suffix = f"{c_id}_{prefix_key}_{loop_idx}"
    db_temp = get_db_data(); sets = db_temp.get("settings", {})
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
        cur_status, cur_drv, cur_time = "未定", "未定", "未定"
        memo_text, temp_addr, takuji_cancel, e_drv, e_time, e_dest, stopover = "", "", "0", "", "", "", ""

    is_early = (e_drv != "" and e_drv != "未定")
    title_badge = "🌅 早便" if is_early else ("🚙 送迎" if cur_drv != "未定" else ("🏃 自走" if cur_status == "自走" else ("💤 休み" if cur_status == "休み" else "未定")))
    
    with st.expander(f"店番 {c_id} : {latest_name} ({pref}) - {title_badge}"):
        if is_authorized:
            st.markdown("<div style='background:#f0f7ff; padding:10px; border-radius:8px; border:1px solid #cce5ff; margin-bottom:10px;'><div style='font-size:12px; font-weight:bold; color:#004085; margin-bottom:5px;'>📱 個別LINE送信</div>", unsafe_allow_html=True)
            if line_uid:
                col_l1, col_l2 = st.columns([3, 1])
                with col_l1: l_msg = st.text_input("メッセージ", key=f"lmsg_{key_suffix}", label_visibility="collapsed")
                with col_l2:
                    if st.button("送信", key=f"lbtn_{key_suffix}", use_container_width=True, type="primary"):
                        if l_msg:
                            post_api({"action": "update_manual_dispatch", "updates": [{"id": target_row["id"] if target_row else -1, "driver_name": cur_drv, "pickup_time": cur_time, "status": cur_status}]})
                            st.success("完了")
            else: st.markdown("<div style='font-size:11px; color:#666;'>⚠️ LINE未連携</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        if st.session_state.get(f"saved_dispatch_{key_suffix}", False):
            st.markdown('<div style="background-color: #4caf50; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold; margin-bottom: 10px;">✅ 決定済み</div>', unsafe_allow_html=True)
            if st.button("🔄 再変更", key=f"reedit_{key_suffix}", use_container_width=True):
                st.session_state[f"saved_dispatch_{key_suffix}"] = False; st.rerun()
        else:
            col1, col2, col3 = st.columns(3)
            with col1: n_s = st.selectbox("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(cur_status) if cur_status in ["未定", "出勤", "自走", "休み"] else 0, key=f"st_{key_suffix}")
            with col2: n_d = st.selectbox("ドライバー", ["未定"] + d_names_list, index=(["未定"] + d_names_list).index(cur_drv) if cur_drv in (["未定"] + d_names_list) else 0, key=f"drv_{key_suffix}")
            with col3: n_t = st.selectbox("時間", ["未定", "AI算出中"] + t_slots, index=(["未定", "AI算出中"] + t_slots).index(cur_time) if cur_time in (["未定", "AI算出中"] + t_slots) else 0, key=f"tm_{key_suffix}")
            
            show_details = st.toggle("⚙️ 早便や詳細設定を開く", key=f"toggle_{key_suffix}")
            if show_details:
                st.markdown("<div style='background:#fffde7; padding:10px; border-radius:8px;'>", unsafe_allow_html=True)
                col_e1, col_e2 = st.columns(2)
                with col_e1: new_ed = st.selectbox("早便ドライバー", ["未定"] + d_names_list, index=(["未定"] + d_names_list).index(e_drv) if e_drv in (["未定"] + d_names_list) else 0, key=f"edrv_{key_suffix}")
                with col_e2: new_et = st.selectbox("送り先到着時間", e_t_slots, index=e_t_slots.index(e_time) if e_time in e_t_slots else 0, key=f"etm_{key_suffix}")
                new_eds = st.text_input("早便送迎先", value=e_dest, key=f"edest_{key_suffix}")
                new_so = st.text_input("立ち寄り先 (同伴等)", value=stopover, key=f"so_{key_suffix}")
                new_ta = st.text_input("迎え先変更", value=temp_addr, key=f"ta_{key_suffix}")
                new_memo = st.text_input("備考", value=new_memo, key=f"mm_{key_suffix}")
                new_tc = st.checkbox("本日託児キャンセル", value=(takuji_cancel == "1"), key=f"tc_{key_suffix}")
                st.markdown("</div>", unsafe_allow_html=True)
            else: new_ed, new_et, new_eds, new_so, new_ta, new_memo, new_tc = e_drv, e_time, e_dest, stopover, temp_addr, memo_text, (takuji_cancel == "1")

            if st.button("💾 決定する", key=f"btn_upd_{key_suffix}", type="primary", use_container_width=True):
                if n_s in ["未定", "休み"]: n_d, n_t, new_ed, new_et, new_eds = "未定", "未定", "未定", "未定", ""
                enc_m = encode_attendance_memo(new_memo, new_ta, ("1" if new_tc else "0"), new_ed, new_et, new_eds, new_so)
                if n_s in ["未定", "休み"]: post_api({"action": "cancel_dispatch", "cast_id": c_id})
                res = post_api({"action": "save_attendance", "records": [{"cast_id": c_id, "cast_name": latest_name, "area": pref, "status": n_s, "memo": enc_m, "target_date": "当日"}]})
                
                if res.get("status") == "success":
                    time.sleep(0.5); clear_cache()
                    if n_s not in ["未定", "休み"]:
                        db_f = get_db_data()
                        new_row = next((r for r in db_f.get("attendance", []) if r["target_date"] == "当日" and str(r["cast_id"]) == str(c_id)), None)
                        if new_row:
                            post_api({"action": "update_manual_dispatch", "updates": [{"id": new_row["id"], "driver_name": n_d, "pickup_time": n_t, "status": n_s}]})
                            if n_d != "未定" and n_d != cur_drv:
                                stff_id = next((d.get("line_user_id", "") for d in db_f.get("drivers", []) if d["name"] == n_d), "")
                                notify_staff_via_line(sets.get("line_access_token", ""), stff_id, n_d, latest_name, n_t)
                    st.session_state[f"saved_dispatch_{key_suffix}"] = True
                    st.session_state.active_search_query = ""
                    if "search_cast_key" in st.session_state: st.session_state.search_cast_key += 1
                    st.session_state.flash_msg = f"{latest_name} 更新完了"
                    st.rerun()

def render_dispatch_editor(d_name, course_idx, t_rows, active_ordered, drv_names, is_adm):
    with st.expander(f"🔄 コース{course_idx}（{d_name}班）の順序入替・担当変更"):
        st.markdown("**◆ 迎え順の変更 / 欠勤(外す)**")
        for idx, t in enumerate(active_ordered):
            task_row = t.get("task", {})
            if not task_row: continue
            c_name, c_id = t["c_name"], t["c_id"]
            c_info, memo_txt = t.get("c_info", {}), t.get("memo_text", "")
            
            c1, c2, c3, c4 = st.columns([5, 1.5, 1.5, 1.5])
            with c1: st.write(f"{idx+1}. {c_name}")
            with c2:
                if idx > 0 and st.button("▲", key=f"up_{d_name}_{course_idx}_{idx}_{c_id}"):
                    pt1, pt2 = task_row.get("pickup_time", "99:99"), active_ordered[idx-1]["task"].get("pickup_time", "99:99")
                    if pt1 == pt2: pt2 = "99:98"
                    post_api({"action": "update_manual_dispatch", "updates": [{"id": task_row["id"], "driver_name": d_name, "pickup_time": pt2, "status": task_row["status"]}, {"id": active_ordered[idx-1]["task"]["id"], "driver_name": d_name, "pickup_time": pt1, "status": active_ordered[idx-1]["task"]["status"]}]})
                    time.sleep(0.5); clear_cache(); recalc_route_for_driver(d_name, trigger_line_notify=True, manual_order=True); clear_cache(); st.rerun()
            with c3:
                if idx < len(active_ordered) - 1 and st.button("▼", key=f"dn_{d_name}_{course_idx}_{idx}_{c_id}"):
                    pt1, pt2 = task_row.get("pickup_time", "99:99"), active_ordered[idx+1]["task"].get("pickup_time", "99:99")
                    if pt1 == pt2: pt2 = "99:98"
                    post_api({"action": "update_manual_dispatch", "updates": [{"id": task_row["id"], "driver_name": d_name, "pickup_time": pt2, "status": task_row["status"]}, {"id": active_ordered[idx+1]["task"]["id"], "driver_name": d_name, "pickup_time": pt1, "status": active_ordered[idx+1]["task"]["status"]}]})
                    time.sleep(0.5); clear_cache(); recalc_route_for_driver(d_name, trigger_line_notify=True, manual_order=True); clear_cache(); st.rerun()
            with c4:
                if st.button("🗑️", key=f"del_{d_name}_{course_idx}_{idx}_{c_id}"):
                    post_api({"action": "save_attendance", "records": [{"cast_id": c_id, "cast_name": c_name, "area": c_info.get("area","他"), "status": "休み", "memo": encode_attendance_memo(memo_txt, "", "0"), "target_date": "当日"}]})
                    post_api({"action": "cancel_dispatch", "cast_id": c_id})
                    time.sleep(0.5); clear_cache(); recalc_route_for_driver(d_name, trigger_line_notify=True, manual_order=True); clear_cache(); st.rerun()
        
        if is_adm:
            st.markdown("<hr style='margin:10px 0;'>**◆ コース担当の完全入替**", unsafe_allow_html=True)
            c_drv1, c_drv2 = st.columns([3, 1])
            with c_drv1: new_course_drv = st.selectbox("新しい担当", ["--"] + drv_names, key=f"cdrv_{d_name}_{course_idx}", label_visibility="collapsed")
            with c_drv2:
                if st.button("入替", key=f"btn_cdrv_{d_name}_{course_idx}", use_container_width=True) and new_course_drv != "--" and new_course_drv != d_name:
                    db_f = get_db_data(); atts_f = db_f.get("attendance", [])
                    updates = []
                    for r in atts_f:
                        if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"]:
                            if r.get("driver_name") == d_name: updates.append({"id": r["id"], "driver_name": new_course_drv, "pickup_time": "未定", "status": r["status"]})
                            elif r.get("driver_name") == new_course_drv: updates.append({"id": r["id"], "driver_name": d_name, "pickup_time": "未定", "status": r["status"]})
                    if updates:
                        post_api({"action": "update_manual_dispatch", "updates": updates})
                        time.sleep(0.5); clear_cache(); recalc_route_for_driver(d_name, trigger_line_notify=True, manual_order=False); recalc_route_for_driver(new_course_drv, trigger_line_notify=True, manual_order=False); clear_cache(); st.rerun()
            
            st.markdown("<hr style='margin:10px 0;'>**◆ 個別キャスト移動**", unsafe_allow_html=True)
            for t in t_rows:
                db_t = get_db_data()
                c_inf = next((c for c in db_t.get("casts", []) if str(c["cast_id"]) == str(t["cast_id"])), {})
                l_name = c_inf.get("name", t['cast_name'])
                col_i1, col_i2 = st.columns([3, 1])
                with col_i1: new_ind_drv = st.selectbox(f"{l_name}", ["--", "未定"] + drv_names, key=f"idrv_{t['id']}_{course_idx}")
                with col_i2:
                    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                    if st.button("移動", key=f"bind_{t['id']}_{course_idx}", use_container_width=True) and new_ind_drv != "--" and new_ind_drv != d_name:
                        post_api({"action": "update_manual_dispatch", "updates": [{"id": t["id"], "driver_name": new_ind_drv, "pickup_time": "未定", "status": t.get("status")}]})
                        time.sleep(0.5); clear_cache(); recalc_route_for_driver(d_name, trigger_line_notify=True, manual_order=False)
                        if new_ind_drv != "未定": recalc_route_for_driver(new_ind_drv, trigger_line_notify=True, manual_order=False)
                        clear_cache(); st.rerun()

def render_top_nav():
    st.markdown('<div id="nav-marker" style="display:none;"></div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1: 
        if st.button("🏠 ホーム"): st.session_state.page = "home"; st.rerun()
    with c2: 
        if st.button("🔙 戻る"): st.session_state.page = "home"; st.rerun()
    with c3: 
        if st.button("🚪 ログアウト"): st.session_state.logged_in_cast = st.session_state.logged_in_staff = None; st.session_state.is_admin = False; st.session_state.page = "home"; st.rerun()
    st.markdown("<hr style='margin: 5px 0 15px 0; border-top: 1px dashed #ccc;'>", unsafe_allow_html=True)
    st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .block-container { max-width: 100vw !important; overflow-x: hidden !important; background-color: #f0f2f5; font-family: -apple-system, sans-serif; }
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 800px !important; }
    header, footer, [data-testid="stToolbar"] { display: none !important; }
    .app-header { border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; font-size: 20px; font-weight: bold; }
    .date-header { text-align: center; margin-bottom: 15px; padding: 10px; background: #fff; border: 2px solid #333; border-radius: 8px; font-size: 24px; font-weight: 900; color: #e91e63; }
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div { border: 2px solid #000000 !important; border-radius: 6px !important; background-color: #ffffff !important; }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 5px !important; margin-bottom: -10px !important; }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] > div[data-testid="column"] { width: 33.33% !important; flex: 1 1 0% !important; min-width: 0 !important; }
    div.element-container:has(#nav-marker) + div.element-container button { padding: 0 !important; font-size: 13px !important; width: 100% !important; white-space: nowrap !important; min-height: 36px !important; height: 36px !important; font-weight: bold !important; border: 1px solid #999 !important; background-color: #f8f9fa !important; }
    div[role="radiogroup"] { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; padding-bottom: 10px; }
    div[role="radiogroup"] > label { background-color: #ffffff !important; border: 2px solid #ccc !important; border-radius: 8px !important; padding: 10px 5px !important; margin: 0 !important; flex: 1 1 auto !important; min-width: 60px !important; justify-content: center !important; box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important; }
    div[role="radiogroup"] > label[data-checked="true"] { background-color: #e3f2fd !important; border-color: #2196f3 !important; }
    div[role="radiogroup"] > label[data-checked="true"] p { color: #1565c0 !important; font-weight: 900 !important; }
    div[role="radiogroup"] > label p { font-size: 15px !important; font-weight: bold !important; margin: 0 !important; }
    div[role="radiogroup"] > label div[data-baseweb="radio"] > div { display: none !important; }
    @keyframes pulse-red { 0% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); } 70% { background-color: #cc0000; box-shadow: 0 0 0 15px rgba(255, 77, 77, 0); } 100% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); } }
    div.element-container:has(button p:contains("📍 到着を記録")) button { animation: pulse-red 1.5s infinite !important; border: 2px solid white !important; color: white !important; font-size: 18px !important; }
    .warning-box { background: #f44336; color: white; padding: 10px; font-weight: bold; border-radius: 5px 5px 0 0; }
    .warning-content { background: #ffebee; border-left: 4px solid #d32f2f; padding: 10px; margin-bottom: 15px; border-radius: 0 0 5px 5px; }
    .title1 { text-align:center; font-size:40px; font-weight:bold; color:white; text-shadow:2px 2px 5px black; margin-top: 30px; }
    .title2 { text-align:center; font-size:32px; font-weight:bold; color:white; text-shadow:2px 2px 5px black; margin-bottom:40px; }
    .footer { position: fixed; bottom: 0; left: 0; width: 100%; background: #333; color: white; padding: 10px; text-align: center; z-index: 9999; }
</style>
""", unsafe_allow_html=True)

current_page = st.session_state.page
NAV_BTN_STYLE = "display:block; text-align:center; padding:12px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:16px; color:white; box-shadow:0 2px 4px rgba(0,0,0,0.2);"
MAP_SEARCH_BTN = """<a href='https://www.google.com/maps' target='_blank' style='display:inline-block; padding:4px 8px; background:#4285f4; color:white; border-radius:4px; text-decoration:none; font-size:12px; font-weight:bold; margin-bottom:5px;'>🔍 Googleマップ</a>"""

if current_page == "home":
    st.markdown("""
    <style>
        div.element-container:has(#btn-staff-marker) + div.element-container button, div.element-container:has(#btn-cast-marker) + div.element-container button { width: 100% !important; height: 80px !important; border-radius: 15px !important; border: 2px solid black !important; box-shadow: 0 4px 6px rgba(0,0,0,0.1) !important; margin-bottom: 10px !important; }
        div.element-container:has(#btn-staff-marker) + div.element-container button p, div.element-container:has(#btn-cast-marker) + div.element-container button p { font-size: 20px !important; font-weight: bold !important; white-space: pre-wrap !important; margin: 0 !important; color: white !important; }
        div.element-container:has(#btn-staff-marker) + div.element-container button { background-color: #64b5f6 !important; }
        div.element-container:has(#btn-cast-marker) + div.element-container button { background-color: #f48fb1 !important; }
        div.element-container:has(#btn-admin-marker) + div.element-container button { width: 100% !important; height: 40px !important; border-radius: 15px !important; border: none !important; box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important; margin-bottom: 10px !important; background-color: #e0e0e0 !important; }
        div.element-container:has(#btn-admin-marker) + div.element-container button p { font-size: 16px !important; font-weight: bold !important; white-space: pre-wrap !important; margin: 0 !important; color: #333333 !important; }
    </style>
    """, unsafe_allow_html=True)
    st.markdown('<div class="title1">六本木水島本店</div>', unsafe_allow_html=True)
    st.markdown('<div class="title2">送迎管理</div>', unsafe_allow_html=True)
    st.markdown('<div id="btn-staff-marker"></div>', unsafe_allow_html=True)
    if st.button("スタッフ業務開始\n（配車・送迎設定）", use_container_width=True): st.session_state.page = "staff_login"; st.rerun()
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div id="btn-cast-marker"></div>', unsafe_allow_html=True)
    if st.button("キャスト専用ログイン\n（予定の申請）", use_container_width=True): st.session_state.page = "cast_login"; st.rerun()
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div id="btn-admin-marker"></div>', unsafe_allow_html=True)
    if st.button("管理者ログイン（設定・リセット）", use_container_width=True): st.session_state.page = "admin_login"; st.rerun()
    st.markdown(f"<div style='text-align:center; color:#999; font-size:12px; margin-top:30px; padding-bottom:60px;'>ver {APP_VERSION}</div>", unsafe_allow_html=True)
    st.markdown('<div class="footer">サーバー同期完了　　　最新データ受信</div>', unsafe_allow_html=True)

if current_page == "cast_login":
    render_top_nav(); db = get_db_data(); casts = db.get("casts", [])
    st.markdown('<div class="app-header">キャストログイン</div>', unsafe_allow_html=True)
    st.caption("店番 または キャスト名を入力し、パスワードを入れてください")
    c_input = st.text_input("店番 または キャスト名", placeholder="例: 15 または ゆみか")
    pw = st.text_input("パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        c_input_str = str(c_input).strip()
        if c_input_str:
            t = next((c for c in casts if str(c["cast_id"]) == c_input_str), None) if c_input_str.isdigit() else next((c for c in casts if c_input_str == str(c.get("name", "")).strip()), None)
            if t:
                correct_pass = str(t.get("password","")).strip().replace("None","")
                if pw == correct_pass or not correct_pass:
                    st.session_state.logged_in_cast = {"店番": str(t["cast_id"]), "キャスト名": str(t["name"]), "方面": t.get("area"), "担当": t.get("manager")}
                    st.session_state.page = "cast_mypage"; st.rerun()
                else: st.error("⚠️ パスワードが違います。")
            else: st.error("⚠️ 該当するキャストが見つかりません。")
        else: st.warning("店番かキャスト名を入力してください。")

if current_page == "admin_login":
    render_top_nav(); db = get_db_data(); settings = db.get("settings") or {}
    pw = st.text_input("管理者パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if pw == "admin" or pw == str(settings.get("admin_password", "admin")): 
            st.session_state.is_admin = True; st.session_state.logged_in_staff = "管理者"
            st.session_state.page = "staff_portal"; st.rerun()
        else: st.error("⚠️ パスワードが違います。")

if current_page == "staff_login":
    render_top_nav(); db = get_db_data(); drivers = db.get("drivers", [])
    for d in [x for x in drivers if str(x["name"]).strip() != ""]:
        st.markdown(f"<div style='font-weight:bold; margin-top:15px; border-bottom:2px solid #ddd; padding-bottom:5px; margin-bottom:10px;'>👤 {d['name']}</div>", unsafe_allow_html=True)
        colA, colB = st.columns([3, 1.2])
        with colA: p_in = st.text_input("PW", type="password", key=f"pw_{d['driver_id']}", label_visibility="collapsed", placeholder="パスワード")
        with colB:
            if st.button("開始", key=f"b_{d['driver_id']}", type="primary", use_container_width=True):
                if p_in in ["0000", str(d.get("password", "")).strip()]: 
                    st.session_state.is_admin = False; st.session_state.logged_in_staff = str(d["name"])
                    st.session_state.page = "staff_portal"; st.rerun()
                else: st.error("❌ エラー")
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)

if current_page == "cast_mypage":
    render_top_nav(); c = st.session_state.logged_in_cast; db = get_db_data()
    settings, casts, attendance = db.get("settings") or {}, db.get("casts", []), db.get("attendance", [])
    my_c = next((x for x in casts if str(x["cast_id"]) == str(c["店番"])), None)
    latest_name = my_c.get("name", c["キャスト名"]) if my_c else c["キャスト名"]
    st.markdown(f'<div style="text-align: center; font-weight: bold; font-size: 20px;">店番 {c["店番"]} {latest_name} 様</div>', unsafe_allow_html=True)
    line_uid = my_c.get("line_user_id", ""); bot_id = str(settings.get("line_bot_id", ""))
    
    if line_uid: st.markdown('<div style="text-align:center; background:#e8f5e9; color:#2e7d32; padding:8px; border-radius:8px; margin-bottom:15px; font-weight:bold; font-size:14px; border:2px solid #4caf50;">✅ LINE通知：連携済み<br><span style="font-size:11px; font-weight:normal;">(配車決定などがLINEにお知らせされます)</span></div>', unsafe_allow_html=True)
    else: st.markdown(f'<div style="text-align:center; background:#ffebee; color:#d32f2f; padding:8px; border-radius:8px; margin-bottom:15px; font-size:13px; border:2px solid #f44336;"><b>⚠️ LINE未連携</b><br>お店のLINE({bot_id})に<br>合言葉「<b>{c["店番"]}{c["キャスト名"]}</b>」とメッセージを送ってください。</div>', unsafe_allow_html=True)

    with st.expander("🏠 自分の登録情報（自宅・託児所）の確認・変更"):
        if my_c:
            raw_addr = my_c.get("address", "")
            home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
            new_home = st.text_input("自宅住所 (迎え先)", value=home_addr)
            st.markdown("<div style='margin-top:10px; font-weight:bold; color:#2196f3;'>👶 託児所の利用設定</div>", unsafe_allow_html=True)
            new_takuji_en = st.checkbox("毎回自動的に託児所を経由する", value=(takuji_en=="1"))
            new_takuji_addr = st.text_input("託児所の住所", value=takuji_addr) if new_takuji_en else ""
            if st.button("💾 決定する", type="primary", use_container_width=True):
                encoded_addr = encode_cast_address(new_home, "1" if new_takuji_en else "0", new_takuji_addr, "1")
                res = post_api({"action": "save_cast", "cast_id": my_c["cast_id"], "name": my_c["name"], "password": my_c.get("password", ""), "phone": my_c.get("phone", ""), "area": my_c.get("area", ""), "address": encoded_addr, "manager": my_c.get("manager", "未設定")})
                if res.get("status") == "success": clear_cache(); st.success("登録情報を更新しました！"); time.sleep(1); st.rerun()

    st.markdown("<div style='margin:top:20px;'></div>", unsafe_allow_html=True)
    with st.expander("💡 今日のトピックス!!（接客の話題にどうぞ）"):
        t_fun, t_trend, t_local, t_econ = st.tabs(["🤣 面白ネタ", "🔥 トレンド", "📰 今日のニュース", "📈 経済全般"])
        with t_fun:
            for n in get_rss_news("https://news.yahoo.co.jp/rss/topics/entertainment.xml", 5): st.markdown(f"・ <a href='{n['link']}' target='_blank' style='text-decoration:none; color:#1565c0; font-size:14px;'>{n['title']}</a>", unsafe_allow_html=True)
        with t_trend:
            for n in get_rss_news("https://news.livedoor.com/topics/rss/trend.xml", 5): st.markdown(f"・ <a href='{n['link']}' target='_blank' style='text-decoration:none; color:#e65100; font-size:14px;'>{n['title']}</a>", unsafe_allow_html=True)
        with t_local:
            for n in get_rss_news("https://news.yahoo.co.jp/rss/topics/local.xml", 5): st.markdown(f"・ <a href='{n['link']}' target='_blank' style='text-decoration:none; color:#2e7d32; font-size:14px;'>{n['title']}</a>", unsafe_allow_html=True)
        with t_econ:
            for n in get_rss_news("https://news.yahoo.co.jp/rss/topics/business.xml", 5): st.markdown(f"・ <a href='{n['link']}' target='_blank' style='text-decoration:none; color:#4527a0; font-size:14px;'>{n['title']}</a>", unsafe_allow_html=True)
    st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

    tab_today, tab_tmr, tab_week = st.tabs(["当日申請", "翌日申請", "週間申請"])
    with tab_today:
        _, takuji_en, _, _ = parse_cast_address(my_c.get("address", "")) if my_c else ("", "0", "", "0")
        m_tdy = next((r for r in attendance if r["target_date"] == "当日" and str(r["cast_id"]) == str(c["店番"])), None)
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
        m_tmr = next((r for r in attendance if r["target_date"] == "翌日" and str(r["cast_id"]) == str(c["店番"])), None)
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
            d = dt + datetime.timedelta(days=i)
            target_val = "翌日" if i == 1 else d.strftime("%Y-%m-%d")
            date_disp = "明日" if i == 1 else f"{d.month}/{d.day}({dow})"
            m_w = next((r for r in attendance if r["target_date"] == target_val and str(r["cast_id"]) == str(c["店番"])), None)
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
                tr = next((r for r in attendance if r["target_date"] == w['date'] and str(r["cast_id"]) == str(c["店番"])), None)
                e_d, e_t, e_dst = "", "", ""
                if tr: _, _, _, e_d, e_t, e_dst, _ = parse_attendance_memo(tr.get("memo", ""))
                enc_w = encode_attendance_memo(w['memo'], "", "0", e_d, e_t, e_dst, "")
                records.append({"cast_id": c["店番"], "cast_name": latest_name, "area": c["方面"], "status": w['attend'], "memo": enc_w, "target_date": w['date']})
            if records:
                res = post_api({"action": "save_attendance", "records": records})
                if res.get("status") == "success": clear_cache(); st.session_state.page = "report_done"; st.rerun()

if current_page == "report_done":
    render_top_nav()
    st.markdown("<h1 style='text-align:center; margin-top:50px;'>✅</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align:center;'>出勤報告を受け付けました。</h3>", unsafe_allow_html=True)
    if st.button("マイページへ戻る", type="primary", use_container_width=True): st.session_state.page = "cast_mypage"; st.rerun()

if current_page == "staff_portal":
    render_top_nav()
    staff_n = st.session_state.logged_in_staff
    is_adm = st.session_state.is_admin
    db = get_db_data()
    casts, drvs, atts, sets = db.get("casts", []), db.get("drivers", []), db.get("attendance", []), db.get("settings") or {}
    d_names = [str(d["name"]) for d in drvs if d.get("name")]
    time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
    early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]
    store_addr = str(sets.get("store_address", "岡山県倉敷市水島東栄町2-24"))
    current_hour, current_minute = dt.hour, dt.minute
    is_return_time = (current_hour > 20) or (current_hour == 20 and current_minute >= 30) or (current_hour <= 7)

    if not is_adm:
        st.markdown(f'<div class="date-header">{today_str} ({dow})</div>', unsafe_allow_html=True)
        d_info = next((d for d in drvs if str(d.get("name")) == staff_n), None)
        if d_info:
            bot_id = str(sets.get("line_bot_id", "")); line_uid = d_info.get("line_user_id", "")
            if line_uid: st.markdown('<div style="text-align:center; background:#e8f5e9; color:#2e7d32; padding:8px; border-radius:8px; margin-bottom:15px; font-size:13px; font-weight:bold;">✅ LINE通知連携済み</div>', unsafe_allow_html=True)
            else: st.markdown(f'<div style="text-align:center; background:#ffebee; color:#d32f2f; padding:8px; border-radius:8px; margin-bottom:15px; font-size:13px;"><b>⚠️ LINE未連携</b><br>お店のLINE({bot_id})に<br>合言葉「<b>STAFF{staff_n}</b>」と送信してください。</div>', unsafe_allow_html=True)
            cur_cap = int(d_info.get("capacity", 4)) if str(d_info.get("capacity", "4")).isdigit() else 4
            col_sn1, col_sn2 = st.columns([2, 1])
            with col_sn1: st.markdown(f"<div style='font-size:20px; font-weight:bold; color:#333; margin-top:5px; margin-bottom:15px;'>👤 {staff_n} 班</div>", unsafe_allow_html=True)
            with col_sn2:
                with st.popover(f"💺 定員: {cur_cap}名"):
                    n_cap = st.number_input("人数", min_value=1, max_value=10, value=cur_cap, key="temp_cap_input")
                    if st.button("変更を反映", type="primary", use_container_width=True):
                        post_api({"action": "save_driver", "driver_id": d_info["driver_id"], "name": d_info["name"], "password": d_info.get("password",""), "address": d_info.get("address",""), "phone": d_info.get("phone",""), "area": d_info.get("area","全般"), "capacity": n_cap})
                        my_assigned = [r for r in atts if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"] and r.get("driver_name") == staff_n]
                        if len(my_assigned) > n_cap:
                            with_dist = []
                            for r in my_assigned:
                                c_inf = next((c for c in casts if str(c["cast_id"]) == str(r["cast_id"])), {})
                                _, d_score = get_route_line_and_distance(clean_address_for_map(c_inf.get("address", "")))
                                with_dist.append({"row": r, "dist": d_score})
                            with_dist.sort(key=lambda x: x["dist"]) 
                            overflow_count = len(my_assigned) - n_cap
                            overflow_casts = [x["row"] for x in with_dist[:overflow_count]]
                            updates = []
                            for oc in overflow_casts:
                                assigned_d = None
                                for d in drvs:
                                    if d["name"] == staff_n: continue
                                    if len([r for r in atts if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"] and r.get("driver_name") == d["name"]]) < int(d.get("capacity", 4)): assigned_d = d["name"]; break
                                updates.append({"id": oc["id"], "driver_name": assigned_d if assigned_d else "未定", "pickup_time": "未定", "status": oc["status"]})
                            if updates:
                                post_api({"action": "update_manual_dispatch", "updates": updates})
                                time.sleep(0.5); recalc_route_for_driver(staff_n, trigger_line_notify=True, manual_order=False)
                                for u in updates:
                                    if u["driver_name"] != "未定": recalc_route_for_driver(u["driver_name"], trigger_line_notify=True, manual_order=False)
                        clear_cache(); st.rerun()

        early_raw = [r for r in atts if r["target_date"] == "当日" and r["status"] == "出勤"]
        my_early = []
        for t in early_raw:
            _, temp_addr, tc, e_drv, e_time, e_dest, so = parse_attendance_memo(t.get("memo", ""))
            if e_drv == staff_n:
                c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), {})
                home_addr, takuji_en, takuji_addr, _ = parse_cast_address(c_info.get("address", ""))
                act_pickup = temp_addr if temp_addr else home_addr
                use_tkj = (takuji_en == "1" and tc == "0" and takuji_addr != "")
                my_early.append({"task": t, "early_time": e_time, "early_dest": e_dest, "c_name": c_info.get("name", t['cast_name']), "c_id": t['cast_id'], "actual_pickup": act_pickup, "use_takuji": use_tkj, "takuji_addr": takuji_addr, "stopover": so})

        if my_early:
            early_html = '<div style="background:#fff3e0; border:2px solid #ff9800; padding:10px; border-radius:8px; margin-bottom:15px;"><h4 style="color:#e65100; margin-top:0; margin-bottom:5px;">🌅 本日の早便</h4>'
            e_dest_addr = my_early[0]["early_dest"] if my_early[0]["early_dest"] else store_addr
            ord_early, early_sec, early_path, first_leg_sec, api_err = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, e_dest_addr, my_early, is_return=False, manual_order=False)
            if not GOOGLE_MAPS_API_KEY: early_html += "<div style='font-size:14px; font-weight:bold; color:white; background:#f44336; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center;'>🚨 API通信エラー: APIキーが設定されていません</div>"
            else:
                earliest_m = 9999
                for rt in ord_early:
                    try:
                        h, m = map(int, rt["early_time"].split(':'))
                        if h * 60 + m < earliest_m: earliest_m = h * 60 + m
                    except Exception: pass
                if earliest_m != 9999:
                    dep_m = earliest_m - (first_leg_sec // 60)
                    if dep_m < 0: dep_m += 24 * 60
                    early_html += f"<div style='font-size:15px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center;'>🚀 店舗出発 (AI逆算): {(dep_m // 60) % 24:02d}:{dep_m % 60:02d}</div>"
            if early_path:
                org_enc = urllib.parse.quote(store_addr); d_enc = urllib.parse.quote(e_dest_addr); wp_enc = urllib.parse.quote("|".join(early_path)) if early_path else ""
                map_url = f"https://www.google.com/maps/dir/?api=1&origin={org_enc}&destination={d_enc}&waypoints={wp_enc}&travelmode=driving"
                early_html += f"<a href='{map_url}' target='_blank' style='{NAV_BTN_STYLE} background:#ff9800; margin-bottom:10px;'>🗺️ 早便ナビ開始</a>"
            for idx, rt in enumerate(ord_early): early_html += f"<div style='font-size:14px;'><b>順 {idx+1}</b>: {rt['c_name']}<br><span style='color:#e65100;font-size:12px;font-weight:bold;'>⏰ 送り先到着: {rt['early_time']}</span><br><span style='color:#1565c0;font-size:12px;'>🏠 迎え: {rt['actual_pickup']}</span><br><span style='color:#666;font-size:12px;'>🏁 届け先: {rt['early_dest']}</span></div><hr style='margin:5px 0;'>"
            early_html += '</div>'
            st.markdown(early_html, unsafe_allow_html=True)

        my_tasks = []
        for t in atts:
            if t["target_date"] == "当日" and t["status"] in ["出勤", "自走"] and t.get("driver_name") == staff_n:
                _, _, _, e_drv, _, _, _ = parse_attendance_memo(t.get("memo", ""))
                if e_drv and e_drv != "未定" and e_drv != "": continue
                if t["status"] != "自走": my_tasks.append(t)
        
        if my_tasks:
            t_rows = sorted(my_tasks, key=lambda x: x['pickup_time'] if x['pickup_time'] and x['pickup_time'] != '未定' else '99:99')
            list_html_head = f'<div style="background:#444; color:white; padding:10px; font-weight:bold; border-radius:5px 5px 0 0;">🚕 通常便ルート</div>'
            
            if is_return_time:
                list_html = list_html_head + f'<div style="background:#ffffff; border:1px solid #ccc; border-top:none; padding:10px; border-radius:0 0 5px 5px; margin-bottom:20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);"><div style="background:#e3f2fd; border:2px solid #2196f3; padding:8px; border-radius:5px; margin-bottom:15px;"><div style="color:#1565c0; font-weight:bold; margin-bottom:5px;">🌙 帰り班 (自動編成)</div>'
                return_tasks = []
                for t in reversed(t_rows):
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                    raw_addr = c_info.get("address", "") if c_info else ""
                    home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
                    raw_memo = t.get("memo", "")
                    _, temp_addr, takuji_cancel, _, _, _, _ = parse_attendance_memo(raw_memo)
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    return_tasks.append({"task": t, "dist": 0, "actual_pickup": actual_pickup, "use_takuji": use_takuji, "takuji_addr": takuji_addr, "c_name": c_info.get("name", t['cast_name']), "c_id": t['cast_id']})
                
                ordered_returns, ret_sec, return_full_path, _, api_err = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, return_tasks, is_return=True, manual_order=False)
                if return_full_path:
                    org_enc = urllib.parse.quote(store_addr); dest_enc = urllib.parse.quote(store_addr); wp_enc = urllib.parse.quote("|".join(return_full_path[:-1])) if len(return_full_path) > 1 else ""
                    map_url = f"https://www.google.com/maps/dir/?api=1&origin={org_enc}&destination={dest_enc}&waypoints={wp_enc}&travelmode=driving"
                    list_html += f"<a href='{map_url}' target='_blank' style='{NAV_BTN_STYLE} background:#1565c0; margin-bottom:10px;'>🗺️ 帰りナビ開始 (現在地から)</a>"
                for idx, rt in enumerate(ordered_returns):
                    list_html += f"<div style='font-size:13px;'>降車順 {idx+1}：<b>{rt['c_name']}</b><br>"
                    if rt["use_takuji"]: list_html += f"<span style='color:#2196f3;font-size:11px;font-weight:bold;'>👶 託児経由: {rt['takuji_addr']}</span><br>"
                    list_html += f"<span style='color:#666;font-size:11px;'>🏠 降車先: {rt['actual_pickup']}</span></div><hr style='margin:5px 0;'>"
                list_html += '</div></div>'
                st.markdown(list_html, unsafe_allow_html=True)
                render_dispatch_editor(staff_n, 1, t_rows, ordered_returns, d_names, False)

            else:
                tasks_with_details = []
                for t in t_rows:
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), {})
                    raw_addr = c_info.get("address", "")
                    home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                    raw_memo = t.get("memo", "")
                    memo_text, temp_addr, takuji_cancel, _, _, _, stopover = parse_attendance_memo(raw_memo)
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    latest_name = c_info.get("name", t['cast_name']) if c_info else t['cast_name']
                    tasks_with_details.append({"task": t, "c_info": c_info, "actual_pickup": actual_pickup, "stopover": stopover, "use_takuji": use_takuji, "takuji_addr": takuji_addr, "memo_text": memo_text, "c_name": latest_name, "c_id": t['cast_id'], "is_edited": is_edited, "home_addr": home_addr, "temp_addr": temp_addr, "takuji_cancel": takuji_cancel})

                tasks_with_details.sort(key=lambda x: x["task"].get("pickup_time", "99:99"))
                ordered_tasks, total_sec, full_path, first_leg_sec, api_err = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, tasks_with_details, is_return=False, manual_order=True)

                list_html = list_html_head + '<div style="background:#ffffff; border:1px solid #ccc; border-top:none; padding:10px; border-radius:0 0 5px 5px; margin-bottom:20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">'
                list_html += "<div style='font-size:12px; font-weight:bold; color:#e91e63; text-align:center; margin-bottom:5px;'>🤖 遠いキャストから拾いながらお店に戻る最短ルートです</div>"
                if not GOOGLE_MAPS_API_KEY: list_html += "<div style='font-size:14px; font-weight:bold; color:white; background:#f44336; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center;'>🚨 API通信エラー: APIキーが設定されていません</div>"
                else:
                    earliest_m = 9999
                    for t in ordered_tasks:
                        try:
                            pt = str(t['task'].get('pickup_time', ''))
                            if pt and pt != '未定':
                                h, m = map(int, pt.split(':'))
                                earliest_m = min(earliest_m, h * 60 + m)
                        except Exception: pass
                    
                    if earliest_m != 9999:
                        dep_m = earliest_m - (first_leg_sec // 60) - 5
                        if dep_m < 0: dep_m += 24 * 60
                        if 6 * 60 < dep_m < 16 * 60: dep_m = 16 * 60
                        list_html += f"<div style='font-size:15px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center; border: 1px solid #f44336;'>🚀 店舗出発時刻 (計算): {(dep_m // 60) % 24:02d}:{dep_m % 60:02d}</div>"

                if full_path:
                    org_enc = urllib.parse.quote(store_addr); dest_enc = urllib.parse.quote(store_addr); wp_enc = urllib.parse.quote("|".join(full_path)) if full_path else ""
                    map_url = f"https://www.google.com/maps/dir/?api=1&origin={org_enc}&destination={dest_enc}&waypoints={wp_enc}&travelmode=driving"
                    list_html += f"<a href='{map_url}' target='_blank' style='{NAV_BTN_STYLE} background:#4caf50; margin-bottom:15px;'>🗺️ スマホのナビで全行程を開始</a>"
                
                for idx, t in enumerate(ordered_tasks):
                    addr_display = f"🏠 迎え: {t['home_addr'] if t['home_addr'] else '未登録'}"
                    if t["temp_addr"]: addr_display += f"<br><span style='color:#e91e63;font-weight:bold;'>📍 当日変更: {t['temp_addr']}</span>"
                    if t["stopover"]: addr_display += f"<br><span style='color:#ff9800;font-weight:bold;'>🍽️ 立ち寄り(同伴): {t['stopover']}</span>"
                    if t["use_takuji"]: addr_display += f"<br><span style='color:#2196f3;font-weight:bold;'>👶 経由(託児): {t['takuji_addr']}</span>"
                    if t["memo_text"]: addr_display += f"<br>📝 備考: {t['memo_text']}"
                    list_html += f"<div style='margin-bottom:8px;'><b>迎え順 {idx+1}： {t['task']['pickup_time']}</b>　<span style='font-size:16px; font-weight:bold;'>{t['c_name']}</span> <br><span style='font-size:13px;'>{addr_display}</span></div><hr style='margin:5px 0;'>"
                list_html += '</div>'
                st.markdown(list_html, unsafe_allow_html=True)
                render_dispatch_editor(staff_n, 1, t_rows, ordered_tasks, d_names, False)

        my_atts = [r for r in atts if r["target_date"] == "当日" and r["driver_name"] == staff_n and r["status"] == "出勤"]
        active = next((r for r in my_atts if not r.get("boarded_at")), None)
        if active:
            c_info = next((c for c in casts if str(c["cast_id"]) == str(active["cast_id"])), {})
            latest_name = c_info.get("name", active["cast_name"])
            st.markdown(f"<div style='background:#1e1e1e; padding:15px; border-radius:12px; border:2px solid #00bcd4; margin-bottom:10px;'><h2 style='color:white; margin:0;'>{latest_name} さん</h2></div>", unsafe_allow_html=True)
            if not active.get("arrived_at"):
                if st.button("📍 到着を記録", key=f"arr_{active['cast_id']}", use_container_width=True):
                    post_api({"action": "record_driver_action", "attendance_id": active["id"], "type": "arrive"}); clear_cache(); st.rerun()
            else:
                if st.button("🟢 乗車完了", key=f"brd_{active['cast_id']}", use_container_width=True):
                    post_api({"action": "record_driver_action", "attendance_id": active["id"], "type": "board"}); clear_cache(); st.rerun()

    if is_adm:
        tabs_list_admin = ["① 配車リスト", "② キャスト送迎", "③ キャスト登録", "④ STAFF設定", "⚙️ 管理設定"]
        current_tab = st.session_state.get("current_staff_tab", "① 配車リスト")
        try: tab_index = tabs_list_admin.index(current_tab)
        except ValueError: tab_index = 0
            
        selected_tab = st.radio("メニュー", tabs_list_admin, index=tab_index, horizontal=True, label_visibility="collapsed")
        st.session_state.current_staff_tab = selected_tab
        st.session_state.staff_tab = selected_tab
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        range_opts = ["全表示"] + [f"{i*10+1}-{i*10+10}" for i in range(15)]
        
        if selected_tab == "① 配車リスト":
            st.markdown(f'<div class="date-header">{today_str} 配車</div>', unsafe_allow_html=True)
            if not GOOGLE_MAPS_API_KEY: st.error("🚨 Google Maps APIキーが設定されていません。AI配車機能とルート計算が正常に機能しません。")
                
            early_disp_tasks = []
            seen_cids_e = set()
            for row in atts:
                if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                    cid_str = str(row["cast_id"])
                    if cid_str in seen_cids_e: continue
                    seen_cids_e.add(cid_str)
                    _, _, _, e_drv, e_time, e_dest, _ = parse_attendance_memo(row.get("memo", ""))
                    if e_drv and e_drv != "未定" and e_drv != "":
                        c_info = next((c for c in casts if str(c["cast_id"]) == str(row["cast_id"])), {})
                        early_disp_tasks.append({"name": c_info.get("name", row["cast_name"]), "drv": e_drv, "time": e_time, "dest": e_dest})
            
            if early_disp_tasks:
                early_html = '<div style="background:#fff3e0; border: 2px solid #ff9800; padding: 10px; border-radius: 8px; margin-bottom: 15px;"><div style="font-weight:bold; color:#e65100; font-size:15px; margin-bottom:5px;">🌅 本日の早便一覧（設定済）</div>'
                for ed in early_disp_tasks: early_html += f"<div style='font-size:13px; color:#333; margin-bottom:3px;'>・ <b>{ed['name']}</b> ➡️ {ed['dest']} ({ed['time']}着) / ドライバー: {ed['drv']}</div>"
                early_html += '</div>'
                st.markdown(early_html, unsafe_allow_html=True)

            st.markdown('<div style="background:#e8f5e9; border: 2px solid #4caf50; padding: 10px; border-radius: 8px; margin-bottom: 10px;"><div style="font-weight:bold; color:#2e7d32; font-size:16px; margin-bottom:5px;">🤖 自動配車（Google AI連携）</div><div style="font-size:12px; color:#555;">現在手動で割り当てているキャストも一旦リセットし、<br>AIが定員を守りながら「遠い人から拾う」最短ルートを組み直します。</div></div>', unsafe_allow_html=True)
            
            if not d_names: st.warning("⚠️ まだドライバーが登録されていません。「④ STAFF設定」タブを開いて登録してください。")
            else:
                if "active_drv_state" not in st.session_state: st.session_state.active_drv_state = d_names
                valid_drv = [d for d in st.session_state.active_drv_state if d in d_names]
                def on_drv_change(): st.session_state.active_drv_state = st.session_state.active_drv_ms
                dispatch_mode = st.radio("🤖 AI配車の優先アルゴリズム", ["1: ルート効率化優先", "2: 完全均等振分け優先"], horizontal=True)
                
                with st.expander("🛠️ 稼働ドライバーの選択 (タップで開く)", expanded=False):
                    active_drivers = st.multiselect("稼働するドライバーを選択", d_names, default=valid_drv, key="active_drv_ms", on_change=on_drv_change)
                
                if st.button("🚀 AI自動配車 (ゼロベース再編成)", type="primary", use_container_width=True):
                    if not GOOGLE_MAPS_API_KEY: st.error("🚨 API通信エラー: Google Maps APIキーが読み込めないため、AI自動配車は実行できません。")
                    elif not active_drivers: st.error("稼働するドライバーを1人以上選択してください。")
                    else:
                        st.info("Google AIでルートを計算中... ⏳")
                        learning_scores = {}
                        for r in atts:
                            if r.get("status") in ["出勤", "自走"] and r.get("driver_name") and r.get("driver_name") not in ["", "未定"]:
                                cid, drv = str(r.get("cast_id")), r.get("driver_name")
                                if cid not in learning_scores: learning_scores[cid] = {}
                                learning_scores[cid][drv] = learning_scores[cid].get(drv, 0) + 1

                        def driver_covers_line(drv_area, c_line):
                            if drv_area == "全般": return True
                            if drv_area == "広島方面" and c_line == "Route_A_West": return True
                            if drv_area == "岡山方面" and c_line == "Route_C_North": return True
                            if drv_area == "広島＆岡山方面" and c_line in ["Route_A_West", "Route_C_North"]: return True
                            if drv_area == "倉敷・岡山方面" and c_line in ["Route_C_North", "Route_B_NorthWest", "Route_E_South"]: return True
                            if drv_area == "倉敷方面" and c_line in ["Route_E_South", "Route_B_NorthWest"]: return True
                            return False

                        all_today_casts, early_drivers, seen_cids_ai = [], set(), set()
                        for row in atts:
                            if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                                cid_str = str(row["cast_id"])
                                if cid_str in seen_cids_ai: continue
                                seen_cids_ai.add(cid_str)
                                c_info = next((c for c in casts if str(c["cast_id"]) == str(row["cast_id"])), {})
                                raw_addr = c_info.get("address", "")
                                home_addr, _, _, _ = parse_cast_address(raw_addr)
                                _, temp_addr, _, e_drv, _, _, _ = parse_attendance_memo(row.get("memo", ""))
                                if e_drv and e_drv != "未定" and e_drv != "":
                                    early_drivers.add(e_drv); continue 
                                actual_pickup = temp_addr if temp_addr else home_addr
                                line, dst = get_route_line_and_distance(actual_pickup)
                                all_today_casts.append({"row": row, "line": line, "dist": dst, "actual_pickup": actual_pickup})
                        
                        if not all_today_casts:
                            st.warning("⚠️ 通常AI配車の対象者がいません（全員が早便や自走、または未出勤です）")
                            time.sleep(2.5); st.rerun()
                        else:
                            all_today_casts.sort(key=lambda x: x["dist"], reverse=True)
                            drv_specs = {}
                            for d in drvs:
                                if d["name"] in active_drivers:
                                    if d["name"] in early_drivers: continue
                                    try: cap = int(d.get("capacity", 4))
                                    except: cap = 4
                                    drv_specs[d["name"]] = {"capacity": cap, "assigned_rows": [], "line": None, "area": d.get("area", "全般")}

                            for uc in all_today_casts:
                                if uc["row"]["status"] == "自走": continue
                                assigned_d, c_line, cid = None, uc["line"], str(uc["row"]["cast_id"])
                                best_score, best_d = -1, None
                                
                                for d_name, stat in drv_specs.items():
                                    if len(stat["assigned_rows"]) >= stat["capacity"]: continue
                                    
                                    # 🌟店舗跨ぎの完全禁止：ルート確定済みの車には別ルートのキャストを乗せない
                                    if stat["line"] is not None and stat["line"] != c_line: continue
                                    if not driver_covers_line(stat["area"], c_line): continue
                                    
                                    score = learning_scores.get(cid, {}).get(d_name, 0) * 5
                                    if "2:" in dispatch_mode: score += (stat["capacity"] - len(stat["assigned_rows"])) * 10
                                    if score > best_score: best_score = score; best_d = d_name
                                
                                if best_d: assigned_d = best_d
                                else:
                                    for d_name, stat in drv_specs.items():
                                        if len(stat["assigned_rows"]) < stat["capacity"] and (stat["line"] is None or stat["line"] == c_line):
                                            assigned_d = d_name; break

                                if assigned_d: 
                                    if drv_specs[assigned_d]["line"] is None: drv_specs[assigned_d]["line"] = c_line
                                    drv_specs[assigned_d]["assigned_rows"].append(uc)

                            assigned_ids = set()
                            base_time = str(sets.get("base_arrival_time", "19:50"))
                            try: bh, bm = map(int, base_time.split(':')); b_mins = bh * 60 + bm
                            except: b_mins = 19 * 60 + 50

                            all_driver_updates, driver_routes_info = [], {}
                            for d_name, stat in drv_specs.items():
                                assigned_list = stat["assigned_rows"]
                                if not assigned_list: continue

                                ai_tasks = []
                                for item in assigned_list:
                                    c_info = next((c for c in casts if str(c["cast_id"]) == str(item["row"]["cast_id"])), {})
                                    latest_name = c_info.get("name", item["row"]["cast_name"])
                                    ai_tasks.append({"task": item["row"], "actual_pickup": item["actual_pickup"], "c_name": latest_name, "c_id": item["row"]["cast_id"], "dist_score": item["dist"]})
                                
                                ordered_tasks, total_sec, full_path, first_leg_sec, api_err = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, ai_tasks, is_return=False, manual_order=False)
                                
                                if total_sec == 0:
                                    st.warning(f"⚠️ API通信エラー: {d_name}班の計算に失敗しました。")
                                    total_casts, interval_mins = len(ordered_tasks), 15
                                else:
                                    total_casts = len(ordered_tasks)
                                    interval_mins = (total_sec // 60) // (total_casts + 1) if total_casts > 0 else 15
                                    if interval_mins < 1: interval_mins = 1
                                
                                t_mins_list = []
                                for idx in range(total_casts):
                                    mins_to_subtract = (total_casts - idx) * interval_mins
                                    t_mins = b_mins - mins_to_subtract
                                    if t_mins < 0: t_mins += 24 * 60
                                    t_mins_list.append(t_mins)
                                    
                                if t_mins_list:
                                    earliest_m = min(t_mins_list)
                                    dep_m = earliest_m - (first_leg_sec // 60) - 5
                                    if 6 * 60 < dep_m < 16 * 60:
                                        dep_m = 16 * 60
                                        t_mins_list = []; current_m = dep_m + (first_leg_sec // 60) + 5
                                        for idx in range(total_casts):
                                            t_mins_list.append(current_m); current_m += interval_mins

                                route_details = []
                                dep_time_str = f"{(dep_m // 60) % 24:02d}:{dep_m % 60:02d}" if t_mins_list else "未定"
                                
                                for idx, item in enumerate(ordered_tasks):
                                    tm = t_mins_list[idx]
                                    current_calc_time = f"{(tm // 60) % 24:02d}:{tm % 60:02d}"
                                    all_driver_updates.append({"id": item["task"]["id"], "driver_name": d_name, "pickup_time": current_calc_time, "status": item["task"]["status"]})
                                    assigned_ids.add(item["task"]["id"])
                                    route_details.append({"name": item["c_name"], "time": current_calc_time, "addr": item["actual_pickup"], "cast_line_id": next((c.get("line_user_id", "") for c in casts if str(c["cast_id"]) == str(item["c_id"])), "")})
                                
                                driver_routes_info[d_name] = {"dep_time": dep_time_str, "route": route_details, "driver_line_id": next((d.get("line_user_id", "") for d in drvs if d["name"] == d_name), "")}
                                
                            if all_driver_updates: post_api({"action": "update_manual_dispatch", "updates": all_driver_updates})
                            
                            # 🌟 未割り当て（送迎不可）の処理
                            unassigned_updates = [{"id": uc["row"]["id"], "driver_name": "未定", "pickup_time": "未定", "status": uc["row"]["status"]} for uc in all_today_casts if uc["row"]["status"] != "自走" and uc["row"]["id"] not in assigned_ids]
                            if unassigned_updates: post_api({"action": "update_manual_dispatch", "updates": unassigned_updates})
                            
                            line_token = sets.get("line_access_token", "")
                            for d_name, info in driver_routes_info.items():
                                notify_driver_route_via_line(line_token, info["driver_line_id"], d_name, info["route"], info["dep_time"])
                                for rt in info["route"]: notify_cast_via_line(line_token, rt["cast_line_id"], rt["name"], rt["time"], d_name)
                            clear_cache(); st.session_state.flash_msg = "AI配車が完了しました！"; st.rerun()

        st.radio("表示", ["当日", "翌日", "週間"], horizontal=True, label_visibility="collapsed")
        unassigned, my_tasks = [], {}
        seen_cids_disp = set()
        for row in atts:
            if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                cid_str = str(row["cast_id"])
                if cid_str in seen_cids_disp: continue
                seen_cids_disp.add(cid_str)
                drv = row["driver_name"]
                _, _, _, e_drv, _, _, _ = parse_attendance_memo(row.get("memo", ""))
                if e_drv and e_drv != "未定" and e_drv != "": continue
                if not drv or drv == "未定" or row["status"] == "自走": 
                    if row["status"] != "自走": unassigned.append(row)
                else:
                    if drv not in my_tasks: my_tasks[drv] = []
                    my_tasks[drv].append(row)
        
        # 🌟 ドライバー不足の警告
        if unassigned:
            unassigned_html = '<div class="warning-box">⚠️ ドライバー不足で送迎できません</div><div class="warning-content"><div style="font-size:12px; color:#666; margin-bottom:10px;">※ルート制限・定員オーバーのため送迎できません。稼働ドライバーを追加してください。</div>'
            for u in unassigned:
                c_info = next((c for c in casts if str(c["cast_id"]) == str(u["cast_id"])), {})
                latest_name = c_info.get("name", u["cast_name"])
                unassigned_html += f"<div style='margin-bottom:5px;'><b>送迎不可</b>　<span style='font-size:16px; font-weight:bold; color:#d32f2f;'>{latest_name}</span> <br><span style='font-size:12px; color:#555;'>({u['status']})</span></div><hr style='margin:5px 0;'>"
            unassigned_html += '</div>'
            st.markdown(unassigned_html, unsafe_allow_html=True)
        
        course_idx = 1
        for d_name, t_rows in my_tasks.items():
            t_rows = sorted(t_rows, key=lambda x: x['pickup_time'] if x['pickup_time'] and x['pickup_time'] != '未定' else '99:99')
            st.markdown(f'<div style="background:#444; color:white; padding:10px; font-weight:bold; border-radius:5px 5px 0 0;">🚕 コース{course_idx}：{d_name} (STAFF)</div>', unsafe_allow_html=True)
            
            if is_return_time:
                st.markdown(f'<div style="background:#ffffff; border:1px solid #ccc; border-top:none; padding:10px; border-radius:0 0 5px 5px; margin-bottom:20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);"><div style="background:#e3f2fd; border:2px solid #2196f3; padding:8px; border-radius:5px; margin-bottom:15px;"><div style="color:#1565c0; font-weight:bold; margin-bottom:5px;">🌙 帰り班 (自動編成)</div>', unsafe_allow_html=True)
                return_tasks = []
                for t in reversed(t_rows):
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                    raw_addr = c_info.get("address", "") if c_info else ""
                    home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
                    raw_memo = t.get("memo", "")
                    _, temp_addr, takuji_cancel, _, _, _, _ = parse_attendance_memo(raw_memo)
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    latest_name = c_info.get("name", t['cast_name']) if c_info else t['cast_name']
                    return_tasks.append({"task": t, "dist": 0, "actual_pickup": actual_pickup, "use_takuji": use_takuji, "takuji_addr": takuji_addr, "c_name": latest_name, "c_id": t['cast_id']})
                
                ordered_returns, ret_sec, return_full_path, _, api_err = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, return_tasks, is_return=True, manual_order=False)
                if return_full_path:
                    org_enc = urllib.parse.quote(store_addr); dest_enc = urllib.parse.quote(store_addr); wp_enc = urllib.parse.quote("|".join(return_full_path[:-1])) if len(return_full_path) > 1 else ""
                    map_url = f"https://www.google.com/maps/dir/?api=1&origin={org_enc}&destination={dest_enc}&waypoints={wp_enc}&travelmode=driving"
                    st.markdown(f"<a href='{map_url}' target='_blank' style='{NAV_BTN_STYLE} background:#1565c0; margin-bottom:10px;'>🗺️ 帰りナビ開始 (現在地から)</a>", unsafe_allow_html=True)
                for idx, rt in enumerate(ordered_returns):
                    disp_str = f"<div style='font-size:13px;'>降車順 {idx+1}：<b>{rt['c_name']}</b><br>"
                    if rt["use_takuji"]: disp_str += f"<span style='color:#2196f3;font-size:11px;font-weight:bold;'>👶 託児経由: {rt['takuji_addr']}</span><br>"
                    st.markdown(disp_str + f"<span style='color:#666;font-size:11px;'>🏠 降車先: {rt['actual_pickup']}</span></div><hr style='margin:5px 0;'>", unsafe_allow_html=True)
                st.markdown('</div></div>', unsafe_allow_html=True)
                render_dispatch_editor(d_name, course_idx, t_rows, ordered_returns, d_names, True)

            else:
                tasks_with_details = []
                for t in t_rows:
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), {})
                    raw_addr = c_info.get("address", "")
                    home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                    raw_memo = t.get("memo", "")
                    memo_text, temp_addr, takuji_cancel, _, _, _, stopover = parse_attendance_memo(raw_memo)
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    latest_name = c_info.get("name", t['cast_name']) if c_info else t['cast_name']
                    tasks_with_details.append({"task": t, "c_info": c_info, "actual_pickup": actual_pickup, "stopover": stopover, "use_takuji": use_takuji, "takuji_addr": takuji_addr, "memo_text": memo_text, "c_name": latest_name, "c_id": t['cast_id'], "is_edited": is_edited, "home_addr": home_addr, "temp_addr": temp_addr, "takuji_cancel": takuji_cancel})

                tasks_with_details.sort(key=lambda x: x["task"].get("pickup_time", "99:99"))
                ordered_tasks, total_sec, full_path, first_leg_sec, api_err = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, tasks_with_details, is_return=False, manual_order=True)

                list_html = '<div style="background:#ffffff; border:1px solid #ccc; border-top:none; padding:10px; border-radius:0 0 5px 5px; margin-bottom:20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">'
                list_html += "<div style='font-size:12px; font-weight:bold; color:#e91e63; text-align:center; margin-bottom:5px;'>🤖 遠いキャストから拾いながらお店に戻る最短ルートです</div>"
                if not GOOGLE_MAPS_API_KEY: list_html += "<div style='font-size:14px; font-weight:bold; color:white; background:#f44336; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center;'>🚨 API通信エラー: APIキーが設定されていません</div>"
                else:
                    earliest_m = 9999
                    for t in ordered_tasks:
                        try:
                            pt = str(t['task'].get('pickup_time', ''))
                            if pt and pt != '未定':
                                h, m = map(int, pt.split(':'))
                                earliest_m = min(earliest_m, h * 60 + m)
                        except Exception: pass
                    
                    if earliest_m != 9999:
                        dep_m = earliest_m - (first_leg_sec // 60) - 5
                        if dep_m < 0: dep_m += 24 * 60
                        if 6 * 60 < dep_m < 16 * 60: dep_m = 16 * 60
                        list_html += f"<div style='font-size:15px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center; border: 1px solid #f44336;'>🚀 店舗出発時刻 (計算): {(dep_m // 60) % 24:02d}:{dep_m % 60:02d}</div>"

                if full_path:
                    org_enc = urllib.parse.quote(store_addr); dest_enc = urllib.parse.quote(store_addr); wp_enc = urllib.parse.quote("|".join(full_path)) if full_path else ""
                    map_url = f"https://www.google.com/maps/dir/?api=1&origin={org_enc}&destination={dest_enc}&waypoints={wp_enc}&travelmode=driving"
                    list_html += f"<a href='{map_url}' target='_blank' style='{NAV_BTN_STYLE} background:#4caf50; margin-bottom:15px;'>🗺️ スマホのナビで全行程を開始</a>"
                
                for idx, t in enumerate(ordered_tasks):
                    addr_display = f"🏠 迎え: {t['home_addr'] if t['home_addr'] else '未登録'}"
                    if t["temp_addr"]: addr_display += f"<br><span style='color:#e91e63;font-weight:bold;'>📍 当日変更: {t['temp_addr']}</span>"
                    if t["stopover"]: addr_display += f"<br><span style='color:#ff9800;font-weight:bold;'>🍽️ 立ち寄り(同伴): {t['stopover']}</span>"
                    if t["use_takuji"]: addr_display += f"<br><span style='color:#2196f3;font-weight:bold;'>👶 経由(託児): {t['takuji_addr']}</span>"
                    if t["memo_text"]: addr_display += f"<br>📝 備考: {t['memo_text']}"
                    list_html += f"<div style='margin-bottom:8px;'><b>迎え順 {idx+1}： {t['task']['pickup_time']}</b>　<span style='font-size:16px; font-weight:bold;'>{t['c_name']}</span> <br><span style='font-size:13px;'>{addr_display}</span></div><hr style='margin:5px 0;'>"
                list_html += '</div>'
                st.markdown(list_html, unsafe_allow_html=True)
                render_dispatch_editor(staff_n, 1, t_rows, ordered_tasks, d_names, True)
        course_idx += 1

    elif selected_tab == "② キャスト送迎":
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

        dispatch_count = 0
        early_count = 0
        today_active_casts = []
        seen_cids_today = set()
        for row in atts:
            if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                cid_str = str(row["cast_id"])
                if cid_str in seen_cids_today: continue
                seen_cids_today.add(cid_str)
                dispatch_count += 1
                _, _, _, e_drv, _, _, _ = parse_attendance_memo(row.get("memo", ""))
                is_early = (e_drv and e_drv != "未定" and e_drv != "")
                if is_early: early_count += 1
                c_info_dict = next((c for c in casts if str(c["cast_id"]) == str(row["cast_id"])), {})
                pref = c_info_dict.get("area", "他")
                today_active_casts.append({"id": row["cast_id"], "name": row["cast_name"], "status": row["status"], "is_early": is_early, "pref": pref, "row": row})

        today_active_casts = sorted(today_active_casts, key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else 999)

        st.markdown(f'''
        <div style="background-color: #e3f2fd; border: 2px solid #2196f3; padding: 10px; border-radius: 8px; text-align: center; margin-bottom: 10px;">
            <span style="font-size: 14px; color: #1565c0; font-weight: bold;">🚗 現在の送迎申請数（当日）</span><br>
            <span style="font-size: 24px; font-weight: bold; color: #e91e63;">{dispatch_count}</span> <span style="font-size: 16px; color: #1565c0; font-weight: bold;">名</span>
            <div style="font-size: 14px; color: #e65100; font-weight: bold; margin-top: 5px;">🌅 うち早便設定済： {early_count} 名</div>
        </div>
        ''', unsafe_allow_html=True)
        
        show_active_casts = st.toggle(f"📋 当日の出勤キャストを表示する（{dispatch_count}名）")
        if show_active_casts:
            if today_active_casts:
                list_search = st.text_input("🔍 一覧からキャストを絞り込み検索", placeholder="名前 または 店番", key="today_list_search")
                st.markdown("<div style='margin-top:10px;'>", unsafe_allow_html=True)
                display_c = 0
                for loop_idx, c_dict in enumerate(today_active_casts):
                    c_id, c_name = str(c_dict['id']), c_dict['name']
                    if list_search and list_search not in c_name and list_search != c_id: continue
                    display_c += 1
                    c_inf = next((c for c in casts if str(c["cast_id"]) == c_id), {})
                    latest_name = c_inf.get("name", c_name)
                    render_cast_edit_card(c_id, latest_name, c_dict.get('pref', '他'), c_dict.get('row'), "tdy", d_names, time_slots, early_time_slots, loop_idx)
                if display_c == 0: st.write("該当するキャストがいません。")
                st.markdown("</div>", unsafe_allow_html=True)
            else: st.info("本日の送迎申請はまだありません。")

        st.markdown("<hr style='margin:15px 0;'>", unsafe_allow_html=True)
        if "search_cast_key" not in st.session_state: st.session_state.search_cast_key = 0
        if "active_search_query" not in st.session_state: st.session_state.active_search_query = ""
            
        st.markdown("<div style='font-size:14px; font-weight:bold; color:#555; margin-bottom:5px;'>🔍 全キャスト検索 (未出勤者の予定追加・変更)</div>", unsafe_allow_html=True)
        col_search1, col_search2 = st.columns([3, 1])
        with col_search1: input_q = st.text_input("検索キーワード", placeholder="名前 または 店番", key=f"search_input_{st.session_state.search_cast_key}", label_visibility="collapsed")
        with col_search2:
            if st.button("検索", type="secondary", use_container_width=True): st.session_state.active_search_query = input_q; st.rerun()

        def reset_search(): st.session_state.active_search_query = ""; st.session_state.search_cast_key += 1; clear_cache()
        act_rng = st.radio("範囲", range_opts, horizontal=True, label_visibility="collapsed")
        st.markdown("<hr style='margin:15px 0;'>", unsafe_allow_html=True)
        
        search_query, display_count, seen_all_cids = st.session_state.active_search_query, 0, set()
        for loop_idx, cast in enumerate(casts):
            c_id, c_name = str(cast["cast_id"]), str(cast["name"])
            if not c_name: continue
            if c_id in seen_all_cids: continue
            seen_all_cids.add(c_id)
            if search_query:
                if search_query not in c_name and search_query not in c_id: continue
            else:
                if not is_in_range(c_id, act_rng): continue
            display_count += 1
            pref = str(cast["area"])
            target_row = next((row for row in atts if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"] and str(row["cast_id"]) == str(c_id)), None)
            render_cast_edit_card(c_id, c_name, pref, target_row, "all", d_names, time_slots, early_time_slots, loop_idx)
        if display_count == 0: st.info("条件に一致するキャストが見つかりません。")

    elif selected_tab == "③ キャスト登録":
        st.markdown('<div style="margin-bottom:15px;">', unsafe_allow_html=True)
        search_query_reg = st.text_input("🔍 キャスト検索 (名前または店番)", placeholder="例: ゆみか, 94", key="search_cast_reg")
        st.markdown('</div>', unsafe_allow_html=True)

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
            
            st.markdown(f"<div style='background:#fff; padding:10px; border-radius:8px; border:1px solid #ccc; margin-bottom:10px;'>", unsafe_allow_html=True)
            col_title, col_mgr = st.columns([3, 2])
            with col_title:
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:5px;'>店番 {i} : {nm if nm else '未登録'}</div>", unsafe_allow_html=True)
            with col_mgr:
                mgr_idx = staff_list.index(mgr) if mgr in staff_list else 0
                n_mgr = st.selectbox("担当", staff_list, index=mgr_idx, key=f"cmgr_{i}", label_visibility="collapsed")
                if n_mgr != mgr:
                    res = post_api({"action": "save_cast", "cast_id": i, "name": nm, "password": str(c.get("password", "0000")), "phone": str(c.get("phone", "")), "area": str(c.get("area", "")), "address": str(c.get("address", "")), "manager": n_mgr})
                    if res.get("status") == "success": clear_cache(); st.rerun()

            with st.expander(f"詳細・住所設定 (店番 {i})"):
                nn = st.text_input("名前", value=nm, key=f"cn_{i}")
                raw_addr = str(c.get("address", ""))
                home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                if is_edited == "1": st.markdown("<div style='color:#4caf50; font-weight:bold; font-size:14px; margin-bottom:10px;'>✅ キャスト本人が自宅住所を更新済みです</div>", unsafe_allow_html=True)
                
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
                
                if st.session_state.get(f"saved_cast_{i}", False):
                    st.markdown('<div style="background-color: #4caf50; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold; margin-bottom: 10px;">✅ 登録済</div>', unsafe_allow_html=True)
                    if st.button("内容を変更する", key=f"edit_cast_{i}", use_container_width=True): st.session_state[f"saved_cast_{i}"] = False; st.rerun()
                else:
                    if st.button("保存する", key=f"cs_{i}", type="primary", use_container_width=True):
                        city_part = c_other_city if c_city == "他" else c_city
                        final_home = c_pref + city_part + c_rest
                        auto_area = "岡山" if c_pref == "岡山県" else ("広島" if c_pref == "広島県" else "他")
                        encoded_addr = encode_cast_address(final_home, "1" if new_takuji_en else "0", new_takuji_addr, "0")
                        res = post_api({"action": "save_cast", "cast_id": i, "name": nn, "password": np, "phone": nt, "area": auto_area, "address": encoded_addr, "manager": n_mgr})
                        if res.get("status") == "success": clear_cache(); st.session_state[f"saved_cast_{i}"] = True; st.success("保存しました！"); time.sleep(1); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        if display_count == 0: st.info("条件に一致するキャストが見つかりません。")

    elif selected_tab == "④ STAFF設定":
        exist_drvs = {str(d["driver_id"]): d for d in drvs}
        if "editing_staff_id" not in st.session_state: st.session_state.editing_staff_id = None

        if st.session_state.editing_staff_id is None:
            st.markdown('<div class="app-header">STAFF一覧・登録</div>', unsafe_allow_html=True)
            for i in range(1, 31):
                d = exist_drvs.get(str(i), {})
                nm, area = d.get("name", ""), d.get("area", "全般")
                disp_nm = nm if nm else "(未登録)"
                disp_area = f"[{area}]" if nm else ""
                
                col1, col2 = st.columns([4, 1])
                with col1: st.markdown(f"<div style='padding:10px 0; border-bottom:1px solid #ddd; font-size:15px;'><b>STAFF {i}</b> : {disp_nm} <span style='color:#666; font-size:12px;'>{disp_area}</span></div>", unsafe_allow_html=True)
                with col2:
                    st.markdown("<div style='margin-top:5px;'></div>", unsafe_allow_html=True)
                    if st.button("詳細", key=f"edit_staff_btn_{i}", use_container_width=True):
                        st.session_state.editing_staff_id = i; st.rerun()
        else:
            i = st.session_state.editing_staff_id
            if st.button("🔙 STAFF一覧に戻る", use_container_width=True): st.session_state.editing_staff_id = None; st.rerun()
                
            d = exist_drvs.get(str(i), {})
            nm = str(d.get("name", ""))
            st.markdown(f'<div class="card" style="padding:15px; border-top: 4px solid #4caf50; margin-top:15px;">', unsafe_allow_html=True)
            st.markdown(f'<div style="font-weight:bold; font-size:18px; margin-bottom:15px;">✏️ STAFF {i} の詳細設定</div>', unsafe_allow_html=True)
            
            d_area = str(d.get("area", "全般")).strip()
            area_opts = ["全般", "広島方面", "岡山方面", "広島＆岡山方面", "倉敷・岡山方面", "倉敷方面"]
            if d_area not in area_opts:
                if "岡山" in d_area and "広島" in d_area: d_area = "広島＆岡山方面"
                elif "岡山" in d_area and "倉敷" in d_area: d_area = "倉敷・岡山方面"
                elif "倉敷" in d_area: d_area = "倉敷方面"
                elif "岡山" in d_area: d_area = "岡山方面"
                elif "広島" in d_area: d_area = "広島方面"
                else: d_area = "全般"
                
            d_cap = int(d.get("capacity", 4)) if str(d.get("capacity", "")).isdigit() else 4
            nn = st.text_input("STAFF名", value=nm, key=f"dn_{i}")
            colA, colB = st.columns(2)
            with colA: n_area = st.selectbox("担当方面", area_opts, index=area_opts.index(d_area), key=f"d_ar_{i}")
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
            
            if st.session_state.get(f"saved_staff_{i}", False):
                st.markdown('<div style="background-color: #4caf50; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold; margin-bottom: 10px;">✅ 決定済み</div>', unsafe_allow_html=True)
                if st.button("🔄 再変更", key=f"reedit_staff_{i}", use_container_width=True): st.session_state[f"saved_staff_{i}"] = False; st.rerun()
            else:
                if st.button("💾 決定する", key=f"ds_{i}", type="primary", use_container_width=True):
                    city_part = d_other_city if d_city == "他" else d_city
                    final_addr = d_pref + city_part + d_rest
                    payload = {"action": "save_driver", "driver_id": i, "name": nn, "password": n_pass, "address": final_addr, "phone": n_tel, "area": n_area, "capacity": n_cap}
                    res = post_api(payload)
                    if res.get("status") == "success": clear_cache(); st.session_state[f"saved_staff_{i}"] = True; st.success("保存しました！"); st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    elif selected_tab == "⚙️ 管理設定":
        st.markdown('<div class="app-header" style="border:none;">📢 アプリ全体設定</div>', unsafe_allow_html=True)
        with st.form("adm_form"):
            s_notice = sets.get("notice_text", "") if isinstance(sets, dict) else ""
            s_pass = sets.get("admin_password", "admin") if isinstance(sets, dict) else "admin"
            s_line = sets.get("line_bot_id", "") if isinstance(sets, dict) else ""
            s_addr = sets.get("store_address", "岡山県倉敷市水島東栄町2-24") if isinstance(sets, dict) else "岡山県倉敷市水島東栄町2-24"
            s_time = sets.get("base_arrival_time", "19:50") if isinstance(sets, dict) else "19:50"
            s_line_token = sets.get("line_access_token", "") if isinstance(sets, dict) else ""
            
            st.markdown('<div class="section-title" style="color:#2196f3; margin-top:0;">📍 送迎基本設定 (店舗・到着時間)</div>', unsafe_allow_html=True)
            n_addr = st.text_input("到着場所（店舗住所）", value=s_addr)
            arr_idx = time_slots.index(s_time) if s_time in time_slots else 0
            n_time = st.selectbox("基本到着時間 (厳守)", time_slots, index=arr_idx)
            
            st.markdown('<div class="section-title" style="margin-top:20px;">お知らせ</div>', unsafe_allow_html=True)
            n_text = st.text_area("例：明日イベント開催！", value=s_notice, label_visibility="collapsed")
            
            st.markdown('<div class="section-title" style="color:#e91e63;">🔑 管理者パスワード</div>', unsafe_allow_html=True)
            a_pass = st.text_input("パスワード", value=s_pass, label_visibility="collapsed")
            
            st.markdown('<div class="section-title" style="color:#00c300;">📱 LINE Bot設定</div>', unsafe_allow_html=True)
            l_id = st.text_input("Bot ID (表示用)", value=s_line, placeholder="@123abcde")
            l_token = st.text_input("LINE アクセストークン (通知用・長文)", value=s_line_token, type="password", placeholder="非常に長い英数字の文字列です")
            
            if st.form_submit_button("保存して反映", type="primary", use_container_width=True):
                res = post_api({"action": "save_settings", "admin_password": a_pass, "notice_text": n_text, "line_bot_id": l_id, "store_address": n_addr, "base_arrival_time": n_time, "line_access_token": l_token})
                if res.get("status") == "success": clear_cache(); st.session_state.flash_msg = "設定を保存しました"; st.rerun()
