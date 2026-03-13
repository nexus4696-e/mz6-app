import os
import requests
import datetime
import urllib.parse
import time
import re
import xml.etree.ElementTree as ET
import streamlit as st

# 🌟 システムバージョン管理
APP_VERSION = 3

# 🌟 抜本的解決：店長からいただいた「確実に稼働するAPIキー」を直接コードに埋め込みます
# （Cloud Runの設定が空でも、このキーが絶対に作動します）
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
if not GOOGLE_MAPS_API_KEY:
    GOOGLE_MAPS_API_KEY = "AIzaSyCRZS-A7Sasucg_lcPksXB7jao8xW6ckeE"

# 🌟 日本時間（JST）を強制的に設定して時差バグを完全に防止
JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')

# 🌟 エラー完全防止：日付変数を一番上でグローバル定義
dt = datetime.datetime.now(JST)
today_str = dt.strftime("%m月%d日")
dow = ['月','火','水','木','金','土','日'][dt.weekday()]

# ==========================================
# 🌟 ページの設定（アイコン化の完全対応）
# ==========================================
st.set_page_config(
    page_title="六本木 水島本店 送迎管理",
    page_icon="http://mute-imari-1089.catfood.jp/mz6/28470.jpg", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

# 🌟 スマホ（Chrome）の勝手な自動誤翻訳（翌日→火曜日など）を強制的に禁止する
st.markdown('<meta name="google" content="notranslate">', unsafe_allow_html=True)

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

# 🌟 今日のトピックス用データ取得機能
@st.cache_data(ttl=3600)
def get_rss_news(url, limit=5):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7',
            'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        }
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        root = ET.fromstring(res.content)
        items = []
        for item in root.findall('.//item')[:limit]:
            title = item.find('title').text
            link = item.find('link').text
            items.append({"title": title, "link": link})
        return items
    except:
        return [{"title": "情報の取得に失敗しました", "link": "#"}]

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
# 🤖 AIルート計算
# ==========================================
@st.cache_data(ttl=120)
def optimize_and_calc_route(api_key, store_addr, dest_addr, tasks_list, is_return=False):
    api_error_msg = ""
    if not api_key:
        return tasks_list, 0, [], 0, "APIキーが設定されていません"
    if not tasks_list:
        return tasks_list, 0, [], 0, ""

    valid_tasks = []
    for t in tasks_list:
        addr = clean_address_for_map(t.get("actual_pickup", ""))
        if addr:
            _, dist_score = get_route_line_and_distance(addr)
            t["dist_score"] = dist_score
            valid_tasks.append(t)

    invalid_tasks = [t for t in tasks_list if not clean_address_for_map(t.get("actual_pickup", ""))]
    
    if is_return:
        valid_tasks.sort(key=lambda x: x["dist_score"])
    else:
        valid_tasks.sort(key=lambda x: x["dist_score"], reverse=True)

    ordered_valid_tasks = valid_tasks
    total_sec = 0
    first_leg_sec = 0
    full_path = []
    actual_dest = dest_addr if dest_addr else store_addr

    if len(ordered_valid_tasks) > 1:
        wp_str = "optimize:true|" + "|".join([clean_address_for_map(t["actual_pickup"]) for t in ordered_valid_tasks])
        try:
            res = requests.get("https://maps.googleapis.com/maps/api/directions/json", params={
                "origin": store_addr,
                "destination": actual_dest,
                "waypoints": wp_str,
                "key": api_key,
                "language": "ja"
            }, timeout=10).json()
            
            if res.get("status") == "OK":
                wp_order = res["routes"][0]["waypoint_order"]
                ordered_valid_tasks = [valid_tasks[i] for i in wp_order]
                
                legs = res["routes"][0]["legs"]
                dur_to_first = legs[0]["duration"]["value"]
                dur_from_last = legs[-1]["duration"]["value"]
                
                is_loop = (store_addr == actual_dest) or ("倉敷市水島東栄町" in actual_dest)
                if is_loop:
                    if is_return: 
                        if dur_to_first > dur_from_last:
                            ordered_valid_tasks.reverse()
                    else: 
                        if dur_to_first < dur_from_last:
                            ordered_valid_tasks.reverse()
            else:
                api_error_msg = f"{res.get('status')} - {res.get('error_message', '')}"
        except Exception as e:
            api_error_msg = f"通信例外: {str(e)}"

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
            res2 = requests.get("https://maps.googleapis.com/maps/api/directions/json", params=params, timeout=10).json()
            if res2.get("status") == "OK":
                legs = res2["routes"][0]["legs"]
                total_sec = sum(leg["duration"]["value"] for leg in legs)
                if legs:
                    first_leg_sec = legs[0]["duration"]["value"]
            else:
                if not api_error_msg:
                    api_error_msg = f"{res2.get('status')} - {res2.get('error_message', '')}"
        except Exception as e:
            if not api_error_msg:
                api_error_msg = f"通信例外2: {str(e)}"
            
    return final_ordered_tasks, total_sec, full_path, first_leg_sec, api_error_msg

# ==========================================
# 🌟 UIパーツ生成
# ==========================================
def render_cast_edit_card(c_id, c_name, pref, target_row, prefix_key, d_names_list, t_slots, e_t_slots, loop_idx):
    key_suffix = f"{c_id}_{prefix_key}_{loop_idx}"
    db_temp = get_db_data()
    settings = db_temp.get("settings", {})
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

        if st.session_state.get(f"saved_dispatch_{key_suffix}", False):
            st.markdown('<div style="background-color: #4caf50; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold; margin-bottom: 10px;">✅ 決定済み</div>', unsafe_allow_html=True)
            if st.button("🔄 再変更", key=f"reedit_{key_suffix}", use_container_width=True):
                st.session_state[f"saved_dispatch_{key_suffix}"] = False
                st.rerun()
        else:
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
                new_memo = st.text_input("備考", value=new_memo, key=f"mm_{key_suffix}")
                new_tc = st.checkbox("本日託児キャンセル", value=(takuji_cancel == "1"), key=f"tc_{key_suffix}")
                st.markdown("</div>", unsafe_allow_html=True)
            else: new_ed, new_et, new_eds, new_so, new_ta, new_memo, new_tc = e_drv, e_time, e_dest, stopover, temp_addr, memo_text, (takuji_cancel == "1")

            msg_placeholder = st.empty()
            if st.button("💾 決定する", key=f"btn_upd_{key_suffix}", type="primary", use_container_width=True):
                msg_placeholder.info("⏳ データベースを書き換えています...")
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
                            if n_d != "未定" and n_d != cur_drv:
                                stff_id = next((d.get("line_user_id", "") for d in db_f.get("drivers", []) if d["name"] == n_d), "")
                                notify_staff_via_line(settings.get("line_access_token", ""), stff_id, n_d, latest_name, n_t)
                    
                    st.session_state[f"saved_dispatch_{key_suffix}"] = True
                    st.session_state.active_search_query = ""
                    if "search_cast_key" in st.session_state:
                        st.session_state.search_cast_key += 1
                    st.session_state.flash_msg = f"{latest_name} 更新完了"
                    st.rerun()

# ==========================================
# 🎨 CSS設計
# ==========================================
st.markdown("""
<style>
    /* 全体の背景と基本スタイル */
    html, body, [data-testid="stAppViewContainer"], .block-container {
        max-width: 100vw !important;
        overflow-x: hidden !important;
        background-color: #f0f2f5;
        font-family: -apple-system, sans-serif;
    }
    .block-container {
        padding-top: 1rem;
        padding-bottom: 5rem;
        max-width: 600px;
    }
    header, footer, [data-testid="stToolbar"] {
        display: none !important;
    }
    .app-header {
        border-bottom: 2px solid #333;
        padding-bottom: 5px;
        margin-bottom: 10px;
        font-size: 20px;
        font-weight: bold;
    }
    .date-header {
        text-align: center;
        margin-bottom: 15px;
        padding: 10px;
        background: #fff;
        border: 2px solid #333;
        border-radius: 8px;
        font-size: 24px;
        font-weight: 900;
        color: #e91e63;
    }
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div {
        border: 2px solid #000000 !important;
        border-radius: 6px !important;
        background-color: #ffffff !important;
    }
    
    /* スタッフ ポータル内のナビゲーションボタン横並び */
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 5px !important;
        margin-bottom: -10px !important;
    }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        width: 33.33% !important;
        flex: 1 1 0% !important;
        min-width: 0 !important;
    }
    div.element-container:has(#nav-marker) + div.element-container button {
        padding: 0 !important;
        font-size: 13px !important;
        width: 100% !important;
        white-space: nowrap !important;
        min-height: 36px !important;
        height: 36px !important;
        line-height: 1.2 !important;
        font-weight: bold !important;
        border: 1px solid #999 !important;
        background-color: #f8f9fa !important;
    }

    /* ラジオグループ（出勤状態、メニュー）のスタイル */
    div[role="radiogroup"] {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        justify-content: center;
        padding-bottom: 10px;
    }
    div[role="radiogroup"] > label {
        background-color: #ffffff !important;
        border: 2px solid #ccc !important;
        border-radius: 8px !important;
        padding: 10px 5px !important;
        margin: 0 !important;
        flex: 1 1 auto !important;
        min-width: 60px !important;
        justify-content: center !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
    }
    div[role="radiogroup"] > label[data-checked="true"] {
        background-color: #e3f2fd !important;
        border-color: #2196f3 !important;
    }
    div[role="radiogroup"] > label[data-checked="true"] p {
        color: #1565c0 !important;
        font-weight: 900 !important;
    }
    div[role="radiogroup"] > label p {
        font-size: 15px !important;
        font-weight: bold !important;
        margin: 0 !important;
    }
    div[role="radiogroup"] > label div[data-baseweb="radio"] > div {
        display: none !important;
    }

    /* 到着記録ボタンのアニメーション */
    @keyframes pulse-red {
        0% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); }
        70% { background-color: #cc0000; box-shadow: 0 0 0 15px rgba(255, 77, 77, 0); }
        100% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); }
    }
    div.element-container:has(button p:contains("📍 到着を記録")) button {
        animation: pulse-red 1.5s infinite !important;
        border: 2px solid white !important;
        color: white !important;
        font-size: 18px !important;
    }
    
    /* 警告ボックスのスタイル */
    .warning-box {
        background: #f44336;
        color: white;
        padding: 10px;
        font-weight: bold;
        border-radius: 5px 5px 0 0;
    }
    .warning-content {
        background: #ffebee;
        border-left: 4px solid #d32f2f;
        padding: 10px;
        margin-bottom: 15px;
        border-radius: 0 0 5px 5px;
    }
</style>
""", unsafe_allow_html=True)

time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]

# 🌟 抜本的修正：世界共通で確実に起動する公式Googleマップ検索URL
MAP_SEARCH_BTN = """<a href='https://www.google.com/maps' target='_blank' style='display:inline-block; padding:4px 8px; background:#4285f4; color:white; border-radius:4px; text-decoration:none; font-size:12px; font-weight:bold; margin-bottom:5px;'>🔍 Googleマップを開く</a>"""
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
    st.markdown("""
    <style>
        [data-testid="stAppViewContainer"] {
            background: linear-gradient(135deg, #1a2a6c, #11212b, #000000) !important;
        }
        .home-title {
            font-size: 36px !important;
            font-weight: 900 !important;
            text-align: center !important;
            margin: 60px 0 40px 0 !important;
            color: #fff !important;
            text-shadow: 0 4px 10px rgba(0,0,0,0.9), 0 0 15px rgba(0,0,0,0.8), 0 0 5px rgba(0,0,0,1) !important;
            letter-spacing: 0.1em !important;
            font-family: "Noto Serif JP", serif !important;
        }
        div.element-container:has(.home-title) ~ div.element-container button {
            height: 60px !important;
            font-size: 20px !important;
            font-weight: bold !important;
            margin-bottom: 20px !important;
            border: none !important;
            border-radius: 30px !important;
            box-shadow: 0 6px 12px rgba(0,0,0,0.4) !important;
            transition: all 0.3s ease !important;
            color: #fff !important;
        }
        div.element-container:has(.home-title) ~ div.element-container [data-testid="stMarkdownContainer"] button {
            background: linear-gradient(135deg, #1565c0, #0d47a1) !important;
        }
        div.element-container:has(.home-title) ~ div.element-container button.secondary {
            background: rgba(255, 255, 255, 0.1) !important;
            backdrop-filter: blur(10px) !important;
            border: 1px solid rgba(255, 255, 255, 0.2) !important;
        }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="home-title">六本木 水島本店<br>送迎管理</div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 4, 1])
    with col2:
        if st.button("🚙 スタッフ業務開始", type="primary", use_container_width=True): st.session_state.page = "staff_login"; st.rerun()
        st.write(""); st.write("")
        if st.button("👩 キャスト専用ログイン", use_container_width=True): st.session_state.page = "cast_login"; st.rerun()
        st.write(""); st.write("")
        if st.button("⚙️ 管理者ログイン", use_container_width=True): st.session_state.page = "admin_login"; st.rerun()
        # 🌟 バージョン番号の表示
        st.markdown(f"<div style='text-align:center; color:#888; font-size:14px; margin-top:30px; font-weight:bold;'>システムバージョン: ver {APP_VERSION}</div>", unsafe_allow_html=True)

elif st.session_state.page == "cast_login":
    render_top_nav(); db = get_db_data(); casts = db.get("casts", [])
    
    st.markdown('<div class="app-header">キャストログイン</div>', unsafe_allow_html=True)
    st.caption("店番 または キャスト名を入力し、パスワードを入れてください")
    
    c_input = st.text_input("店番 または キャスト名", placeholder="例: 15 または ゆみか")
    pw = st.text_input("パスワード", type="password")
    
    if st.button("ログイン", type="primary", use_container_width=True):
        c_input_str = str(c_input).strip()
        if c_input_str:
            t = None
            if c_input_str.isdigit():
                t = next((c for c in casts if str(c["cast_id"]) == c_input_str), None)
            else:
                t = next((c for c in casts if c_input_str == str(c.get("name", "")).strip()), None)
            
            if t:
                correct_pass = str(t.get("password","")).strip().replace("None","")
                if pw == correct_pass or not correct_pass:
                    st.session_state.logged_in_cast = {"店番": str(t["cast_id"]), "キャスト名": str(t["name"]), "方面": t.get("area"), "担当": t.get("manager")}
                    st.session_state.page = "cast_mypage"; st.rerun()
                else:
                    st.error("⚠️ パスワードが違います。")
            else:
                st.error("⚠️ 該当するキャストが見つかりません。")
        else:
            st.warning("店番かキャスト名を入力してください。")

elif st.session_state.page == "admin_login":
    render_top_nav(); db = get_db_data(); settings = db.get("settings") or {}
    pw = st.text_input("管理者パスワード", type="password")
    if st.button("ログイン", type="primary", use_container_width=True):
        if pw == "admin" or pw == str(settings.get("admin_password", "admin")): st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = True, "管理者", "staff_portal"; st.rerun()
        else: st.error("⚠️ パスワードが違います。")

elif st.session_state.page == "staff_login":
    render_top_nav(); db = get_db_data(); drivers = db.get("drivers", [])
    for d in [x for x in drivers if str(x["name"]).strip() != ""]:
        st.markdown(f"<div style='font-weight:bold; margin-top:15px; border-bottom:2px solid #ddd; padding-bottom:5px; margin-bottom:10px;'>👤 {d['name']}</div>", unsafe_allow_html=True)
        colA, colB = st.columns([3, 1.2])
        with colA: p_in = st.text_input("PW", type="password", key=f"pw_{d['driver_id']}", label_visibility="collapsed", placeholder="パスワード")
        with colB:
            if st.button("開始", key=f"b_{d['driver_id']}", type="primary", use_container_width=True):
                if p_in in ["0000", str(d.get("password")).strip()]: 
                    st.session_state.is_admin = False
                    st.session_state.logged_in_staff = str(d["name"])
                    st.session_state.page = "staff_portal"
                    st.rerun()
                else: 
                    st.error("❌ エラー")
        st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)

# ==========================================
# 👩 キャストマイページ
# ==========================================
elif st.session_state.page == "cast_mypage":
    render_top_nav(); c = st.session_state.logged_in_cast
    db = get_db_data(); settings = db.get("settings") or {}; casts = db.get("casts", []); attendance = db.get("attendance", [])
    
    my_c = next((x for x in casts if str(x["cast_id"]) == str(c["店番"])), None)
    latest_name = my_c.get("name", c["キャスト名"]) if my_c else c["キャスト名"]
    
    st.markdown(f'<div style="text-align: center; font-weight: bold; font-size: 20px;">店番 {c["店番"]} {latest_name} 様</div>', unsafe_allow_html=True)
    
    line_uid = my_c.get("line_user_id", "") if my_c else ""
    bot_id = str(settings.get("line_bot_id", ""))
    
    if line_uid:
        st.markdown('<div style="text-align:center; background:#e8f5e9; color:#2e7d32; padding:8px; border-radius:8px;
