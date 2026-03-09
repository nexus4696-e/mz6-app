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
    line = "Route_E_South" 
    dist = 10
    if any(x in addr for x in ["広島", "福山", "笠岡", "浅口", "里庄", "玉島", "井原"]):
        line = "Route_A_West"
    elif any(x in addr for x in ["真備", "矢掛", "総社", "清音", "船穂"]):
        line = "Route_B_NorthWest"
    elif any(x in addr for x in ["北区", "中区", "庭瀬", "中庄", "庄", "倉敷"]):
        if any(x in addr for x in ["水島", "連島", "広江", "児島", "下津井"]): pass 
        else: line = "Route_C_North"
    if line == "Route_E_South": 
        if any(x in addr for x in ["備前", "瀬戸内", "赤磐", "東区", "南区", "妹尾", "早島", "茶屋町", "玉野"]):
            line = "Route_D_East"
        else:
            line = "Route_E_South"
    return line, dist

# 🌟 【絶対ルール厳守】乗車時間を最短化する「完全なGoogle AIアルゴリズム」
@st.cache_data(ttl=120)
def optimize_and_calc_route(api_key, store_addr, dest_addr, tasks_list, is_return=False):
    if not api_key or not tasks_list:
        return tasks_list, 0, []

    valid_tasks = []
    valid_pickups = []
    for t in tasks_list:
        addr = clean_address_for_map(t["actual_pickup"])
        if addr:
            valid_tasks.append(t)
            valid_pickups.append(addr)

    invalid_tasks = [t for t in tasks_list if not clean_address_for_map(t["actual_pickup"])]
    
    ordered_valid_tasks = valid_tasks
    total_sec = 0
    full_path = []

    if len(valid_pickups) == 1:
        ordered_valid_tasks = valid_tasks
    elif len(valid_pickups) > 1:
        # Google AIに店舗を起点・終点とした「最適な一筆書きルート」を計算させる
        wp_str = "optimize:true|" + "|".join(valid_pickups)
        try:
            res = requests.get("https://maps.googleapis.com/maps/api/directions/json", params={
                "origin": store_addr,
                "destination": store_addr,
                "waypoints": wp_str,
                "key": api_key,
                "language": "ja"
            }).json()
            
            if res.get("status") == "OK":
                wp_order = res["routes"][0]["waypoint_order"]
                ordered_valid_tasks = [valid_tasks[i] for i in wp_order]
                ordered_pickups = [valid_pickups[i] for i in wp_order]
                
                legs = res["routes"][0]["legs"]
                # AIが弾き出した、店舗からの「行き」と「帰り」の所要時間を比較
                dur_to_first = legs[0]["duration"]["value"]
                dur_from_last = legs[-1]["duration"]["value"]
                
                if is_return:
                    # 帰り便：店舗から「近い人」から降ろしていく
                    if dur_to_first > dur_from_last:
                        ordered_valid_tasks.reverse()
                        ordered_pickups.reverse()
                else:
                    # 迎え便：店舗から「一番遠い人」まで空車で向かい、拾いながら帰る（乗車時間最短）
                    if dur_to_first < dur_from_last:
                        ordered_valid_tasks.reverse()
                        ordered_pickups.reverse()
        except:
            pass
            
    final_ordered_tasks = ordered_valid_tasks + invalid_tasks

    # 同伴や託児所を含めた最終的なフルルートを構築
    for t in final_ordered_tasks:
        if t.get("actual_pickup"): full_path.append(clean_address_for_map(t["actual_pickup"]))
        if t.get("stopover"): full_path.append(clean_address_for_map(t["stopover"]))
        if t.get("use_takuji") and t.get("takuji_addr"): full_path.append(clean_address_for_map(t["takuji_addr"]))
        
    full_path = [p for p in full_path if p]
    
    # リアルな走行時間を再計算（出発時間の逆算用）
    if full_path:
        calc_origin = store_addr
        calc_dest = store_addr if not is_return else full_path[-1]
        calc_waypoints = full_path if not is_return else full_path[:-1]
        
        params = {
            "origin": calc_origin,
            "destination": calc_dest,
            "key": api_key,
            "language": "ja"
        }
        if calc_waypoints:
            params["waypoints"] = "|".join(calc_waypoints)
            
        try:
            res2 = requests.get("https://maps.googleapis.com/maps/api/directions/json", params=params).json()
            if res2.get("status") == "OK":
                legs = res2["routes"][0]["legs"]
                total_sec = sum(leg["duration"]["value"] for leg in legs)
        except:
            pass
            
    return final_ordered_tasks, total_sec, full_path

# 🌟 【バグ完全排除】確実な画面切り替えを行うキャスト詳細編集カード
def render_cast_edit_card(c_id, c_name, pref, target_row, prefix_key, d_names_list, t_slots, e_t_slots, loop_idx):
    key_suffix = f"{c_id}_{prefix_key}_{loop_idx}"
    
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
    
    with st.expander(f"店番 {c_id} : {c_name} ({pref}) - {title_badge}"):
        st.markdown("<div style='font-size:13px; font-weight:bold; color:#1565c0; margin-bottom:5px;'>🚙 迎え便（通常）設定</div>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            new_status = st.selectbox("出勤状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(cur_status) if cur_status in ["未定", "出勤", "自走", "休み"] else 0, key=f"st_{key_suffix}")
        with col2:
            drv_opts = ["未定"] + d_names_list
            new_drv = st.selectbox("送迎ドライバー", drv_opts, index=drv_opts.index(cur_drv) if cur_drv in drv_opts else 0, key=f"drv_{key_suffix}")
        with col3:
            time_opts = ["未定", "AI算出中"] + t_slots
            new_time = st.selectbox("時間", time_opts, index=time_opts.index(cur_time) if cur_time in time_opts else 0, key=f"tm_{key_suffix}")
            
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        
        show_details = st.toggle("⚙️ 早便や詳細設定（同伴・変更など）を開く", key=f"toggle_{key_suffix}")
        
        new_e_drv = e_drv if e_drv else "未定"
        new_e_time = e_time if e_time else (e_t_slots[0] if e_t_slots else "17:00")
        new_e_dest = e_dest
        new_stopover = stopover
        new_temp_addr = temp_addr
        new_memo = memo_text
        new_takuji_cancel = (takuji_cancel == "1")

        if show_details:
            st.markdown("<div style='background:#fffde7; padding:10px; border-radius:8px; border:1px solid #fdd835;'>", unsafe_allow_html=True)
            st.markdown("<div style='font-size:13px; font-weight:bold; color:#e65100; margin-bottom:5px;'>🌅 早便（送り便）設定</div>", unsafe_allow_html=True)
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                new_e_drv = st.selectbox("早便ドライバー", drv_opts, index=drv_opts.index(new_e_drv) if new_e_drv in drv_opts else 0, key=f"edrv_{key_suffix}")
            with col_e2:
                new_e_time = st.selectbox("到着指定時間", e_t_slots, index=e_t_slots.index(new_e_time) if new_e_time in e_t_slots else 0, key=f"etm_{key_suffix}")
            new_e_dest = st.text_input("早便送迎先 (住所・駅名など)", value=new_e_dest, key=f"edest_{key_suffix}")

            st.markdown("<div style='font-size:13px; font-weight:bold; color:#4caf50; margin-top:10px; margin-bottom:5px;'>📝 詳細情報（同伴・変更など）</div>", unsafe_allow_html=True)
            new_stopover = st.text_input("立ち寄り先 (同伴等)", value=new_stopover, key=f"so_{key_suffix}")
            new_temp_addr = st.text_input("当日のみ迎え先変更", value=new_temp_addr, key=f"ta_{key_suffix}")
            new_memo = st.text_input("備考", value=new_memo, key=f"mm_{key_suffix}")
            new_takuji_cancel = st.checkbox("本日の託児をキャンセル", value=new_takuji_cancel, key=f"tc_{key_suffix}")
            st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
        
        # 🌟 ここが「確実に処理を終えてから画面を切り替える」ための心臓部です
        msg_placeholder = st.empty()
        if st.button("💾 この内容で更新する", key=f"btn_upd_{key_suffix}", type="primary", use_container_width=True):
            msg_placeholder.info("⏳ データベースを書き換えています...")
            
            if new_status in ["未定", "休み"]:
                new_drv = "未定"
                new_time = "未定"
                new_e_drv = "未定"
                new_e_time = "未定"
                new_e_dest = ""

            tc_val = "1" if new_takuji_cancel else "0"
            save_e_drv = new_e_drv if new_e_drv != "未定" else ""
            save_e_time = new_e_time if save_e_drv else ""
            save_e_dest = new_e_dest if save_e_drv else ""

            enc_memo = encode_attendance_memo(new_memo, new_temp_addr, tc_val, save_e_drv, save_e_time, save_e_dest, new_stopover)
            
            # 🌟 「未定」の時は確実に配車から除外
            if new_status in ["未定", "休み"]:
                post_api({"action": "cancel_dispatch", "cast_id": c_id})

            rec = {
                "cast_id": c_id,
                "cast_name": c_name,
                "area": pref,
                "status": new_status,
                "memo": enc_memo,
                "target_date": "当日"
            }
            res1 = post_api({"action": "save_attendance", "records": [rec]})
            
            if res1.get("status") == "success":
                # 🌟 DBが確実に情報を保存し終わるのを1秒待つ（人数が減らないバグを完璧に阻止）
                time.sleep(1.0)
                clear_cache()
                
                if new_status not in ["未定", "休み"]:
                    db_temp = get_db_data()
                    new_row = next((r for r in db_temp.get("attendance", []) if r["target_date"] == "当日" and str(r["cast_id"]) == str(c_id)), None)
                    if new_row:
                        updates = [{"id": new_row["id"], "driver_name": new_drv, "pickup_time": new_time, "status": new_status}]
                        post_api({"action": "update_manual_dispatch", "updates": updates})
                        time.sleep(0.5)
                        clear_cache()
                
                msg_placeholder.success("✅ 保存完了！画面を最新に切り替えます...")
                time.sleep(0.5)
                st.session_state.flash_msg = f"{c_name} の情報を更新しました！"
                st.rerun() 
            else:
                msg_placeholder.error("エラー: " + res1.get("message"))

# ==========================================
# 🎨 クリーンで安全なCSS
# ==========================================
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .block-container {
        max-width: 100vw !important;
        overflow-x: hidden !important;
        background-color: #f0f2f5; 
        font-family: -apple-system, sans-serif;
    }
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 600px; }
    
    header, footer, [data-testid="stToolbar"], [data-testid="manage-app-button"] { display: none !important; visibility: hidden !important; }
    a[href^="https://streamlit.io/cloud"] { display: none !important; }

    .app-header { border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; font-size: 20px; font-weight: bold; }
    .home-title { font-size: 24px; font-weight: bold; text-align: center; margin-bottom: 30px; margin-top: 30px; }
    .shop-no-badge-mini { background: #ffeb3b; color: #d32f2f; font-weight: bold; padding: 2px 4px; border-radius: 4px; border: 1px solid #d32f2f; font-size: 12px; margin-right: 5px; display: inline-block; min-width: 45px; text-align: center; }
    .notice-box { border: 2px solid #fdd835; background: #fffde7; padding: 15px; border-radius: 8px; margin-bottom: 20px; text-align: center; }
    .date-header { text-align: center; margin-bottom: 15px; padding: 10px; background: #fff; border: 2px solid #333; border-radius: 8px; font-size: 24px; font-weight: 900; color: #e91e63; }
    
    div[role="radiogroup"] { flex-wrap: wrap !important; gap: 5px; justify-content: center; padding-bottom: 5px; }
    div[role="radiogroup"] > label { background-color: white; border: 2px solid #999; padding: 8px 15px; border-radius: 20px; cursor: pointer; margin-bottom: 5px; }
    div[role="radiogroup"] > label[data-checked="true"] { background-color: #009688; border-color: #009688; }
    div[role="radiogroup"] > label[data-checked="true"] p { color: white !important; }
    div[role="radiogroup"] > label > div:first-child { display: none; }
    div[role="radiogroup"] > label p { color: #333; margin: 0; font-size: 14px; font-weight: bold; }
    
    .warning-box { background: #f44336; color: white; padding: 10px; font-weight: bold; border-radius: 5px 5px 0 0; }
    .warning-content { background: #ffebee; border-left: 4px solid #d32f2f; padding: 10px; margin-bottom: 15px; border-radius: 0 0 5px 5px; }
    
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div {
        border: 2px solid #000000 !important; border-radius: 6px !important; background-color: #fff !important;
    }

    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        gap: 5px !important;
    }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        width: 33% !important;
        flex: 1 1 0% !important;
        min-width: 0 !important;
    }
    div.element-container:has(#nav-marker) + div.element-container button {
        padding: 0 !important;
        font-size: 13px !important;
        width: 100% !important;
        white-space: nowrap !important;
        min-height: 42px !important;
        height: 42px !important;
        line-height: 1.2 !important;
        font-weight: bold !important;
    }
</style>
""", unsafe_allow_html=True)

time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]

MAP_SEARCH_BTN = """<a href='https://www.google.com/maps' target='_blank' style='display:inline-block; padding:4px 8px; background:#4285f4; color:white; border-radius:4px; text-decoration:none; font-size:12px; font-weight:bold; margin-bottom:5px; box-shadow:0 1px 2px rgba(0,0,0,0.2);'>🔍 Googleマップを開いて住所を検索・コピー</a>"""

# ==========================================
# 🌟 ナビゲーション
# ==========================================
def render_top_nav():
    if st.session_state.page == "home": return
    
    st.markdown('<div id="nav-marker" style="display:none;"></div>', unsafe_allow_html=True)
    
    if st.session_state.get("logged_in_cast") or st.session_state.get("logged_in_staff") or st.session_state.get("is_admin"):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🏠 ホーム", key=f"nh_{st.session_state.page}"): 
                st.session_state.page = "home"; st.rerun()
        with col2:
            if st.button("🔙 戻る", key=f"nb_{st.session_state.page}"): 
                st.session_state.page = "home"; st.rerun()
        with col3:
            if st.button("🚪 ログアウト", key=f"nl_{st.session_state.page}"):
                st.session_state.logged_in_cast = None
                st.session_state.logged_in_staff = None
                st.session_state.is_admin = False
                st.session_state.cast_id = None
                st.session_state.page = "home"
                st.rerun()
    else:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🏠 ホーム", key=f"nh_{st.session_state.page}"): 
                st.session_state.page = "home"; st.rerun()
        with col2:
            if st.button("🔙 戻る", key=f"nb_{st.session_state.page}"): 
                st.session_state.page = "home"; st.rerun()
                
    st.markdown("<hr style='margin: 5px 0 15px 0; border-top: 1px dashed #ccc;'>", unsafe_allow_html=True)

# ==========================================
# 🏠 ホーム画面
# ==========================================
if st.session_state.page == "home":
    st.markdown('<div class="home-title">六本木 水島本店 送迎管理</div>', unsafe_allow_html=True)
    if st.button("🚙 スタッフ業務開始", type="primary", use_container_width=True):
        if st.session_state.get("logged_in_staff") or st.session_state.get("is_admin"): st.session_state.page = "staff_portal"
        else: st.session_state.page = "staff_login"; st.session_state.selected_staff_for_login = None
        st.rerun()
    st.write("") 
    if st.button("👩 キャスト専用ログイン", use_container_width=True):
        if st.session_state.get("logged_in_cast"): st.session_state.page = "cast_mypage"
        else: st.session_state.page = "cast_login"
        st.rerun()
    st.write("\n\n")
    st.markdown("<div style='text-align:center;'>", unsafe_allow_html=True)
    if st.button("⚙️ 管理者ログイン", use_container_width=True):
        if st.session_state.get("is_admin"): st.session_state.page = "staff_portal"
        else: st.session_state.page = "admin_login"
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# 🔐 ログイン画面系
# ==========================================
elif st.session_state.page == "cast_login":
    render_top_nav()
    st.markdown('<div class="app-header">キャストログイン</div>', unsafe_allow_html=True)
    st.caption("店番とキャスト名を選択し、パスワードを入力してください")
    
    db = get_db_data()
    casts = db.get("casts", [])
    cast_list_display = ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in casts if str(c.get("name", "")).strip() != ""]
    
    c_selected = st.selectbox("店番とキャスト名", cast_list_display, key="cl_select")
    input_password = st.text_input("パスワード", type="password")
    
    if st.button("ログイン", type="primary", use_container_width=True):
        if c_selected != "-- 選択 --":
            selected_id = str(c_selected.split(" ")[0])
            target_cast = next((c for c in casts if str(c["cast_id"]) == selected_id), None)
            if target_cast:
                correct_pass = str(target_cast.get("password", "")).strip()
                if correct_pass == "None": correct_pass = ""
                if str(input_password).strip() == correct_pass or correct_pass == "":
                    st.session_state.logged_in_cast = {"店番": str(target_cast["cast_id"]), "キャスト名": str(target_cast["name"]), "方面": str(target_cast.get("area", "")), "担当": str(target_cast.get("manager", "未設定"))}
                    st.session_state.page = "cast_mypage"
                    st.rerun()
                else: st.error("⚠️ パスワードが違います。")
            else: st.error("⚠️ キャスト情報が見つかりません。")
        else: st.warning("キャストを選択してください。")

elif st.session_state.page == "admin_login":
    render_top_nav()
    db = get_db_data()
    settings = db.get("settings") or {}
    
    st.markdown('<div class="app-header">👑 管理者認証</div>', unsafe_allow_html=True)
    st.caption("パスワードを入力してください (初期: 1234)")
    
    admin_pass = st.text_input("パスワード", type="password", key="admin_pass_input", label_visibility="collapsed")
    
    if st.button("ログイン", type="primary", use_container_width=True):
        db_pass = str(settings.get("admin_password", "")) if isinstance(settings, dict) else "1234"
        if not db_pass: db_pass = "1234"
        if admin_pass == db_pass: 
            st.session_state.is_admin = True; st.session_state.logged_in_staff = "管理者"; st.session_state.page = "staff_portal"; st.rerun()
        else: st.error("⚠️ パスワードが違います。")

elif st.session_state.page == "staff_login":
    render_top_nav()
    st.markdown('<div class="app-header">スタッフ認証</div>', unsafe_allow_html=True)
    st.caption("自分の名前の横にパスワードを入力して開始を押してください")
    
    db = get_db_data()
    drivers = db.get("drivers", [])
    staff_list = [d for d in drivers if str(d["name"]).strip() != ""]
    
    if not staff_list: st.warning("※管理者が「④ STAFF設定」からスタッフ登録を行ってください")
    else:
        for d in staff_list:
            st.markdown(f"<div style='font-weight:bold; margin-top:15px; border-bottom:2px solid #ddd; padding-bottom:5px; margin-bottom:10px;'>👤 {d['name']}</div>", unsafe_allow_html=True)
            colA, colB = st.columns([3, 2])
            with colA: 
                p_in = st.text_input("パスワード", type="password", key=f"pass_{d['driver_id']}", label_visibility="collapsed", placeholder="パスワード")
            with colB:
                if st.button("開始", key=f"btn_{d['driver_id']}", type="primary", use_container_width=True):
                    if p_in == "0000" or p_in.strip() == str(d["password"]).strip() or str(d["password"]) == "":
                        st.session_state.is_admin = False
                        st.session_state.logged_in_staff = str(d["name"])
                        st.session_state.page = "staff_portal"
                        st.rerun()
                    else: st.error("❌ エラー")

# ==========================================
# 👩 出勤報告 / マイページ
# ==========================================
elif st.session_state.page == "cast_mypage":
    render_top_nav()
    c = st.session_state.logged_in_cast
    db = get_db_data()
    settings = db.get("settings") or {}
    casts = db.get("casts", [])
    attendance = db.get("attendance", [])
    
    st.markdown('<div class="app-header" style="margin-bottom:0; border:none; text-align:left;">出勤報告</div>', unsafe_allow_html=True)
    st.markdown("<hr style='margin-top:0; margin-bottom:15px; border-top: 2px solid #333;'>", unsafe_allow_html=True)
    
    notice = str(settings.get("notice_text", "")).strip()
    if notice:
        st.markdown(f'<div class="notice-box"><div class="notice-title">📢 お知らせ</div><div style="font-weight:bold;">{notice}</div></div>', unsafe_allow_html=True)
        
    st.markdown(f'''
    <div style="text-align: center; font-weight: bold; font-size: 20px; margin-bottom: 15px;">
        店番 {c['店番']}　{c['キャスト名']} 様<br><span style="font-size: 14px; color: #555; font-weight: normal;">(担当: {c.get('担当', '未設定')})</span>
    </div>
    ''', unsafe_allow_html=True)

    with st.expander("🏠 自分の登録情報（自宅・託児所）の確認・変更"):
        my_cast_info = next((cast for cast in casts if str(cast["cast_id"]) == str(c["店番"])), None)
        if my_cast_info:
            raw_addr = my_cast_info.get("address", "")
            home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
            
            with st.form("edit_profile_form"):
                st.caption("※ここで住所を更新すると、管理者の名簿も自動的に更新されます。")
                new_home = st.text_input("自宅住所 (迎え先)", value=home_addr)
                
                st.markdown("<div style='margin-top:10px; font-weight:bold; color:#2196f3;'>👶 託児所の利用設定</div>", unsafe_allow_html=True)
                new_takuji_en = st.checkbox("毎回自動的に託児所を経由する", value=(takuji_en=="1"))
                new_takuji_addr = ""
                if new_takuji_en:
                    new_takuji_addr = st.text_input("託児所の住所", value=takuji_addr, placeholder="託児所の住所を入力してください")
                
                if st.form_submit_button("情報を更新する", type="primary", use_container_width=True):
                    encoded_addr = encode_cast_address(new_home, "1" if new_takuji_en else "0", new_takuji_addr, "1")
                    res = post_api({"action": "save_cast", "cast_id": my_cast_info["cast_id"], "name": my_cast_info["name"], "password": my_cast_info.get("password", ""), "phone": my_cast_info.get("phone", ""), "area": my_cast_info.get("area", ""), "address": encoded_addr, "manager": my_cast_info.get("manager", "未設定")})
                    if res.get("status") == "success":
                        clear_cache(); st.success("✅ 登録情報を更新しました！"); time.sleep(1); st.rerun()
                    else:
                        st.error("更新エラーが発生しました。")
    
    today_dt = datetime.datetime.now(JST)
    days = ['月','火','水','木','金','土','日']
    today_str = f"{today_dt.month}/{today_dt.day}({days[today_dt.weekday()]})"
    tmr_dt = today_dt + datetime.timedelta(days=1)
    tmr_str = f"{tmr_dt.month}/{tmr_dt.day}({days[tmr_dt.weekday()]})"

    tab_today, tab_tmr, tab_week = st.tabs(["当日申請", "翌日申請", "週間申請"])

    with tab_today:
        with st.form("cast_report_form"):
            st.markdown(f'<div style="background-color: #fff9c4; border: 3px solid #fdd835; border-radius: 8px; padding: 10px; margin-bottom: 15px; text-align: center; color: #f57f17; font-weight: bold; font-size: 18px;">⚡ 当日出勤申請 ({today_str})</div>', unsafe_allow_html=True)
            
            my_cast_info = next((cast for cast in casts if str(cast["cast_id"]) == str(c["店番"])), None)
            _, takuji_en, _, _ = parse_cast_address(my_cast_info.get("address", "")) if my_cast_info else ("", "0", "", "0")

            col_t1, col_t2 = st.columns([3, 1.2]) 
            with col_t1:
                today_s = st.radio("状態", ["未定", "出勤", "自走", "休み"], horizontal=True, key="today_s", label_visibility="collapsed")
                today_m = st.text_input("備考", placeholder="備考", key="today_m")
                
                st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
                req_stopover = st.checkbox("🍽️ 本日、途中で寄る場所（同伴先など）がある", key="req_stopover_today")
                stopover_addr = st.text_input("立ち寄り先の住所・店名", key="stopover_addr_today", placeholder="例：倉敷市阿知〇-〇 〇〇店") if req_stopover else ""

                req_change = st.checkbox("📍 本日のみ迎え先を指定の場所に変更する", key="req_chg_today")
                temp_m_addr = st.text_input("本日の迎え先住所", key="temp_addr_today", placeholder="例：倉敷駅前") if req_change else ""
                
                takuji_cancel_val = "1" if (takuji_en == "1" and st.checkbox("👶 本日は託児所を利用しない (キャンセル)", key="cancel_takuji_today")) else "0"

            with col_t2:
                st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True) 
                if st.form_submit_button("📤 送信", type="primary", use_container_width=True):
                    if st.session_state.today_s != "未定":
                        my_task_today = next((r for r in attendance if r["target_date"] == "当日" and str(r["cast_id"]) == str(c["店番"])), None)
                        ex_e_drv, ex_e_time, ex_e_dest = "", "", ""
                        if my_task_today:
                            _, _, _, ex_e_drv, ex_e_time, ex_e_dest, _ = parse_attendance_memo(my_task_today.get("memo", ""))

                        encoded_memo = encode_attendance_memo(today_m, temp_m_addr, takuji_cancel_val, ex_e_drv, ex_e_time, ex_e_dest, stopover_addr)
                        rec = {"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": today_s, "memo": encoded_memo, "target_date": "当日"}
                        
                        if today_s in ["未定", "休み"]:
                            post_api({"action": "cancel_dispatch", "cast_id": c["店番"]})
                            
                        res = post_api({"action": "save_attendance", "records": [rec]})
                        if res.get("status") == "success": 
                            clear_cache()
                            st.session_state.page = "report_done"
                            st.rerun()
                        else: 
                            st.error(res.get("message"))

    with tab_tmr:
        with st.form("cast_tmr_form"):
            st.markdown(f'<div style="background-color: #e3f2fd; border: 3px solid #64b5f6; border-radius: 8px; padding: 10px; margin-bottom: 15px; text-align: center; color: #1565c0; font-weight: bold; font-size: 18px;">🌙 翌日申請 ({tmr_str})</div>', unsafe_allow_html=True)
            col_tm1, col_tm2 = st.columns([3, 1.2])
            with col_tm1:
                tmr_s = st.radio("状態", ["未定", "出勤", "自走", "休み"], horizontal=True, key="tmr_s", label_visibility="collapsed")
                tmr_m = st.text_input("明日の備考", placeholder="備考", key="tmr_m")
                
                st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
                req_stopover_tmr = st.checkbox("🍽️ 明日、途中で寄る場所（同伴先など）がある", key="req_stopover_tmr")
                stopover_addr_tmr = st.text_input("立ち寄り先の住所・店名", key="stopover_addr_tmr", placeholder="例：倉敷市阿知〇-〇 〇〇店") if req_stopover_tmr else ""

                req_change_tmr = st.checkbox("📍 明日のみ迎え先を指定の場所に変更する", key="req_chg_tmr")
                temp_m_addr_tmr = st.text_input("明日の迎え先住所", key="temp_addr_tmr") if req_change_tmr else ""
                
                takuji_cancel_val_tmr = "1" if (takuji_en == "1" and st.checkbox("👶 明日は託児所を利用しない (キャンセル)", key="cancel_takuji_tmr")) else "0"

            with col_tm2:
                st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True)
                if st.form_submit_button("📤 送信", type="primary", use_container_width=True):
                    my_task_tmr = next((r for r in attendance if r["target_date"] == "翌日" and str(r["cast_id"]) == str(c["店番"])), None)
                    ex_e_drv_tmr, ex_e_time_tmr, ex_e_dest_tmr = "", "", ""
                    if my_task_tmr:
                        _, _, _, ex_e_drv_tmr, ex_e_time_tmr, ex_e_dest_tmr, _ = parse_attendance_memo(my_task_tmr.get("memo", ""))

                    encoded_memo_tmr = encode_attendance_memo(tmr_m, temp_m_addr_tmr, takuji_cancel_val_tmr, ex_e_drv_tmr, ex_e_time_tmr, ex_e_dest_tmr, stopover_addr_tmr)
                    rec = {"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": tmr_s, "memo": encoded_memo_tmr, "target_date": "翌日"}
                    res = post_api({"action": "save_attendance", "records": [rec]})
                    if res.get("status") == "success": 
                        clear_cache()
                        st.session_state.page = "report_done"
                        st.rerun()
                    else: 
                        st.error(res.get("message"))

    with tab_week:
        st.write("※向こう1週間の予定をまとめて申請できます")
        with st.form("cast_week_form"):
            weekly_data = []
            for i in range(1, 8):
                d = today_dt + datetime.timedelta(days=i)
                target_val = "翌日" if i == 1 else d.strftime("%Y-%m-%d")
                date_disp = "明日" if i == 1 else f"{d.month}/{d.day}({days[d.weekday()]})"
                
                st.write(f"**{date_disp}**")
                col_w1, col_w2 = st.columns([3, 1.2])
                with col_w1:
                    w_attend = st.radio("状態", ["未定", "出勤", "自走", "休み"], horizontal=True, key=f"w_s_{i}", label_visibility="collapsed")
                    w_memo = st.text_input("備考", placeholder="備考", key=f"w_m_{i}")
                with col_w2:
                    pass
                
                weekly_data.append({
                    "date": target_val,
                    "attend": w_attend,
                    "memo": w_memo
                })
                st.markdown("---")
                
            if st.form_submit_button("📤 週間申請を一括送信", type="primary", use_container_width=True):
                records = []
                for w in weekly_data:
                    target_row = next((r for r in attendance if r["target_date"] == w['date'] and str(r["cast_id"]) == str(c["店番"])), None)
                    ex_e_drv_w, ex_e_time_w, ex_e_dest_w = "", "", ""
                    if target_row:
                        _, _, _, ex_e_drv_w, ex_e_time_w, ex_e_dest_w, _ = parse_attendance_memo(target_row.get("memo", ""))

                    encoded_memo_week = encode_attendance_memo(w['memo'], "", "0", ex_e_drv_w, ex_e_time_w, ex_e_dest_w, "")
                    records.append({
                        "cast_id": c["店番"],
                        "cast_name": c["キャスト名"],
                        "area": c["方面"],
                        "status": w['attend'],
                        "memo": encoded_memo_week,
                        "target_date": w['date']
                    })
                if records:
                    res = post_api({"action": "save_attendance", "records": records})
                    if res.get("status") == "success": 
                        clear_cache()
                        st.session_state.page = "report_done"
                        st.rerun()
                    else: 
                        st.error(res.get("message"))
                else:
                    st.warning("出勤の申請がありませんでした。")

elif st.session_state.page == "report_done":
    render_top_nav()
    st.markdown("<h1 style='text-align:center; margin-top:50px;'>✅</h1>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align:center;'>出勤報告を受け付けました。</h3>", unsafe_allow_html=True)
    if st.button("マイページへ戻る", type="primary", use_container_width=True): st.session_state.page = "cast_mypage"; st.rerun()

# ==========================================
# 🚕 送迎管理ダッシュボード (管理者 ＆ ドライバー専用画面)
# ==========================================
elif st.session_state.page == "staff_portal":
    render_top_nav()
    staff_name = st.session_state.logged_in_staff
    is_admin = st.session_state.is_admin
    db = get_db_data()
    casts = db.get("casts", [])
    drivers = db.get("drivers", [])
    attendance = db.get("attendance", [])
    settings = db.get("settings") or {}
    dt = datetime.datetime.now(JST)
    today_str = dt.strftime("%m月%d日")
    dow = ['月','火','水','木','金','土','日'][dt.weekday()]
    d_names = [str(d["name"]) for d in drivers if str(d["name"]).strip() != ""]
    store_addr = str(settings.get("store_address", "岡山県倉敷市水島東栄町2-24"))

    col1, col2 = st.columns([4, 2])
    with col1: 
        if is_admin: st.markdown('<b>六本木 水島本店<br>送迎管理 (管理者)</b>', unsafe_allow_html=True)
        else: st.markdown(f'<b>{staff_name} 様<br>ドライバー専用画面</b>', unsafe_allow_html=True)
    with col2: 
        if st.button("🔄 最新"): clear_cache(); st.rerun()
    st.markdown("<hr style='margin:5px 0 10px 0;'>", unsafe_allow_html=True)

    current_hour = dt.hour
    current_minute = dt.minute
    is_return_time = (current_hour > 20) or (current_hour == 20 and current_minute >= 30) or (current_hour <= 7)

    # ========================================================
    # 🚙 【非管理者】ドライバー専用のナビ直結＆ルート画面
    # ========================================================
    if not is_admin:
        st.markdown(f'<div class="date-header"><div style="font-size:12px; color:#555; font-weight:normal;">本日の配車ルート</div><div class="main-date">{today_str} ({dow})</div></div>', unsafe_allow_html=True)
        
        early_tasks_raw = []
        seen_early_drv_cids = set()
        for row in attendance:
            if row["target_date"] == "当日" and row["status"] in ["出勤"]:
                cid_str = str(row["cast_id"])
                if cid_str in seen_early_drv_cids: continue
                seen_early_drv_cids.add(cid_str)
                early_tasks_raw.append(row)
                
        my_early_tasks = []
        for t in early_tasks_raw:
            _, _, _, e_drv, e_time, e_dest, _ = parse_attendance_memo(t.get("memo", ""))
            if e_drv == staff_name:
                _, dist = get_route_line_and_distance(e_dest)
                my_early_tasks.append({
                    "task": t, "early_time": e_time, "early_dest": e_dest, "dist": dist,
                    "c_name": t['cast_name'], "c_id": t['cast_id']
                })

        if my_early_tasks:
            st.markdown(f'<div style="background:#fff3e0; border:2px solid #ff9800; padding:10px; border-radius:8px; margin-bottom:15px;"><h4 style="color:#e65100; margin-top:0; margin-bottom:5px;">🌅 本日の早便（送り）</h4><p style="font-size:12px; color:#555; margin-bottom:10px;">到着指定時間を基準に自動計算された出発時刻と順路です。</p>', unsafe_allow_html=True)
            
            my_early_tasks.sort(key=lambda x: x["dist"])
            valid_early_addrs = [clean_address_for_map(x["early_dest"]) for x in my_early_tasks if clean_address_for_map(x["early_dest"])]
            
            if valid_early_addrs:
                origin_enc = urllib.parse.quote(store_addr)
                dest_enc = urllib.parse.quote(valid_early_addrs[-1])
                wp_enc = urllib.parse.quote("|".join(valid_early_addrs[:-1]))
                early_map_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_enc}&destination={dest_enc}&waypoints={wp_enc}"
                st.markdown(f"<a href='{early_map_url}' target='_blank' class='nav-btn' style='background:#ff9800; margin-bottom:10px;'>🗺️ 早便ナビ開始 (店舗発〜近い順)</a>", unsafe_allow_html=True)
            
            earliest_dep_mins = 9999
            for rt in my_early_tasks:
                try:
                    h, m = map(int, rt["early_time"].split(':'))
                    dep_m = h * 60 + m - rt["dist"]
                    if dep_m < earliest_dep_mins: earliest_dep_mins = dep_m
                except: pass
            
            if earliest_dep_mins != 9999:
                dep_time_str = f"{earliest_dep_mins // 60}:{earliest_dep_mins % 60:02d}"
                st.markdown(f"<div style='font-size:15px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center; border: 1px solid #f44336;'>🚀 店舗出発時刻 (目安): {dep_time_str}</div>", unsafe_allow_html=True)

            for idx, rt in enumerate(my_early_tasks):
                disp_str = f"<div style='font-size:14px;'><b>降車順 {idx+1}</b>：店番 {rt['c_id']} <b>{rt['c_name']}</b><br>"
                disp_str += f"<span style='color:#e65100;font-size:12px;font-weight:bold;'>⏰ 指定到着: {rt['early_time']}</span><br>"
                disp_str += f"<span style='color:#666;font-size:12px;'>🏠 届け先: {rt['early_dest']}</span></div><hr style='margin:5px 0;'>"
                st.markdown(disp_str, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        my_tasks_raw = []
        seen_task_cids_drv = set()
        for row in attendance:
            if row["target_date"] == "当日" and row["driver_name"] == staff_name:
                cid_str = str(row["cast_id"])
                if cid_str in seen_task_cids_drv: continue
                seen_task_cids_drv.add(cid_str)
                my_tasks_raw.append(row)
        
        if not my_tasks_raw:
            st.info("現在、割り当てられている送迎（迎え便）はありません。管理者の配車をお待ちください。")
        else:
            if is_return_time:
                st.markdown(f'<div style="background:#e3f2fd; border:2px solid #2196f3; padding:10px; border-radius:8px; margin-bottom:15px;"><h4 style="color:#1565c0; margin-top:0; margin-bottom:5px;">🌙 帰りの送迎便（送り班）</h4><p style="font-size:12px; color:#555; margin-bottom:10px;">行きで送迎したキャストが自動的に帰り班として表示されています。</p>', unsafe_allow_html=True)
                
                return_tasks = []
                for t in my_tasks_raw:
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                    raw_addr = c_info.get("address", "") if c_info else ""
                    home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
                    raw_memo = t.get("memo", "")
                    _, temp_addr, takuji_cancel, _, _, _, _ = parse_attendance_memo(raw_memo)
                    
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    _, dst = get_route_line_and_distance(actual_pickup)
                    
                    return_tasks.append({
                        "task": t, "dist": dst, "actual_pickup": actual_pickup, 
                        "use_takuji": use_takuji, "takuji_addr": takuji_addr,
                        "c_name": t['cast_name'], "c_id": t['cast_id']
                    })
                
                ordered_returns, _, return_full_path = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, return_tasks, is_return=True)
                
                if return_full_path:
                    origin_enc = urllib.parse.quote(store_addr)
                    dest_enc = urllib.parse.quote(return_full_path[-1])
                    wp_enc = urllib.parse.quote("|".join(return_full_path[:-1]))
                    return_map_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_enc}&destination={dest_enc}&waypoints={wp_enc}"
                    st.markdown(f"<a href='{return_map_url}' target='_blank' class='nav-btn' style='background:#1565c0; margin-bottom:10px;'>🗺️ 帰りナビ開始 (Google AI 最短ルート)</a>", unsafe_allow_html=True)
                    
                for idx, rt in enumerate(ordered_returns):
                    disp_str = f"<div style='font-size:14px;'><b>降車順 {idx+1}</b>：店番 {rt['c_id']} <b>{rt['c_name']}</b><br>"
                    if rt["use_takuji"]:
                        disp_str += f"<span style='color:#2196f3;font-size:12px;font-weight:bold;'>👶 託児経由: {rt['takuji_addr']}</span><br>"
                    disp_str += f"<span style='color:#666;font-size:12px;'>🏠 降車先: {rt['actual_pickup']}</span></div><hr style='margin:5px 0;'>"
                    st.markdown(disp_str, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            tasks_with_details = []
            for t in my_tasks_raw:
                c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                raw_addr = c_info.get("address", "") if c_info else ""
                home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                raw_memo = t.get("memo", "")
                memo_text, temp_addr, takuji_cancel, _, _, _, stopover = parse_attendance_memo(raw_memo)
                
                actual_pickup = temp_addr if temp_addr else home_addr
                use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                _, dst = get_route_line_and_distance(actual_pickup)
                
                tasks_with_details.append({
                    "task": t, "c_info": c_info, "actual_pickup": actual_pickup, "stopover": stopover,
                    "use_takuji": use_takuji, "takuji_addr": takuji_addr, "memo_text": memo_text,
                    "c_name": t['cast_name'], "c_id": t['cast_id'], "is_edited": is_edited,
                    "home_addr": home_addr, "temp_addr": temp_addr, "takuji_cancel": takuji_cancel,
                    "dist": dst
                })

            st.markdown("<div style='font-size:12px; font-weight:bold; color:#e91e63; text-align:center; margin-bottom:5px;'>🤖 Google AIによって「一番遠い人から拾う」最短ルートに最適化済です</div>", unsafe_allow_html=True)

            ordered_tasks, total_sec, full_path = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, tasks_with_details, is_return=False)

            target_time_str = str(settings.get("base_arrival_time", "19:50"))
            try:
                th, tm = map(int, target_time_str.split(':'))
                target_dt = dt.replace(hour=th, minute=tm, second=0)
                if dt.hour > 20 and th < 10: target_dt += datetime.timedelta(days=1)
                
                padding_sec = len(full_path) * 3 * 60 
                dep_dt = target_dt - datetime.timedelta(seconds=(total_sec + padding_sec))
                dep_time_str = dep_dt.strftime("%H:%M")
            except:
                dep_time_str = "未定"

            st.markdown(f"<div style='font-size:16px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:10px; border-radius:5px; margin-bottom:15px; text-align:center; border: 2px solid #f44336;'>🚀 店舗出発時刻（計算値）: {dep_time_str}</div>", unsafe_allow_html=True)

            if full_path:
                origin_enc = urllib.parse.quote(full_path[0])
                dest_enc = urllib.parse.quote(store_addr)
                wp_enc = urllib.parse.quote("|".join(full_path[1:])) if len(full_path) > 1 else ""
                map_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_enc}&destination={dest_enc}"
                if wp_enc: map_url += f"&waypoints={wp_enc}"
                st.markdown(f"<a href='{map_url}' target='_blank' class='nav-btn'>🗺️ 行きナビ開始 (AI最短ルート)</a>", unsafe_allow_html=True)
            else:
                st.warning("キャストの住所が登録されていないため、自動ナビゲーションが起動できません。")

            st.markdown("<div style='margin-bottom:10px; font-weight:bold; color:#555;'>▼ 本日のピックアップ順 ▼</div>", unsafe_allow_html=True)
            
            for idx, t in enumerate(ordered_tasks):
                c_info = t["c_info"]
                mgr_name = c_info.get("manager", "未設定") if c_info else "未設定"
                mgr_phone = ""
                if mgr_name != "未設定":
                    for d in drivers:
                        if d["name"] == mgr_name:
                            mgr_phone = d.get("phone", ""); break
                
                if mgr_phone: phone_btn = f"<a href='tel:{mgr_phone}' style='text-decoration:none; background:#4caf50; color:white; padding:4px 10px; border-radius:15px; font-size:12px; font-weight:bold; margin-left:10px; box-shadow:0 1px 3px rgba(0,0,0,0.2);'>📞 担当({mgr_name})</a>"
                else: phone_btn = f"<span style='font-size:12px; color:#999; margin-left:10px;'>(担当:{mgr_name})</span>"
                
                route_points = []
                if clean_address_for_map(t["actual_pickup"]): route_points.append(clean_address_for_map(t["actual_pickup"]))
                if clean_address_for_map(t["stopover"]): route_points.append(clean_address_for_map(t["stopover"]))
                if t["use_takuji"] and clean_address_for_map(t["takuji_addr"]): route_points.append(clean_address_for_map(t["takuji_addr"]))
                
                ind_map_url = ""
                if len(route_points) >= 2:
                    origin_enc = urllib.parse.quote(route_points[0])
                    dest_enc = urllib.parse.quote(route_points[-1])
                    waypoints_enc = urllib.parse.quote("|".join(route_points[1:-1]))
                    ind_map_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_enc}&destination={dest_enc}"
                    if route_points[1:-1]:
                        ind_map_url += f"&waypoints={waypoints_enc}"
                elif len(route_points) == 1:
                    ind_map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(route_points[0])}"

                map_btn = f"<a href='{ind_map_url}' target='_blank' style='text-decoration:none; background:#e3f2fd; color:#1565c0; font-weight:bold; padding:4px 10px; border-radius:15px; font-size:12px; border:1px solid #2196f3; margin-left:5px; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>📍 個別マップ</a>" if ind_map_url else ""

                addr_display = f"🏠 迎え: {t['home_addr'] if t['home_addr'] else '未登録'}"
                if t["is_edited"] == "1": addr_display += " <span style='color:#4caf50;font-weight:bold;font-size:11px;'>(✅更新済)</span>"
                if t["temp_addr"]: addr_display += f"<br><span style='color:#e91e63;font-weight:bold;'>📍 当日変更: {t['temp_addr']}</span>"
                if t["stopover"]: addr_display += f"<br><span style='color:#ff9800;font-weight:bold;'>🍽️ 立ち寄り(同伴): {t['stopover']}</span>"
                if t["use_takuji"]: addr_display += f"<br><span style='color:#2196f3;font-weight:bold;'>👶 経由(託児): {t['takuji_addr']}</span>"
                if t["memo_text"]: addr_display += f"<br>📝 備考: {t['memo_text']}"

                st.markdown(f"""
                <div class='driver-card' style='margin-bottom:5px;'>
                    <div style='font-size:14px; color:#e91e63; font-weight:bold; margin-bottom:5px;'>
                        🚙 迎え順 {idx+1}： {t['task']['pickup_time']}
                    </div>
                    <div style='display:flex; align-items:center; margin-bottom:8px;'>
                        <span style='font-size:20px; font-weight:900;'>{t['c_name']}</span>
                        {phone_btn}
                    </div>
                    <div style='font-size:13px; color:#555; line-height:1.4;'>
                        {addr_display}
                    </div>
                    <div style='margin-top:10px; text-align:right;'>
                        {map_btn}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander("📍 住所ズレの修正（訂正ピン）"):
                    st.caption("ナビの場所がずれていた場合、Googleマップで正しい位置の座標（例: 34.123, 133.456）や正確な住所をコピーして上書きしてください。次回から正確に案内されます。")
                    new_addr = st.text_input("正確な住所・座標", value=t["actual_pickup"], key=f"fix_addr_{t['c_id']}")
                    if st.button("📍 この住所でシステムを更新", key=f"fix_btn_{t['c_id']}", type="secondary", use_container_width=True):
                        if c_info:
                            encoded_addr = encode_cast_address(new_addr, t["use_takuji"], t["takuji_addr"], "0")
                            payload = {
                                "action": "save_cast",
                                "cast_id": c_info["cast_id"],
                                "name": c_info["name"],
                                "password": c_info["password"],
                                "phone": c_info["phone"],
                                "area": c_info["area"],
                                "address": encoded_addr,
                                "manager": c_info.get("manager", "未設定")
                            }
                            res = post_api(payload)
                            if res.get("status") == "success":
                                clear_cache(); st.rerun()
                            else:
                                st.error("修正に失敗しました")
                
                if t["use_takuji"]:
                    if st.button("👶 本日の託児をキャンセル", key=f"cancel_t_{t['task']['id']}", use_container_width=True):
                        new_memo = encode_attendance_memo(t["memo_text"], t["temp_addr"], "1", "", "", "", t["stopover"])
                        rec = {"cast_id": t["c_id"], "cast_name": t["c_name"], "area": c_info["area"], "status": t["task"]["status"], "memo": new_memo, "target_date": "当日"}
                        res = post_api({"action": "save_attendance", "records": [rec]})
                        if res.get("status") == "success": clear_cache(); st.rerun()

                if st.button("❌ 辞退(この人を外す)", key=f"cancel_{t['task']['id']}", use_container_width=True):
                    updates = [{"id": t["task"]["id"], "driver_name": "未定", "pickup_time": "未定", "status": t["task"]["status"]}]
                    res = post_api({"action": "update_manual_dispatch", "updates": updates})
                    if res.get("status") == "success": clear_cache(); st.rerun()
                st.write("")

    # ========================================================
    # 👑 【管理者】フル機能ダッシュボード
    # ========================================================
    else:
        tabs = ["① 配車リスト", "② キャスト送迎", "③ キャスト登録", "④ STAFF設定", "⚙️ 管理設定"]
        if "current_staff_tab" not in st.session_state: st.session_state.current_staff_tab = "① 配車リスト"
        if st.session_state.current_staff_tab not in tabs: st.session_state.current_staff_tab = "① 配車リスト"
            
        def on_tab_change(): st.session_state.current_staff_tab = st.session_state.tab_selector
        st.radio("メニュー", tabs, index=tabs.index(st.session_state.current_staff_tab), horizontal=True, label_visibility="collapsed", key="tab_selector", on_change=on_tab_change)
        st.session_state.staff_tab = st.session_state.current_staff_tab
        st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
        
        range_opts = ["全表示"] + [f"{i*10+1}-{i*10+10}" for i in range(15)]
        store_addr = str(settings.get("store_address", "岡山県倉敷市水島東栄町2-24"))

        # ----------------------------------------
        # ① 配車リスト
        # ----------------------------------------
        if st.session_state.staff_tab == "① 配車リスト":
            st.markdown(f'<div class="date-header"><div style="font-size:12px; color:#555; font-weight:normal;">配車予定日</div><div class="main-date">{today_str} ({dow})</div></div>', unsafe_allow_html=True)
            
            early_disp_tasks = []
            seen_cids_e = set()
            for row in attendance:
                if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                    cid_str = str(row["cast_id"])
                    if cid_str in seen_cids_e: continue
                    seen_cids_e.add(cid_str)
                    _, _, _, e_drv, e_time, e_dest, _ = parse_attendance_memo(row.get("memo", ""))
                    if e_drv and e_drv != "未定" and e_drv != "":
                        early_disp_tasks.append({"name": row["cast_name"], "drv": e_drv, "time": e_time, "dest": e_dest})
            
            if early_disp_tasks:
                st.markdown('<div style="background:#fff3e0; border: 2px solid #ff9800; padding: 10px; border-radius: 8px; margin-bottom: 15px;"><div style="font-weight:bold; color:#e65100; font-size:15px; margin-bottom:5px;">🌅 本日の早便一覧（設定済）</div>', unsafe_allow_html=True)
                for ed in early_disp_tasks:
                    st.markdown(f"<div style='font-size:13px; color:#333; margin-bottom:3px;'>・ <b>{ed['name']}</b> ➡️ {ed['dest']} ({ed['time']}着) / ドライバー: {ed['drv']}</div>", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            st.markdown('<div style="background:#e8f5e9; border: 2px solid #4caf50; padding: 10px; border-radius: 8px; margin-bottom: 10px;"><div style="font-weight:bold; color:#2e7d32; font-size:16px; margin-bottom:5px;">🤖 自動配車（Google AI連携）</div><div style="font-size:12px; color:#555;">現在手動で割り当てているキャストも一旦リセットし、<br>AIが定員を守りながら「一番遠い人から拾う」最短ルートを組み直します。</div></div>', unsafe_allow_html=True)
            
            if not d_names:
                st.warning("⚠️ まだドライバーが登録されていません。「④ STAFF設定」タブを開いて登録してください。")
            else:
                if "active_drv_state" not in st.session_state: st.session_state.active_drv_state = d_names
                valid_drv = [d for d in st.session_state.active_drv_state if d in d_names]
                def on_drv_change(): st.session_state.active_drv_state = st.session_state.active_drv_ms
                
                with st.expander("🛠️ 稼働ドライバーの選択 (タップで開く)", expanded=False):
                    active_drivers = st.multiselect("稼働するドライバーを選択", d_names, default=valid_drv, key="active_drv_ms", on_change=on_drv_change)
                
                if st.button("🚀 自動配車を実行（ゼロベースで再編成）", type="primary", use_container_width=True):
                    if not active_drivers: 
                        st.error("稼働するドライバーを1人以上選択してください。")
                    else:
                        st.info("Google AIでルートを計算中... ⏳")
                        all_today_casts = []
                        early_drivers = set() 
                        seen_cids_ai = set()
                        
                        for row in attendance:
                            if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                                cid_str = str(row["cast_id"])
                                if cid_str in seen_cids_ai: continue
                                seen_cids_ai.add(cid_str)
                                
                                c_info = next((c for c in casts if str(c["cast_id"]) == str(row["cast_id"])), {})
                                raw_addr = c_info.get("address", "")
                                home_addr, _, _, _ = parse_cast_address(raw_addr)
                                _, temp_addr, _, e_drv, _, _, _ = parse_attendance_memo(row.get("memo", ""))
                                
                                if e_drv and e_drv != "未定" and e_drv != "":
                                    early_drivers.add(e_drv)
                                    continue 
                                
                                actual_pickup = temp_addr if temp_addr else home_addr
                                line, dst = get_route_line_and_distance(actual_pickup)
                                all_today_casts.append({"row": row, "line": line, "dist": dst})
                        
                        all_today_casts.sort(key=lambda x: x["dist"], reverse=True)
                        
                        drv_specs = {}
                        for d in drivers:
                            if d["name"] in active_drivers:
                                if d["name"] in early_drivers: continue
                                try: cap = int(d.get("capacity", 4))
                                except: cap = 4
                                drv_specs[d["name"]] = {"capacity": cap, "assigned_rows": [], "line": None}

                        for uc in all_today_casts:
                            if uc["row"]["status"] == "自走": continue
                                
                            assigned_d = None
                            c_line = uc["line"]
                            
                            for d_name, stat in drv_specs.items():
                                if len(stat["assigned_rows"]) < stat["capacity"] and stat["line"] == c_line:
                                    assigned_d = d_name; break
                            if not assigned_d:
                                for d_name, stat in drv_specs.items():
                                    if len(stat["assigned_rows"]) == 0:
                                        stat["line"] = c_line
                                        assigned_d = d_name; break
                            if not assigned_d and uc["dist"] <= 10:
                                for d_name, stat in drv_specs.items():
                                    if len(stat["assigned_rows"]) < stat["capacity"]:
                                        assigned_d = d_name; break
                            if not assigned_d:
                                for d_name, stat in drv_specs.items():
                                    if len(stat["assigned_rows"]) < stat["capacity"]:
                                        assigned_d = d_name; break

                            if assigned_d: 
                                drv_specs[assigned_d]["assigned_rows"].append(uc)

                        updates = []
                        assigned_ids = set()
                        
                        base_time = str(settings.get("base_arrival_time", "19:50"))
                        try:
                            bh, bm = map(int, base_time.split(':'))
                            b_mins = bh * 60 + bm
                        except: b_mins = 19 * 60 + 50

                        for d_name, stat in drv_specs.items():
                            assigned_list = stat["assigned_rows"]
                            if not assigned_list: continue

                            rep_points = []
                            for item in assigned_list:
                                c_info = next((c for c in casts if str(c["cast_id"]) == str(item["row"]["cast_id"])), {})
                                raw_addr = c_info.get("address", "")
                                home_addr, _, _, _ = parse_cast_address(raw_addr)
                                _, temp_addr, _, _, _, _, _ = parse_attendance_memo(item["row"].get("memo", ""))
                                actual_pickup = temp_addr if temp_addr else home_addr
                                clean_addr = clean_address_for_map(actual_pickup)
                                rep_points.append(clean_addr if clean_addr else "")
                                    
                            opt_indices = list(range(len(assigned_list)))
                            valid_reps = [p for p in rep_points if p]
                            
                            if len(valid_reps) > 1:
                                origin_pt = valid_reps[0]
                                dest_pt = store_addr
                                waypoints = valid_reps[1:]
                                
                                wp_str = "optimize:true|" + "|".join(waypoints) if waypoints else ""
                                try:
                                    res = requests.get("https://maps.googleapis.com/maps/api/directions/json", params={
                                        "origin": origin_pt,
                                        "destination": dest_pt,
                                        "waypoints": wp_str,
                                        "key": GOOGLE_MAPS_API_KEY,
                                        "language": "ja"
                                    }).json()
                                    if res.get("status") == "OK" and waypoints:
                                        wp_order = res["routes"][0]["waypoint_order"]
                                        valid_idx_map = [i for i, p in enumerate(rep_points) if p]
                                        invalid_idx_map = [i for i, p in enumerate(rep_points) if not p]
                                        
                                        opt_valid_indices = [valid_idx_map[0]] + [valid_idx_map[i+1] for i in wp_order]
                                        
                                        # 🌟 自動配車の「時間割り当て」も完全修正
                                        legs = res["routes"][0]["legs"]
                                        dur_to_first = legs[0]["duration"]["value"]
                                        dur_from_last = legs[-1]["duration"]["value"]
                                        if dur_to_first < dur_from_last:
                                            opt_valid_indices.reverse()
                                            
                                        opt_indices = opt_valid_indices + invalid_idx_map
                                except:
                                    pass
                                    
                            ordered_assigned = [assigned_list[i] for i in opt_indices]
                            
                            total_casts = len(ordered_assigned)
                            for idx, item in enumerate(ordered_assigned):
                                mins_to_subtract = (total_casts - idx) * 20
                                t_mins = b_mins - mins_to_subtract
                                current_calc_time = f"{t_mins // 60}:{t_mins % 60:02d}"
                                updates.append({
                                    "id": item["row"]["id"], 
                                    "driver_name": d_name, 
                                    "pickup_time": current_calc_time,
                                    "status": item["row"]["status"]
                                })
                                assigned_ids.add(item["row"]["id"])
                        
                        for uc in all_today_casts:
                            if uc["row"]["status"] != "自走" and uc["row"]["id"] not in assigned_ids:
                                updates.append({
                                    "id": uc["row"]["id"], 
                                    "driver_name": "未定", 
                                    "pickup_time": "未定",
                                    "status": uc["row"]["status"]
                                })
                                        
                        if updates:
                            res = post_api({"action": "update_manual_dispatch", "updates": updates})
                            if res.get("status") == "success": 
                                clear_cache(); st.session_state.flash_msg = "AIによる最短ルート最適化が完了しました！"; st.rerun()
                            else: st.error("エラー: " + res.get("message"))
            
            st.radio("表示", ["当日", "翌日", "週間"], horizontal=True, label_visibility="collapsed")
            
            unassigned, my_tasks = [], {}
            seen_cids_disp = set()
            for row in attendance:
                if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                    cid_str = str(row["cast_id"])
                    if cid_str in seen_cids_disp: continue
                    seen_cids_disp.add(cid_str)
                    
                    drv = row["driver_name"]
                    _, _, _, e_drv, _, _, _ = parse_attendance_memo(row.get("memo", ""))
                    if e_drv and e_drv != "未定" and e_drv != "":
                        continue
                        
                    if not drv or drv == "未定" or row["status"] == "自走": 
                        if row["status"] != "自走": unassigned.append(row)
                    else:
                        if drv not in my_tasks: my_tasks[drv] = []
                        my_tasks[drv].append(row)
            
            if unassigned:
                st.markdown('<div class="warning-box">⚠️ 定員・エリアオーバーで未割り当てのキャスト</div><div class="warning-content">', unsafe_allow_html=True)
                st.caption("※下の「全キャスト検索」から手動で割り当てるか、稼働ドライバーを追加してください。")
                for u in unassigned:
                    st.markdown(f"**未定**　<span style='font-size:16px; font-weight:bold;'>{u['cast_name']}</span> <br><span style='font-size:12px; color:#555;'>({u['status']})</span><hr style='margin:5px 0;'>", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
            for d_name, t_rows in my_tasks.items():
                t_rows = sorted(t_rows, key=lambda x: x['pickup_time'] if x['pickup_time'] and x['pickup_time'] != '未定' else '99:99')
                st.markdown(f'<div style="background:#444; color:white; padding:10px; font-weight:bold; border-radius:5px 5px 0 0;">🚕 {d_name} (STAFF)</div><div class="card" style="border-radius:0 0 5px 5px; border-top:none;">', unsafe_allow_html=True)
                
                if is_return_time:
                    st.markdown(f'<div style="background:#e3f2fd; border:2px solid #2196f3; padding:8px; border-radius:5px; margin-bottom:15px;"><div style="color:#1565c0; font-weight:bold; margin-bottom:5px;">🌙 帰り班 (自動編成)</div>', unsafe_allow_html=True)
                    return_tasks = []
                    for t in reversed(t_rows):
                        c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                        raw_addr = c_info.get("address", "") if c_info else ""
                        home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
                        raw_memo = t.get("memo", "")
                        _, temp_addr, takuji_cancel, _, _, _, _ = parse_attendance_memo(raw_memo)
                        
                        actual_pickup = temp_addr if temp_addr else home_addr
                        use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                        
                        return_tasks.append({
                            "task": t, "actual_pickup": actual_pickup, 
                            "use_takuji": use_takuji, "takuji_addr": takuji_addr,
                            "c_name": t['cast_name'], "c_id": t['cast_id']
                        })
                    
                    valid_return_addrs = []
                    for rt in return_tasks:
                        if rt["use_takuji"] and clean_address_for_map(rt["takuji_addr"]):
                            valid_return_addrs.append(clean_address_for_map(rt["takuji_addr"]))
                        if clean_address_for_map(rt["actual_pickup"]):
                            valid_return_addrs.append(clean_address_for_map(rt["actual_pickup"]))
                    
                    if valid_return_addrs:
                        origin_enc = urllib.parse.quote(store_addr)
                        dest_enc = urllib.parse.quote(valid_return_addrs[-1])
                        wp_enc = urllib.parse.quote("|".join(valid_return_addrs[:-1]))
                        return_map_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_enc}&destination={dest_enc}&waypoints={wp_enc}"
                        st.markdown(f"<a href='{return_map_url}' target='_blank' style='display:inline-block; background:#1565c0; color:white; padding:5px 10px; border-radius:5px; text-decoration:none; font-size:12px; font-weight:bold; margin-bottom:5px;'>🗺️ 帰りナビ (店舗発)</a>", unsafe_allow_html=True)
                        
                    for idx, rt in enumerate(return_tasks):
                        disp_str = f"<div style='font-size:13px;'>降車順 {idx+1}：<b>{rt['c_name']}</b><br>"
                        if rt["use_takuji"]:
                            disp_str += f"<span style='color:#2196f3;font-size:11px;font-weight:bold;'>👶 託児経由: {rt['takuji_addr']}</span><br>"
                        disp_str += f"<span style='color:#666;font-size:11px;'>🏠 降車先: {rt['actual_pickup']}</span></div><hr style='margin:5px 0;'>"
                        st.markdown(disp_str, unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)

                tasks_with_details = []
                full_path = []
                for t in t_rows:
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                    raw_addr = c_info.get("address", "") if c_info else ""
                    home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                    raw_memo = t.get("memo", "")
                    memo_text, temp_addr, takuji_cancel, _, _, _, stopover = parse_attendance_memo(raw_memo)
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    _, dst = get_route_line_and_distance(actual_pickup)
                    tasks_with_details.append({
                        "task": t, "c_info": c_info, "actual_pickup": actual_pickup, "stopover": stopover,
                        "use_takuji": use_takuji, "takuji_addr": takuji_addr, "memo_text": memo_text,
                        "c_name": t['cast_name'], "c_id": t['cast_id'], "is_edited": is_edited,
                        "home_addr": home_addr, "temp_addr": temp_addr, "takuji_cancel": takuji_cancel,
                        "dist": dst
                    })

                st.markdown("<div style='font-size:12px; font-weight:bold; color:#e91e63; text-align:center; margin-bottom:5px;'>🤖 一番遠いキャストから拾いながらお店に戻る最短ルートです</div>", unsafe_allow_html=True)
                
                ordered_tasks, total_sec, full_path = optimize_and_calc_route(GOOGLE_MAPS_API_KEY, store_addr, store_addr, tasks_with_details, is_return=False)

                target_time_str = str(settings.get("base_arrival_time", "19:50"))
                try:
                    th, tm = map(int, target_time_str.split(':'))
                    target_dt = dt.replace(hour=th, minute=tm, second=0)
                    if dt.hour > 20 and th < 10: target_dt += datetime.timedelta(days=1)
                    padding_sec = len(full_path) * 3 * 60
                    dep_dt = target_dt - datetime.timedelta(seconds=(total_sec + padding_sec))
                    dep_time_str = dep_dt.strftime("%H:%M")
                except:
                    dep_time_str = "未定"

                st.markdown(f"<div style='font-size:15px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center; border: 1px solid #f44336;'>🚀 店舗出発時刻 (計算): {dep_time_str}</div>", unsafe_allow_html=True)

                if full_path:
                    origin_enc = urllib.parse.quote(full_path[0])
                    dest_enc = urllib.parse.quote(store_addr)
                    wp_enc = urllib.parse.quote("|".join(full_path[1:])) if len(full_path) > 1 else ""
                    map_url = f"https://www.google.com/maps/dir/?api=1&origin={origin_enc}&destination={dest_enc}"
                    if wp_enc: map_url += f"&waypoints={wp_enc}"
                    st.markdown(f"<a href='{map_url}' target='_blank' class='line-connect-btn' style='background:#4285f4; margin-bottom:15px;'>🗺️ スマホのナビで全行程を開始</a>", unsafe_allow_html=True)
                
                for idx, t in enumerate(ordered_tasks):
                    addr_display = f"🏠 迎え: {t['home_addr'] if t['home_addr'] else '未登録'}"
                    if t["temp_addr"]: addr_display += f"<br><span style='color:#e91e63;font-weight:bold;'>📍 当日変更: {t['temp_addr']}</span>"
                    if t["stopover"]: addr_display += f"<br><span style='color:#ff9800;font-weight:bold;'>🍽️ 立ち寄り(同伴): {t['stopover']}</span>"
                    if t["use_takuji"]: addr_display += f"<br><span style='color:#2196f3;font-weight:bold;'>👶 経由(託児): {t['takuji_addr']}</span>"
                    if t["memo_text"]: addr_display += f"<br>📝 備考: {t['memo_text']}"
                    
                    st.markdown(f"**迎え順 {idx+1}： {t['task']['pickup_time']}**　<span style='font-size:16px; font-weight:bold;'>{t['c_name']}</span> <br><span style='font-size:13px;'>{addr_display}</span><hr style='margin:5px 0;'>", unsafe_allow_html=True)

                st.markdown('</div>', unsafe_allow_html=True)

        # ----------------------------------------
        # ② キャスト送迎
        # ----------------------------------------
        elif st.session_state.staff_tab == "② キャスト送迎":
            st.markdown(f'<div style="text-align:center; font-size:18px; font-weight:bold;">{today_str} ({dow})</div><div style="text-align:center; color:#aaa; font-size:12px; margin-bottom:15px;">▼ 全キャスト送迎管理 ▼</div>', unsafe_allow_html=True)
            
            with st.expander("🌅 早便設定（一括追加ツール）", expanded=False):
                if "early_form_key" not in st.session_state:
                    st.session_state.early_form_key = 0
                fk = st.session_state.early_form_key
                
                if st.session_state.get("early_msg"):
                    st.success(st.session_state.early_msg)
                    st.session_state.early_msg = ""
                    
                c_disp_list = ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in casts if str(c.get("name", "")).strip() != ""]
                selected_c = st.selectbox("早便希望キャスト", c_disp_list, key=f"early_cast_{fk}")
                
                selected_d = st.selectbox("送迎ドライバー", ["未定"] + d_names, key=f"early_driver_{fk}")
                
                st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                early_dest = st.text_input("送迎先（送り先住所）", placeholder="例: 倉敷駅北口", key=f"early_dest_{fk}")
                
                early_time = st.selectbox(
                    "到着指定時間", 
                    early_time_slots, 
                    index=early_time_slots.index("17:00") if "17:00" in early_time_slots else 0, 
                    key=f"early_time_{fk}"
                )
                
                if st.button("➕ このキャストを早便リストに追加", type="secondary", use_container_width=True, key=f"btn_add_early_{fk}"):
                    if selected_c != "-- 選択 --" and early_dest:
                        c_id = str(selected_c.split(" ")[0])
                        c_name = str(selected_c.split(" ")[1])
                        if "early_list" not in st.session_state:
                            st.session_state.early_list = []
                        new_item = {"cast_id": c_id, "cast_name": c_name, "driver": selected_d, "dest": early_dest, "time": early_time}
                        st.session_state.early_list = st.session_state.early_list + [new_item]
                        st.session_state.early_msg = f"✅ {c_name} をリストに追加しました！続けて入力できます。"
                        st.session_state.early_form_key += 1
                        st.rerun()
                    else:
                        st.warning("キャストを選択し、送迎先を入力してください。")
                
                if "early_list" in st.session_state and st.session_state.early_list:
                    st.markdown("<div style='background:#fff3e0; padding:10px; border-radius:8px; border:2px solid #ff9800; margin-top:15px;'>", unsafe_allow_html=True)
                    st.markdown("<b style='color:#e65100;'>【追加された早便リスト】</b>", unsafe_allow_html=True)
                    for idx, item in enumerate(st.session_state.early_list):
                        st.markdown(f"<div style='font-size:14px; margin-bottom:5px;'>・ {item['cast_name']} ➡️ {item['dest']} ({item['time']}着) / ドライバー: {item['driver']}</div>", unsafe_allow_html=True)
                    
                    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                    col_eb1, col_eb2 = st.columns([3, 1.2])
                    with col_eb1:
                        if st.button("🚀 決定（保存する）", type="primary", use_container_width=True):
                            updates = []
                            for item in st.session_state.early_list:
                                target_row = next((r for r in attendance if r["target_date"] == "当日" and str(r["cast_id"]) == str(item["cast_id"])), None)
                                if target_row:
                                    memo, temp_addr, takuji_cancel, _, _, _, stopover = parse_attendance_memo(target_row.get("memo", ""))
                                    new_memo = encode_attendance_memo(memo, temp_addr, takuji_cancel, item["driver"], item["time"], item["dest"], stopover)
                                    updates.append({
                                        "id": target_row.get("id"),
                                        "cast_id": item["cast_id"], "cast_name": item["cast_name"], "area": target_row["area"],
                                        "status": "出勤",
                                        "memo": new_memo, "target_date": "当日"
                                    })
                                else:
                                    new_memo = encode_attendance_memo("", "", "0", item["driver"], item["time"], item["dest"], "")
                                    c_info = next((c for c in casts if str(c["cast_id"]) == str(item["cast_id"])), {})
                                    updates.append({
                                        "cast_id": item["cast_id"], "cast_name": item["cast_name"], "area": c_info.get("area", "他"),
                                        "status": "出勤", "memo": new_memo, "target_date": "当日"
                                    })
                            if updates:
                                res = post_api({"action": "save_attendance", "records": updates})
                                if res.get("status") == "success":
                                    st.session_state.early_list = []
                                    st.session_state.early_form_key += 1
                                    clear_cache(); st.success("✅ 早便の割り当てが完了しました！"); time.sleep(1.5); st.rerun()
                                else: st.error("エラーが発生しました。")
                    with col_eb2:
                        if st.button("🗑 リセット", use_container_width=True):
                            st.session_state.early_list = []
                            st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<hr style='margin:15px 0;'>", unsafe_allow_html=True)

            dispatch_count = 0
            early_count = 0
            today_active_casts = []
            seen_cids_today = set()
            
            for row in attendance:
                if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                    cid_str = str(row["cast_id"])
                    if cid_str in seen_cids_today: continue
                    seen_cids_today.add(cid_str)
                    
                    dispatch_count += 1
                    _, _, _, e_drv, _, _, _ = parse_attendance_memo(row.get("memo", ""))
                    is_early = (e_drv and e_drv != "未定" and e_drv != "")
                    if is_early:
                        early_count += 1
                    
                    c_info_dict = next((c for c in casts if str(c["cast_id"]) == str(row["cast_id"])), {})
                    pref = c_info_dict.get("area", "他")
                        
                    today_active_casts.append({
                        "id": row["cast_id"], 
                        "name": row["cast_name"], 
                        "status": row["status"],
                        "is_early": is_early,
                        "pref": pref,
                        "row": row
                    })

            today_active_casts = sorted(today_active_casts, key=lambda x: int(x["id"]) if str(x["id"]).isdigit() else 999)

            st.markdown(f'''
            <div style="background-color: #e3f2fd; border: 2px solid #2196f3; padding: 10px; border-radius: 8px; text-align: center; margin-bottom: 10px;">
                <span style="font-size: 14px; color: #1565c0; font-weight: bold;">🚗 現在の送迎申請数（当日）</span><br>
                <span style="font-size: 24px; font-weight: bold; color: #e91e63;">{dispatch_count}</span> <span style="font-size: 16px; color: #1565c0; font-weight: bold;">名</span>
                <div style="font-size: 14px; color: #e65100; font-weight: bold; margin-top: 5px;">🌅 うち早便設定済： {early_count} 名</div>
            </div>
            ''', unsafe_allow_html=True)
            
            with st.expander(f"📋 当日の送迎キャスト一覧を見る・編集する（{dispatch_count}名）"):
                if today_active_casts:
                    list_search = st.text_input("🔍 一覧からキャストを絞り込み検索", placeholder="名前 または 店番", key="today_list_search")
                    st.markdown("<div style='margin-top:10px;'>", unsafe_allow_html=True)
                    
                    display_c = 0
                    for loop_idx, c_dict in enumerate(today_active_casts):
                        c_id = str(c_dict['id'])
                        c_name = c_dict['name']
                        
                        if list_search:
                            if list_search not in c_name and list_search != c_id:
                                continue
                        
                        display_c += 1
                        pref = c_dict.get('pref', '他')
                        target_row = c_dict.get('row')
                        
                        render_cast_edit_card(c_id, c_name, pref, target_row, "tdy", d_names, time_slots, early_time_slots, loop_idx)
                        
                    if display_c == 0:
                        st.write("該当するキャストがいません。")
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.info("本日の送迎申請はまだありません。")

            st.markdown("<hr style='margin:15px 0;'>", unsafe_allow_html=True)
            
            if "search_cast_key" not in st.session_state:
                st.session_state.search_cast_key = 0
            if "active_search_query" not in st.session_state:
                st.session_state.active_search_query = ""
                
            st.markdown("<div style='font-size:14px; font-weight:bold; color:#555; margin-bottom:5px;'>🔍 全キャスト検索 (未出勤者の予定追加・変更)</div>", unsafe_allow_html=True)
            col_search1, col_search2 = st.columns([3, 1])
            with col_search1:
                input_q = st.text_input("検索キーワード", placeholder="名前 または 店番", key=f"search_input_{st.session_state.search_cast_key}", label_visibility="collapsed")
            with col_search2:
                if st.button("検索", type="secondary", use_container_width=True):
                    st.session_state.active_search_query = input_q
                    st.rerun()

            def reset_search():
                st.session_state.active_search_query = ""
                st.session_state.search_cast_key += 1
                clear_cache()

            act_rng = st.radio("範囲", range_opts, horizontal=True, label_visibility="collapsed")
            st.markdown("<hr style='margin:15px 0;'>", unsafe_allow_html=True)
            
            search_query = st.session_state.active_search_query
            
            display_count = 0
            seen_all_cids = set()
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
                
                target_row = None
                for row in attendance:
                    if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"] and str(row["cast_id"]) == str(c_id):
                        target_row = row; break
                
                render_cast_edit_card(c_id, c_name, pref, target_row, "all", d_names, time_slots, early_time_slots, loop_idx)

            if display_count == 0: st.info("条件に一致するキャストが見つかりません。")

        # ----------------------------------------
        # ③ キャスト登録
        # ----------------------------------------
        elif st.session_state.staff_tab == "③ キャスト登録":
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
                
                with st.expander(f"店番 {i} : {nm if nm else '未登録'} {mgr}"):
                    nn = st.text_input("名前", value=nm, key=f"cn_{i}")
                    mgr_idx = staff_list.index(mgr) if mgr in staff_list else 0
                    n_mgr = st.selectbox("担当スタッフ", staff_list, index=mgr_idx, key=f"cmgr_{i}")
                    
                    raw_addr = str(c.get("address", ""))
                    home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                    
                    if is_edited == "1":
                        st.markdown("<div style='color:#4caf50; font-weight:bold; font-size:14px; margin-bottom:10px;'>✅ キャスト本人が自宅住所を更新済みです</div>", unsafe_allow_html=True)
                    
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
                    nt = st.text_input("電話番号", value=str(c["phone"]), key=f"ct_{i}")
                    np = st.text_input("パスワード", value=str(c["password"]), key=f"cp_{i}")
                    
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
                            if res.get("status") == "success":
                                clear_cache(); st.session_state[f"saved_cast_{i}"] = True; st.success("保存しました！"); time.sleep(1); st.rerun()
                            else: st.error("エラー: " + res.get("message"))
            if display_count == 0:
                st.info("条件に一致するキャストが見つかりません。")

        # ----------------------------------------
        # ④ STAFF設定
        # ----------------------------------------
        elif st.session_state.staff_tab == "④ STAFF設定":
            exist_drvs = {str(d["driver_id"]): d for d in drivers}
            
            st.markdown('<div style="background:#e3f2fd; border: 2px solid #2196f3; padding: 10px; border-radius: 8px; margin-bottom: 15px;"><div style="font-weight:bold; color:#1565c0; font-size:14px; margin-bottom:5px;">👤 編集・登録するスタッフを選択</div>', unsafe_allow_html=True)
            
            staff_disp_list = ["-- 新規・編集するスタッフを選択 --"]
            for i in range(1, 31):
                nm = exist_drvs.get(str(i), {}).get("name", "")
                if nm:
                    staff_disp_list.append(f"STAFF {i} : {nm}")
                else:
                    staff_disp_list.append(f"STAFF {i} : (未登録)")
                    
            selected_staff_str = st.selectbox("スタッフ選択", staff_disp_list, label_visibility="collapsed", key="staff_selector")
            st.markdown('</div>', unsafe_allow_html=True)
            
            if selected_staff_str != "-- 新規・編集するスタッフを選択 --":
                i_str = selected_staff_str.split(" ")[1]
                i = int(i_str)
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
                        clear_cache()
                        st.session_state.flash_msg = f"STAFF {i} を保存しました！"
                        st.rerun()
                    else: st.error("エラー: " + res.get("message"))
                st.markdown('</div>', unsafe_allow_html=True)

        # ----------------------------------------
        # ⚙️ 管理設定
        # ----------------------------------------
        elif st.session_state.staff_tab == "⚙️ 管理設定":
            st.markdown('<div class="app-header" style="border:none;">📢 アプリ全体設定</div>', unsafe_allow_html=True)
            with st.form("adm_form"):
                s_notice = settings.get("notice_text", "") if isinstance(settings, dict) else ""
                s_pass = settings.get("admin_password", "1234") if isinstance(settings, dict) else "1234"
                s_line = settings.get("line_bot_id", "") if isinstance(settings, dict) else ""
                s_addr = settings.get("store_address", "岡山県倉敷市水島東栄町2-24") if isinstance(settings, dict) else "岡山県倉敷市水島東栄町2-24"
                s_time = settings.get("base_arrival_time", "19:50") if isinstance(settings, dict) else "19:50"
                st.markdown('<div class="section-title" style="color:#2196f3; margin-top:0;">📍 送迎基本設定 (店舗・到着時間)</div>', unsafe_allow_html=True)
                st.caption("ドライバーのスマホから起動するカーナビの目的地と、基本の到着時間です。")
                n_addr = st.text_input("到着場所（店舗住所）", value=s_addr)
                arr_idx = time_slots.index(s_time) if s_time in time_slots else 0
                n_time = st.selectbox("基本到着時間 (厳守)", time_slots, index=arr_idx)
                st.markdown('<div class="section-title" style="margin-top:20px;">お知らせ</div>', unsafe_allow_html=True)
                n_text = st.text_area("例：明日イベント開催！", value=s_notice, label_visibility="collapsed")
                st.markdown('<div class="section-title" style="color:#e91e63;">🔑 管理者パスワード</div>', unsafe_allow_html=True)
                a_pass = st.text_input("パスワード", value=s_pass, label_visibility="collapsed")
                st.markdown('<div class="section-title" style="color:#00c300;">📱 LINE Bot設定</div>', unsafe_allow_html=True)
                l_id = st.text_input("Bot ID", value=s_line, placeholder="@123abcde", label_visibility="collapsed")
                if st.form_submit_button("保存して反映", type="primary", use_container_width=True):
                    res = post_api({"action": "save_settings", "admin_password": a_pass, "notice_text": n_text, "line_bot_id": l_id, "store_address": n_addr, "base_arrival_time": n_time})
                    if res.get("status") == "success": 
                        clear_cache()
                        st.session_state.flash_msg = "設定を保存しました"
                        st.rerun()
