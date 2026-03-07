import requests
import datetime
import urllib.parse
import time
import re
import streamlit as st

# ページの設定
st.set_page_config(page_title="六本木 水島本店 送迎管理", page_icon="🚗", layout="centered", initial_sidebar_state="collapsed")

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

# 🌟 新機能用：既存のDB構造を壊さずデータを隠して保存・復元する処理
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
    if not raw_memo: return "", "", "0", "", "", ""
    parts = str(raw_memo).split("||")
    memo = parts[0]
    temp_addr = parts[1] if len(parts) > 1 else ""
    takuji_cancel = parts[2] if len(parts) > 2 else "0"
    early_driver = parts[3] if len(parts) > 3 else ""
    early_time = parts[4] if len(parts) > 4 else ""
    early_dest = parts[5] if len(parts) > 5 else ""
    return memo, temp_addr, takuji_cancel, early_driver, early_time, early_dest

def encode_attendance_memo(memo, temp_addr, takuji_cancel, early_driver="", early_time="", early_dest=""):
    return f"{memo}||{temp_addr}||{takuji_cancel}||{early_driver}||{early_time}||{early_dest}"

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
        if "広島" in addr or "福山" in addr: dist = 60
        elif "井原" in addr: dist = 50
        elif "笠岡" in addr: dist = 40
        elif "浅口" in addr or "里庄" in addr: dist = 30
        elif "玉島" in addr: dist = 20
        else: dist = 20
    elif any(x in addr for x in ["真備", "矢掛", "総社", "清音", "船穂"]):
        line = "Route_B_NorthWest"
        if "矢掛" in addr: dist = 50
        elif "総社" in addr: dist = 40
        elif "真備" in addr: dist = 30
        elif "清音" in addr: dist = 25
        elif "船穂" in addr: dist = 20
        else: dist = 20
    elif any(x in addr for x in ["北区", "中区", "庭瀬", "中庄", "庄", "倉敷"]):
        if any(x in addr for x in ["水島", "連島", "広江", "児島", "下津井"]): pass 
        else:
            line = "Route_C_North"
            if "中区" in addr: dist = 50
            elif "北区" in addr: dist = 40
            elif "庭瀬" in addr: dist = 35
            elif "中庄" in addr or "庄" in addr: dist = 25
            elif "倉敷" in addr: dist = 15
            else: dist = 15
    if line == "Route_E_South": 
        if any(x in addr for x in ["備前", "瀬戸内", "赤磐", "東区", "南区", "妹尾", "早島", "茶屋町", "玉野"]):
            line = "Route_D_East"
            if "備前" in addr or "赤磐" in addr: dist = 60
            elif "瀬戸内" in addr: dist = 50
            elif "東区" in addr: dist = 45
            elif "玉野" in addr: dist = 40
            elif "南区" in addr: dist = 35
            elif "妹尾" in addr: dist = 25
            elif "早島" in addr: dist = 20
            elif "茶屋町" in addr: dist = 15
            else: dist = 15
        else:
            line = "Route_E_South"
            if "児島" in addr or "下津井" in addr: dist = 20
            elif "連島" in addr or "広江" in addr: dist = 10
            elif "水島" in addr: dist = 5
            else: dist = 10
    return line, dist

def calc_dep_time(pickup_time_str, dist_mins):
    if not pickup_time_str or pickup_time_str == "未定": return "未定"
    try:
        h, m = map(int, pickup_time_str.split(':'))
        t_mins = h * 60 + m - dist_mins
        return f"{t_mins // 60}:{t_mins % 60:02d}"
    except:
        return "未定"

# ==========================================
# 🎨 超安全・堅牢なカスタムCSS
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
    
    @media (max-width: 640px) {
        div[data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 5px !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            flex: 1 1 0% !important;
            min-width: 0 !important;
            width: auto !important;
        }
    }

    div.stButton > button {
        padding: 0px 5px !important;
        min-height: 42px !important;
        height: 42px !important;
        line-height: 1.2 !important;
        font-size: 14px !important;
        font-weight: bold !important;
        white-space: nowrap !important;
        width: 100% !important;
    }

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
    .auto-dispatch-box { background: #e8f5e9; border: 2px solid #4caf50; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
    
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div {
        border: 2px solid #000000 !important; border-radius: 6px !important; background-color: #fff !important;
    }
</style>
""", unsafe_allow_html=True)

# 状態管理
for k in ["page", "logged_in_cast", "logged_in_staff", "is_admin", "selected_staff_for_login"]:
    if k not in st.session_state: st.session_state[k] = None if k != "page" else "home"
if "is_admin" not in st.session_state: st.session_state.is_admin = False

# 通常便の時間帯
time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
# 🌟 早便専用の時間帯（14:00〜20:00）17:00の前後3時間
early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]

MAP_SEARCH_BTN = """<a href='https://www.google.com/maps' target='_blank' style='display:inline-block; padding:4px 8px; background:#4285f4; color:white; border-radius:4px; text-decoration:none; font-size:12px; font-weight:bold; margin-bottom:5px; box-shadow:0 1px 2px rgba(0,0,0,0.2);'>🔍 Googleマップを開いて住所を検索・コピー</a>"""

# ==========================================
# 🌟 ナビゲーション
# ==========================================
def render_top_nav():
    if st.session_state.page == "home": return
    
    if st.session_state.get("logged_in_cast") or st.session_state.get("logged_in_staff") or st.session_state.get("is_admin"):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🏠 ホーム", key=f"nh_{st.session_state.page}", use_container_width=True): 
                st.session_state.page = "home"; st.rerun()
        with col2:
            if st.button("🔙 戻る", key=f"nb_{st.session_state.page}", use_container_width=True): 
                st.session_state.page = "home"; st.rerun()
        with col3:
            if st.button("🚪 ログアウト", key=f"nl_{st.session_state.page}", use_container_width=True):
                st.session_state.logged_in_cast = None
                st.session_state.logged_in_staff = None
                st.session_state.is_admin = False
                st.session_state.cast_id = None
                st.session_state.page = "home"
                st.rerun()
    else:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🏠 ホーム", key=f"nh_{st.session_state.page}", use_container_width=True): 
                st.session_state.page = "home"; st.rerun()
        with col2:
            if st.button("🔙 戻る", key=f"nb_{st.session_state.page}", use_container_width=True): 
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
                st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                new_home = st.text_input("自宅住所 (迎え先)", value=home_addr)
                
                st.markdown("<div style='margin-top:10px; font-weight:bold; color:#2196f3;'>👶 託児所の利用設定</div>", unsafe_allow_html=True)
                new_takuji_en = st.checkbox("毎回自動的に託児所を経由する", value=(takuji_en=="1"))
                new_takuji_addr = ""
                if new_takuji_en:
                    st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                    new_takuji_addr = st.text_input("託児所の住所", value=takuji_addr, placeholder="託児所の住所を入力してください")
                
                if st.form_submit_button("情報を更新する", type="primary", use_container_width=True):
                    encoded_addr = encode_cast_address(new_home, "1" if new_takuji_en else "0", new_takuji_addr, "1")
                    res = post_api({"action": "save_cast", "cast_id": my_cast_info["cast_id"], "name": my_cast_info["name"], "password": my_cast_info.get("password", ""), "phone": my_cast_info.get("phone", ""), "area": my_cast_info.get("area", ""), "address": encoded_addr, "manager": my_cast_info.get("manager", "未設定")})
                    if res.get("status") == "success":
                        clear_cache(); st.success("✅ 登録情報を更新しました！"); time.sleep(1); st.rerun()
                    else:
                        st.error("更新エラーが発生しました。")
    
    today_dt = datetime.datetime.now()
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
                st.radio("状態", ["未定", "出勤", "自走", "休み"], horizontal=True, key="today_s", label_visibility="collapsed")
                st.text_input("備考 (同伴・送り先など)", placeholder="備考", key="today_m")
                
                st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
                req_change = st.checkbox("📍 本日のみ迎え先を指定の場所に変更する", key="req_chg_today")
                temp_m_addr = ""
                if req_change:
                    st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                    temp_m_addr = st.text_input("本日の迎え先住所", key="temp_addr_today", placeholder="例：倉敷駅前")
                
                takuji_cancel_val = "0"
                if takuji_en == "1":
                    if st.checkbox("👶 本日は託児所を利用しない (キャンセル)", key="cancel_takuji_today"):
                        takuji_cancel_val = "1"

            with col_t2:
                st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True) 
                if st.form_submit_button("📤 送信", type="primary", use_container_width=True):
                    if st.session_state.today_s != "未定":
                        encoded_memo = encode_attendance_memo(st.session_state.today_m, temp_m_addr, takuji_cancel_val)
                        rec = {"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": st.session_state.today_s, "memo": encoded_memo, "target_date": "当日"}
                        res = post_api({"action": "save_attendance", "records": [rec]})
                        if res.get("status") == "success": clear_cache(); st.session_state.page = "report_done"; st.rerun()
                        else: st.error(res.get("message"))

    with tab_tmr:
        with st.form("cast_tmr_form"):
            st.markdown(f'<div style="background-color: #e3f2fd; border: 3px solid #64b5f6; border-radius: 8px; padding: 10px; margin-bottom: 15px; text-align: center; color: #1565c0; font-weight: bold; font-size: 18px;">🌙 翌日申請 ({tmr_str})</div>', unsafe_allow_html=True)
            col_tm1, col_tm2 = st.columns([3, 1.2])
            with col_tm1:
                st.radio("状態", ["未定", "出勤", "自走", "休み"], horizontal=True, key="tmr_s", label_visibility="collapsed")
                st.text_input("明日の備考", placeholder="備考", key="tmr_m")
                
                st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
                req_change_tmr = st.checkbox("📍 明日のみ迎え先を指定の場所に変更する", key="req_chg_tmr")
                temp_m_addr_tmr = ""
                if req_change_tmr:
                    st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                    temp_m_addr_tmr = st.text_input("明日の迎え先住所", key="temp_addr_tmr")
                
                takuji_cancel_val_tmr = "0"
                if takuji_en == "1":
                    if st.checkbox("👶 明日は託児所を利用しない (キャンセル)", key="cancel_takuji_tmr"):
                        takuji_cancel_val_tmr = "1"

            with col_tm2:
                st.markdown('<div style="height: 28px;"></div>', unsafe_allow_html=True)
                if st.form_submit_button("📤 送信", type="primary", use_container_width=True):
                    if st.session_state.tmr_s != "未定":
                        encoded_memo_tmr = encode_attendance_memo(st.session_state.tmr_m, temp_m_addr_tmr, takuji_cancel_val_tmr)
                        rec = {"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": st.session_state.tmr_s, "memo": encoded_memo_tmr, "target_date": "翌日"}
                        res = post_api({"action": "save_attendance", "records": [rec]})
                        if res.get("status") == "success": clear_cache(); st.session_state.page = "report_done"; st.rerun()
                        else: st.error(res.get("message"))

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
                    if w['attend'] != "未定":
                        encoded_memo_week = encode_attendance_memo(w['memo'], "", "0")
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
                    if res.get("status") == "success": clear_cache(); st.session_state.page = "report_done"; st.rerun()
                    else: st.error(res.get("message"))
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
    dt = datetime.datetime.now()
    today_str = dt.strftime("%m月%d日")
    dow = ['月','火','水','木','金','土','日'][dt.weekday()]
    d_names = [str(d["name"]) for d in drivers if str(d["name"]).strip() != ""]

    col1, col2 = st.columns([4, 2])
    with col1: 
        if is_admin: st.markdown('<b>六本木 水島本店<br>送迎管理 (管理者)</b>', unsafe_allow_html=True)
        else: st.markdown(f'<b>{staff_name} 様<br>ドライバー専用画面</b>', unsafe_allow_html=True)
    with col2: 
        if st.button("🔄 最新"): clear_cache(); st.rerun()
    st.markdown("<hr style='margin:5px 0 10px 0;'>", unsafe_allow_html=True)

    current_hour = datetime.datetime.now().hour
    is_return_time = (current_hour >= 22) or (current_hour <= 7)

    # ========================================================
    # 🚙 【非管理者】ドライバー専用のナビ直結＆順番入替ルート画面
    # ========================================================
    if not is_admin:
        st.markdown(f'<div class="date-header"><div style="font-size:12px; color:#555; font-weight:normal;">本日の配車ルート</div><div class="main-date">{today_str} ({dow})</div></div>', unsafe_allow_html=True)
        
        early_tasks_raw = [row for row in attendance if row["target_date"] == "当日" and row["status"] in ["出勤"]]
        my_early_tasks = []
        for t in early_tasks_raw:
            _, _, _, e_drv, e_time, e_dest = parse_attendance_memo(t.get("memo", ""))
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
            store_addr = settings.get("store_address", "岡山県倉敷市水島東栄町2-24")
            
            if valid_early_addrs:
                dest_early = urllib.parse.quote(valid_early_addrs[-1])
                waypoints_list = [store_addr] + valid_early_addrs[:-1]
                waypoints_str = "/".join([urllib.parse.quote(a) for a in waypoints_list])
                early_map_url = f"https://www.google.com/maps/dir/現在地//{waypoints_str}/{dest_early}?hl=ja"
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

        my_tasks = [row for row in attendance if row["target_date"] == "当日" and row["status"] in ["出勤"] and row["driver_name"] == staff_name]
        my_tasks = sorted(my_tasks, key=lambda x: x['pickup_time'] if x['pickup_time'] and x['pickup_time'] != '未定' else '99:99')

        if not my_tasks:
            st.info("現在、割り当てられている送迎（迎え便）はありません。管理者の配車をお待ちください。")
        else:
            if is_return_time:
                st.markdown(f'<div style="background:#e3f2fd; border:2px solid #2196f3; padding:10px; border-radius:8px; margin-bottom:15px;"><h4 style="color:#1565c0; margin-top:0; margin-bottom:5px;">🌙 帰りの送迎便（送り班）</h4><p style="font-size:12px; color:#555; margin-bottom:10px;">行きで送迎したキャストが自動的に帰り班として表示されています。</p>', unsafe_allow_html=True)
                
                return_tasks = []
                for t in my_tasks:
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                    raw_addr = c_info.get("address", "") if c_info else ""
                    home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
                    raw_memo = t.get("memo", "")
                    _, temp_addr, takuji_cancel, _, _, _ = parse_attendance_memo(raw_memo)
                    
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    _, dst = get_route_line_and_distance(actual_pickup)
                    
                    return_tasks.append({
                        "task": t, "dist": dst, 
                        "actual_pickup": actual_pickup, 
                        "use_takuji": use_takuji, "takuji_addr": takuji_addr,
                        "c_name": t['cast_name'], "c_id": t['cast_id']
                    })
                
                return_tasks.sort(key=lambda x: x["dist"])
                
                valid_return_addrs = []
                for rt in return_tasks:
                    if rt["use_takuji"] and clean_address_for_map(rt["takuji_addr"]):
                        valid_return_addrs.append(clean_address_for_map(rt["takuji_addr"]))
                    if clean_address_for_map(rt["actual_pickup"]):
                        valid_return_addrs.append(clean_address_for_map(rt["actual_pickup"]))
                
                store_addr = settings.get("store_address", "岡山県倉敷市水島東栄町2-24")
                
                if valid_return_addrs:
                    dest_return = urllib.parse.quote(valid_return_addrs[-1])
                    waypoints_list = [store_addr] + valid_return_addrs[:-1]
                    waypoints_str = "/".join([urllib.parse.quote(a) for a in waypoints_list])
                    return_map_url = f"https://www.google.com/maps/dir/現在地//{waypoints_str}/{dest_return}?hl=ja"
                    st.markdown(f"<a href='{return_map_url}' target='_blank' class='nav-btn' style='background:#1565c0; margin-bottom:10px;'>🗺️ 帰りナビ開始 (店舗発〜近い順)</a>", unsafe_allow_html=True)
                    
                for idx, rt in enumerate(return_tasks):
                    disp_str = f"<div style='font-size:14px;'><b>降車順 {idx+1}</b>：店番 {rt['c_id']} <b>{rt['c_name']}</b><br>"
                    if rt["use_takuji"]:
                        disp_str += f"<span style='color:#2196f3;font-size:12px;font-weight:bold;'>👶 託児経由: {rt['takuji_addr']}</span><br>"
                    disp_str += f"<span style='color:#666;font-size:12px;'>🏠 降車先: {rt['actual_pickup']}</span></div><hr style='margin:5px 0;'>"
                    st.markdown(disp_str, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            first_t = my_tasks[0]
            c_info_first = next((c for c in casts if str(c["cast_id"]) == str(first_t["cast_id"])), None)
            addr_first_raw = c_info_first.get("address", "") if c_info_first else ""
            home_first, _, _, _ = parse_cast_address(addr_first_raw)
            _, temp_first, _, _, _, _ = parse_attendance_memo(first_t.get("memo", ""))
            actual_first_pickup = temp_first if temp_first else home_first
            _, dist_first = get_route_line_and_distance(actual_first_pickup)
            dep_time = calc_dep_time(first_t['pickup_time'], dist_first)
            
            st.markdown(f"<div style='font-size:16px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:10px; border-radius:5px; margin-bottom:15px; text-align:center; border: 2px solid #f44336;'>🚀 店舗出発時刻（目安）: {dep_time}</div>", unsafe_allow_html=True)

            valid_addrs = []
            for t in my_tasks:
                c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                if c_info: 
                    raw_addr = c_info.get("address", "")
                    home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
                    raw_memo = t.get("memo", "")
                    _, temp_addr, takuji_cancel, _, _, _ = parse_attendance_memo(raw_memo)
                    
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    
                    if actual_pickup and clean_address_for_map(actual_pickup):
                        valid_addrs.append(clean_address_for_map(actual_pickup))
                    if use_takuji and clean_address_for_map(takuji_addr):
                        valid_addrs.append(clean_address_for_map(takuji_addr))
            
            store_addr = settings.get("store_address", "岡山県倉敷市水島東栄町2-24")
            if valid_addrs:
                dest = urllib.parse.quote(store_addr)
                waypoints = "/".join([urllib.parse.quote(a) for a in valid_addrs])
                map_url = f"https://www.google.com/maps/dir/現在地/{waypoints}/{dest}?hl=ja"
                st.markdown(f"<a href='{map_url}' target='_blank' class='nav-btn'>🚀 行きナビ開始 (遠方から順)</a>", unsafe_allow_html=True)
            else:
                st.warning("キャストの住所が登録されていないため、自動ナビゲーションが起動できません。")

            st.markdown("<div style='margin-bottom:10px; font-weight:bold; color:#555;'>▼ 本日のピックアップ順 (変更可能) ▼</div>", unsafe_allow_html=True)
            
            for idx, t in enumerate(my_tasks):
                c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                raw_addr = c_info.get("address", "") if c_info else ""
                home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                raw_memo = t.get("memo", "")
                memo_text, temp_addr, takuji_cancel, _, _, _ = parse_attendance_memo(raw_memo)
                
                actual_pickup = temp_addr if temp_addr else home_addr
                use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                
                mgr_name = c_info.get("manager", "未設定") if c_info else "未設定"
                mgr_phone = ""
                if mgr_name != "未設定":
                    for d in drivers:
                        if d["name"] == mgr_name:
                            mgr_phone = d.get("phone", ""); break
                
                if mgr_phone: phone_btn = f"<a href='tel:{mgr_phone}' style='text-decoration:none; background:#4caf50; color:white; padding:4px 10px; border-radius:15px; font-size:12px; font-weight:bold; margin-left:10px; box-shadow:0 1px 3px rgba(0,0,0,0.2);'>📞 担当({mgr_name})</a>"
                else: phone_btn = f"<span style='font-size:12px; color:#999; margin-left:10px;'>(担当:{mgr_name})</span>"
                
                clean_actual_pickup = clean_address_for_map(actual_pickup)
                clean_takuji = clean_address_for_map(takuji_addr) if use_takuji else ""
                if clean_takuji and clean_actual_pickup:
                    ind_map_url = f"https://www.google.com/maps/dir/現在地/{urllib.parse.quote(clean_actual_pickup)}/{urllib.parse.quote(clean_takuji)}?hl=ja"
                else:
                    ind_map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(clean_actual_pickup)}?hl=ja" if clean_actual_pickup else ""
                map_btn = f"<a href='{ind_map_url}' target='_blank' style='text-decoration:none; background:#e3f2fd; color:#1565c0; font-weight:bold; padding:4px 10px; border-radius:15px; font-size:12px; border:1px solid #2196f3; margin-left:5px; box-shadow:0 1px 3px rgba(0,0,0,0.1);'>📍 個別マップ</a>" if ind_map_url else ""

                addr_display = f"🏠 自宅: {home_addr if home_addr else '未登録'}"
                if is_edited == "1": addr_display += " <span style='color:#4caf50;font-weight:bold;font-size:11px;'>(✅更新済)</span>"
                if temp_addr: addr_display += f"<br><span style='color:#e91e63;font-weight:bold;'>📍 当日変更: {temp_addr}</span>"
                if use_takuji: addr_display += f"<br><span style='color:#2196f3;font-weight:bold;'>👶 経由(託児): {takuji_addr}</span>"
                if memo_text: addr_display += f"<br>📝 備考: {memo_text}"

                st.markdown(f"""
                <div class='driver-card' style='margin-bottom:5px;'>
                    <div style='font-size:14px; color:#e91e63; font-weight:bold; margin-bottom:5px;'>
                        🚙 {idx+1}件目：{t['pickup_time'] if t['pickup_time'] else '未定'}
                    </div>
                    <div style='display:flex; align-items:center; margin-bottom:8px;'>
                        <span style='font-size:20px; font-weight:900;'>{t['cast_name']}</span>
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
                    new_addr = st.text_input("正確な住所・座標", value=actual_pickup, key=f"fix_addr_{t['cast_id']}")
                    if st.button("📍 この住所でシステムを更新", key=f"fix_btn_{t['cast_id']}", type="secondary", use_container_width=True):
                        if c_info:
                            encoded_addr = encode_cast_address(new_addr, takuji_en, takuji_addr, "0")
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
                                clear_cache()
                                st.rerun()
                            else:
                                st.error("修正に失敗しました")
                
                if takuji_en == "1" and takuji_cancel == "0":
                    if st.button("👶 本日の託児をキャンセル", key=f"cancel_t_{t['id']}", use_container_width=True):
                        new_memo = encode_attendance_memo(memo_text, temp_addr, "1")
                        rec = {"cast_id": t["cast_id"], "cast_name": t["cast_name"], "area": c_info["area"], "status": t["status"], "memo": new_memo, "target_date": "当日"}
                        res = post_api({"action": "save_attendance", "records": [rec]})
                        if res.get("status") == "success": clear_cache(); st.rerun()

                col_a, col_b, col_c = st.columns([1, 1, 2])
                with col_a:
                    if idx > 0:
                        if st.button("↑", key=f"up_{t['id']}", use_container_width=True):
                            prev_t = my_tasks[idx-1]
                            updates = [
                                {"id": t["id"], "driver_name": staff_name, "pickup_time": prev_t["pickup_time"], "status": t["status"]},
                                {"id": prev_t["id"], "driver_name": staff_name, "pickup_time": t["pickup_time"], "status": prev_t["status"]}
                            ]
                            res = post_api({"action": "update_manual_dispatch", "updates": updates})
                            if res.get("status") == "success": clear_cache(); st.rerun()
                with col_b:
                    if idx < len(my_tasks) - 1:
                        if st.button("↓", key=f"down_{t['id']}", use_container_width=True):
                            next_t = my_tasks[idx+1]
                            updates = [
                                {"id": t["id"], "driver_name": staff_name, "pickup_time": next_t["pickup_time"], "status": t["status"]},
                                {"id": next_t["id"], "driver_name": staff_name, "pickup_time": t["pickup_time"], "status": next_t["status"]}
                            ]
                            res = post_api({"action": "update_manual_dispatch", "updates": updates})
                            if res.get("status") == "success": clear_cache(); st.rerun()
                with col_c:
                    if st.button("❌ 辞退(外す)", key=f"cancel_{t['id']}", use_container_width=True):
                        updates = [{"id": t["id"], "driver_name": "未定", "pickup_time": "未定", "status": t["status"]}]
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

        # ----------------------------------------
        # ① 配車リスト
        # ----------------------------------------
        if st.session_state.staff_tab == "① 配車リスト":
            st.markdown(f'<div class="date-header"><div style="font-size:12px; color:#555; font-weight:normal;">配車予定日</div><div class="main-date">{today_str} ({dow})</div></div>', unsafe_allow_html=True)
            
            st.markdown('<div class="auto-dispatch-box">', unsafe_allow_html=True)
            st.markdown('<div style="font-weight:bold; color:#2e7d32; font-size:16px; margin-bottom:5px;">🤖 自動配車（一筆書きAI）</div>', unsafe_allow_html=True)
            if not d_names:
                st.warning("⚠️ まだドライバーが登録されていません。「④ STAFF設定」タブを開いて登録してください。")
            else:
                if "active_drv_state" not in st.session_state: st.session_state.active_drv_state = d_names
                valid_drv = [d for d in st.session_state.active_drv_state if d in d_names]
                def on_drv_change(): st.session_state.active_drv_state = st.session_state.active_drv_ms
                
                with st.expander("🛠️ 稼働ドライバーの選択 (タップで開く)", expanded=False):
                    active_drivers = st.multiselect("稼働するドライバーを選択", d_names, default=valid_drv, key="active_drv_ms", on_change=on_drv_change)
                
                if st.button("🚀 自動配車を実行", type="primary", use_container_width=True):
                    if not active_drivers: 
                        st.error("稼働するドライバーを1人以上選択してください。")
                    else:
                        st.info("自動配車を実行中...")
                        all_today_casts = []
                        for row in attendance:
                            if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                                c_info = next((c for c in casts if str(c["cast_id"]) == str(row["cast_id"])), {})
                                raw_addr = c_info.get("address", "")
                                home_addr, _, _, _ = parse_cast_address(raw_addr)
                                _, temp_addr, _, _, _, _ = parse_attendance_memo(row.get("memo", ""))
                                actual_pickup = temp_addr if temp_addr else home_addr
                                
                                line, dst = get_route_line_and_distance(actual_pickup)
                                all_today_casts.append({"row": row, "line": line, "dist": dst})
                        
                        all_today_casts.sort(key=lambda x: x["dist"], reverse=True)
                        
                        drv_specs = {}
                        for d in drivers:
                            if d["name"] in active_drivers:
                                try: cap = int(d.get("capacity", 4))
                                except: cap = 4
                                drv_specs[d["name"]] = {"capacity": cap, "assigned_rows": [], "line": None}

                        for uc in all_today_casts:
                            if uc["row"]["status"] == "自走":
                                uc["row"]["driver_name"] = "未定"
                                uc["row"]["pickup_time"] = "未定"
                                continue
                                
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
                            if not assigned_d and c_line == "Route_E_South" and uc["dist"] <= 10:
                                for d_name, stat in drv_specs.items():
                                    if len(stat["assigned_rows"]) < stat["capacity"] and len(stat["assigned_rows"]) > 0:
                                        assigned_d = d_name; break
                            if assigned_d: drv_specs[assigned_d]["assigned_rows"].append(uc)
                            else:
                                uc["row"]["driver_name"] = "未定"
                                uc["row"]["pickup_time"] = "未定"
                        
                        base_time = str(settings.get("base_arrival_time", "19:50"))
                        updates = []
                        for d_name, stat in drv_specs.items():
                            assigned_list = sorted(stat["assigned_rows"], key=lambda x: x["dist"], reverse=True)
                            try:
                                bh, bm = map(int, base_time.split(':'))
                                b_mins = bh * 60 + bm
                            except: b_mins = 19 * 60 + 50
                            total_casts = len(assigned_list)
                            for idx, item in enumerate(assigned_list):
                                mins_to_subtract = (total_casts - idx) * 20
                                t_mins = b_mins - mins_to_subtract
                                current_calc_time = f"{t_mins // 60}:{t_mins % 60:02d}"
                                updates.append({
                                    "id": item["row"]["id"], 
                                    "driver_name": d_name, 
                                    "pickup_time": current_calc_time,
                                    "status": item["row"]["status"]
                                })
                        
                        for uc in all_today_casts:
                            if uc["row"]["driver_name"] == "未定":
                                updates.append({
                                    "id": uc["row"]["id"], 
                                    "driver_name": "未定", 
                                    "pickup_time": "未定",
                                    "status": uc["row"]["status"]
                                })
                                        
                        if updates:
                            res = post_api({"action": "update_manual_dispatch", "updates": updates})
                            if res.get("status") == "success": 
                                clear_cache(); st.success(f"自動配車が完了しました！"); time.sleep(1.5); st.rerun()
                            else: st.error("エラー: " + res.get("message"))
                        else: st.warning("本日の出勤キャストがいません。")
            st.markdown('</div>', unsafe_allow_html=True)
            
            with st.expander("✏️ 配車の手動変更・入れ替え (個別更新)"):
                st.caption("各キャストの項目を変更し、右側の「更新」ボタンを押してください。")
                for row in attendance:
                    if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                        st.markdown(f"<div style='font-size:14px; font-weight:bold; margin-top:10px;'>{row['cast_name']} <span style='font-size:12px;color:#666;'>({row['area']})</span></div>", unsafe_allow_html=True)
                        c_drv, c_tm, c_st, c_btn = st.columns([2, 2, 2, 1.5])
                        with c_drv:
                            d_idx = d_names.index(row['driver_name']) + 1 if row['driver_name'] in d_names else 0
                            new_drv = st.selectbox("担当", ["未定"] + d_names, index=d_idx, key=f"md_d_{row['id']}", label_visibility="collapsed")
                        with c_tm:
                            t_idx = time_slots.index(row['pickup_time']) + 1 if row['pickup_time'] in time_slots else 0
                            new_tm = st.selectbox("時間", ["未定"] + time_slots, index=t_idx, key=f"md_t_{row['id']}", label_visibility="collapsed")
                        with c_st:
                            s_opts = ["出勤", "自走", "休み"]
                            s_idx = s_opts.index(row['status']) if row['status'] in s_opts else 0
                            new_st = st.selectbox("状態", s_opts, index=s_idx, key=f"md_s_{row['id']}", label_visibility="collapsed")
                        
                        with c_btn:
                            if st.button("更新", key=f"md_btn_{row['id']}", type="primary", use_container_width=True):
                                updates = [{"id": row["id"], "driver_name": new_drv, "pickup_time": new_tm, "status": new_st}]
                                res = post_api({"action": "update_manual_dispatch", "updates": updates})
                                if res.get("status") == "success": 
                                    clear_cache()
                                    st.rerun()
                                else: st.error("エラー")
                        st.markdown("<hr style='margin:5px 0; border-top:1px dashed #ccc;'>", unsafe_allow_html=True)

            st.radio("表示", ["当日", "翌日", "週間"], horizontal=True, label_visibility="collapsed")
            
            unassigned, my_tasks = [], {}
            for row in attendance:
                if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"]:
                    drv = row["driver_name"]
                    if not drv or drv == "未定" or row["status"] == "自走": 
                        if row["status"] != "自走": unassigned.append(row)
                    else:
                        if drv not in my_tasks: my_tasks[drv] = []
                        my_tasks[drv].append(row)
            
            if unassigned:
                st.markdown('<div class="warning-box">⚠️ 定員・路線オーバーで未割り当てのキャスト</div><div class="warning-content">', unsafe_allow_html=True)
                st.caption("※手動で割り当てるか、稼働ドライバーを追加してください。")
                for u in unassigned:
                    st.markdown(f"**{u['pickup_time'] if u['pickup_time'] else '未定'}**　<span style='font-size:16px; font-weight:bold;'>{u['cast_name']}</span> <br><span style='font-size:12px; color:#555;'>({u['status']})</span><hr style='margin:5px 0;'>", unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
            for d_name, t_rows in my_tasks.items():
                t_rows = sorted(t_rows, key=lambda x: x['pickup_time'] if x['pickup_time'] and x['pickup_time'] != '未定' else '99:99')
                st.markdown(f'<div style="background:#444; color:white; padding:10px; font-weight:bold; border-radius:5px 5px 0 0;">🚕 {d_name} (STAFF)</div><div class="card" style="border-radius:0 0 5px 5px; border-top:none;">', unsafe_allow_html=True)
                
                if is_return_time:
                    st.markdown(f'<div style="background:#e3f2fd; border:2px solid #2196f3; padding:8px; border-radius:5px; margin-bottom:15px;"><div style="color:#1565c0; font-weight:bold; margin-bottom:5px;">🌙 帰り班 (自動編成)</div>', unsafe_allow_html=True)
                    return_tasks = []
                    for t in t_rows:
                        c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                        raw_addr = c_info.get("address", "") if c_info else ""
                        home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
                        raw_memo = t.get("memo", "")
                        _, temp_addr, takuji_cancel, _, _, _ = parse_attendance_memo(raw_memo)
                        
                        actual_pickup = temp_addr if temp_addr else home_addr
                        use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                        _, dst = get_route_line_and_distance(actual_pickup)
                        
                        return_tasks.append({
                            "task": t, "dist": dst, 
                            "actual_pickup": actual_pickup, 
                            "use_takuji": use_takuji, "takuji_addr": takuji_addr,
                            "c_name": t['cast_name'], "c_id": t['cast_id']
                        })
                    
                    return_tasks.sort(key=lambda x: x["dist"])
                    valid_return_addrs = []
                    for rt in return_tasks:
                        if rt["use_takuji"] and clean_address_for_map(rt["takuji_addr"]):
                            valid_return_addrs.append(clean_address_for_map(rt["takuji_addr"]))
                        if clean_address_for_map(rt["actual_pickup"]):
                            valid_return_addrs.append(clean_address_for_map(rt["actual_pickup"]))
                    
                    store_addr = settings.get("store_address", "岡山県倉敷市水島東栄町2-24")
                    if valid_return_addrs:
                        dest_return = urllib.parse.quote(valid_return_addrs[-1])
                        waypoints_list = [store_addr] + valid_return_addrs[:-1]
                        waypoints_str = "/".join([urllib.parse.quote(a) for a in waypoints_list])
                        return_map_url = f"https://www.google.com/maps/dir/現在地//{waypoints_str}/{dest_return}?hl=ja"
                        st.markdown(f"<a href='{return_map_url}' target='_blank' style='display:inline-block; background:#1565c0; color:white; padding:5px 10px; border-radius:5px; text-decoration:none; font-size:12px; font-weight:bold; margin-bottom:5px;'>🗺️ 帰りナビ (店舗発)</a>", unsafe_allow_html=True)
                        
                    for idx, rt in enumerate(return_tasks):
                        disp_str = f"<div style='font-size:13px;'>降車順 {idx+1}：<b>{rt['c_name']}</b><br>"
                        if rt["use_takuji"]:
                            disp_str += f"<span style='color:#2196f3;font-size:11px;font-weight:bold;'>👶 託児: {rt['takuji_addr']}</span><br>"
                        disp_str += f"<span style='color:#666;font-size:11px;'>🏠 降車先: {rt['actual_pickup']}</span></div><hr style='margin:5px 0;'>"
                        st.markdown(disp_str, unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)

                first_t = t_rows[0]
                c_info_first = next((c for c in casts if str(c["cast_id"]) == str(first_t["cast_id"])), None)
                addr_first_raw = c_info_first.get("address", "") if c_info_first else ""
                home_first, _, _, _ = parse_cast_address(addr_first_raw)
                _, temp_first, _, _, _, _ = parse_attendance_memo(first_t.get("memo", ""))
                actual_first_pickup = temp_first if temp_first else home_first
                _, dist_first = get_route_line_and_distance(actual_first_pickup)
                dep_time = calc_dep_time(first_t['pickup_time'], dist_first)

                st.markdown(f"<div style='font-size:15px; font-weight:bold; color:#d32f2f; background:#ffebee; padding:8px; border-radius:5px; margin-bottom:10px; text-align:center; border: 1px solid #f44336;'>🚀 店舗出発時刻: {dep_time}</div>", unsafe_allow_html=True)

                with st.expander("⚙️ 本日の運行設定 (早便・目標時間)"):
                    def_store = str(settings.get("store_address", "岡山県倉敷市水島東栄町2-24"))
                    def_time = str(settings.get("base_arrival_time", "19:50"))
                    is_early = st.checkbox("🏃 早便・特別ルート", key=f"is_early_{d_name}")
                    if is_early:
                        dest_addr = st.text_input("到着場所", value=def_store, key=f"dest_addr_{d_name}")
                    else: dest_addr = def_store
                    arr_idx = time_slots.index(def_time) if def_time in time_slots else 0
                    st.selectbox("目標到着時間", time_slots, index=arr_idx, key=f"arr_time_{d_name}")
                    
                    valid_addrs = []
                    for r in t_rows:
                        c_info = next((c for c in casts if str(c["cast_id"]) == str(r["cast_id"])), None)
                        if c_info: 
                            raw_addr = c_info.get("address", "")
                            home_addr, takuji_en, takuji_addr, _ = parse_cast_address(raw_addr)
                            raw_memo = r.get("memo", "")
                            _, temp_addr, takuji_cancel, _, _, _ = parse_attendance_memo(raw_memo)
                            
                            actual_pickup = temp_addr if temp_addr else home_addr
                            use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                            
                            if actual_pickup and clean_address_for_map(actual_pickup):
                                valid_addrs.append(clean_address_for_map(actual_pickup))
                            if use_takuji and clean_address_for_map(takuji_addr):
                                valid_addrs.append(clean_address_for_map(takuji_addr))
                    
                    if valid_addrs:
                        dest = urllib.parse.quote(dest_addr)
                        waypoints = "/".join([urllib.parse.quote(a) for a in valid_addrs])
                        map_url = f"https://www.google.com/maps/dir/現在地/{waypoints}/{dest}?hl=ja"
                        st.markdown(f"<a href='{map_url}' target='_blank' class='line-connect-btn' style='background:#4285f4; margin-top:15px;'>🗺️ スマホのナビで全行程を開始</a>", unsafe_allow_html=True)

                st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
                
                for t in t_rows:
                    c_info = next((c for c in casts if str(c["cast_id"]) == str(t["cast_id"])), None)
                    raw_addr = c_info.get("address", "") if c_info else ""
                    home_addr, takuji_en, takuji_addr, is_edited = parse_cast_address(raw_addr)
                    
                    raw_memo = t.get("memo", "")
                    memo_text, temp_addr, takuji_cancel, _, _, _ = parse_attendance_memo(raw_memo)
                    
                    actual_pickup = temp_addr if temp_addr else home_addr
                    use_takuji = (takuji_en == "1" and takuji_cancel == "0" and takuji_addr != "")
                    
                    clean_actual_pickup = clean_address_for_map(actual_pickup)
                    clean_takuji = clean_address_for_map(takuji_addr) if use_takuji else ""
                    if clean_takuji and clean_actual_pickup:
                        ind_map_url = f"https://www.google.com/maps/dir/現在地/{urllib.parse.quote(clean_actual_pickup)}/{urllib.parse.quote(clean_takuji)}?hl=ja"
                    else:
                        ind_map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(clean_actual_pickup)}?hl=ja" if clean_actual_pickup else ""
                    map_btn = f"<a href='{ind_map_url}' target='_blank' style='text-decoration:none; background:#e3f2fd; padding:2px 8px; border-radius:10px; font-size:12px; border:1px solid #2196f3; margin-left:5px;'>📍 マップ</a>" if ind_map_url else ""
                    
                    addr_display = f"🏠 自宅: {home_addr if home_addr else '未登録'}"
                    if is_edited == "1": addr_display += " <span style='color:#4caf50;font-weight:bold;font-size:11px;'>(✅更新済)</span>"
                    if temp_addr: addr_display += f"<br><span style='color:#e91e63;font-weight:bold;'>📍 当日変更: {temp_addr}</span>"
                    if use_takuji: addr_display += f"<br><span style='color:#2196f3;font-weight:bold;'>👶 経由(託児): {takuji_addr}</span>"
                    if memo_text: addr_display += f"<br>📝 備考: {memo_text}"
                    
                    st.markdown(f"**{t['pickup_time'] if t['pickup_time'] else '未定'}**　<span style='font-size:16px; font-weight:bold;'>{t['cast_name']}</span> {map_btn}<br><span style='font-size:12px; color:#555;'>({t['status']})</span><br><span style='font-size:13px;'>{addr_display}</span><hr style='margin:5px 0;'>", unsafe_allow_html=True)
                    
                    if takuji_en == "1" and takuji_cancel == "0":
                        if st.button("👶 託児キャンセル", key=f"cancel_t_{t['id']}", use_container_width=True):
                            new_memo = encode_attendance_memo(memo_text, temp_addr, "1")
                            rec = {"cast_id": t["cast_id"], "cast_name": t["cast_name"], "area": c_info["area"], "status": t["status"], "memo": new_memo, "target_date": "当日"}
                            res = post_api({"action": "save_attendance", "records": [rec]})
                            if res.get("status") == "success": clear_cache(); st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)

        # ----------------------------------------
        # ② キャスト送迎
        # ----------------------------------------
        elif st.session_state.staff_tab == "② キャスト送迎":
            st.markdown(f'<div style="text-align:center; font-size:18px; font-weight:bold;">{today_str} ({dow})</div><div style="text-align:center; color:#aaa; font-size:12px; margin-bottom:15px;">▼ 全キャスト送迎管理 ▼</div>', unsafe_allow_html=True)
            
            # 🌟 新機能：早便設定（入力リセット機能付き、時間は17:00基準）
            with st.expander("🌅 早便設定（送り便の個別指定）", expanded=False):
                if "early_form_key" not in st.session_state:
                    st.session_state.early_form_key = 0
                fk = st.session_state.early_form_key
                
                if st.session_state.get("early_msg"):
                    st.success(st.session_state.early_msg)
                    st.session_state.early_msg = ""
                    
                c_disp_list = ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in casts if str(c.get("name", "")).strip() != ""]
                selected_c = st.selectbox("早便希望キャスト", c_disp_list, key=f"early_cast_{fk}")
                selected_d = st.selectbox("担当送迎ドライバー", ["未定"] + d_names, key=f"early_driver_{fk}")
                st.markdown(MAP_SEARCH_BTN, unsafe_allow_html=True)
                early_dest = st.text_input("送迎先（送り先住所）", placeholder="例: 倉敷駅北口", key=f"early_dest_{fk}")
                
                # 🌟 指定通り、早便専用の時間リスト（14:00〜20:00）を使用し、17:00をデフォルトに設定
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
                        st.session_state.early_list.append({
                            "cast_id": c_id, "cast_name": c_name, "driver": selected_d, "dest": early_dest, "time": early_time
                        })
                        st.session_state.early_msg = f"✅ {c_name} をリストに追加しました！続けて入力できます。"
                        st.session_state.early_form_key += 1
                        st.rerun()
                    else:
                        st.warning("キャストを選択し、送迎先を入力してください。")
                
                if "early_list" in st.session_state and st.session_state.early_list:
                    st.markdown("<div style='background:#fff3e0; padding:10px; border-radius:8px; border:2px solid #ff9800; margin-top:15px;'>", unsafe_allow_html=True)
                    st.markdown("<b style='color:#e65100;'>【追加された早便リスト】</b>", unsafe_allow_html=True)
                    for idx, item in enumerate(st.session_state.early_list):
                        st.markdown(f"<div style='font-size:14px; margin-bottom:5px;'>・ {item['cast_name']} ➡️ {item['dest']} ({item['time']}着) / 担当: {item['driver']}</div>", unsafe_allow_html=True)
                    
                    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                    col_eb1, col_eb2 = st.columns([3, 1.2])
                    with col_eb1:
                        if st.button("🚀 決定（自動振分けを実行）", type="primary", use_container_width=True):
                            updates = []
                            for item in st.session_state.early_list:
                                target_row = next((r for r in attendance if r["target_date"] == "当日" and str(r["cast_id"]) == str(item["cast_id"])), None)
                                if target_row:
                                    memo, temp_addr, takuji_cancel, _, _, _ = parse_attendance_memo(target_row.get("memo", ""))
                                    new_memo = encode_attendance_memo(memo, temp_addr, takuji_cancel, item["driver"], item["time"], item["dest"])
                                    updates.append({
                                        "cast_id": item["cast_id"], "cast_name": item["cast_name"], "area": target_row["area"],
                                        "status": target_row["status"], "memo": new_memo, "target_date": "当日"
                                    })
                                else:
                                    new_memo = encode_attendance_memo("", "", "0", item["driver"], item["time"], item["dest"])
                                    c_info = next((c for c in casts if str(c["cast_id"]) == str(item["cast_id"])), {})
                                    updates.append({
                                        "cast_id": item["cast_id"], "cast_name": item["cast_name"], "area": c_info.get("area", "他"),
                                        "status": "出勤", "memo": new_memo, "target_date": "当日"
                                    })
                            if updates:
                                res = post_api({"action": "save_attendance", "records": updates})
                                if res.get("status") == "success":
                                    st.session_state.early_list = []
                                    clear_cache(); st.success("✅ 早便の割り当てが完了しました！"); time.sleep(1.5); st.rerun()
                                else: st.error("エラーが発生しました。")
                    with col_eb2:
                        if st.button("🗑 リセット", use_container_width=True):
                            st.session_state.early_list = []
                            st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
            
            st.markdown("<hr style='margin:15px 0;'>", unsafe_allow_html=True)

            dispatch_count = sum(1 for row in attendance if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"])
            st.markdown(f'''
            <div style="background-color: #e3f2fd; border: 2px solid #2196f3; padding: 10px; border-radius: 8px; text-align: center; margin-bottom: 20px;">
                <span style="font-size: 14px; color: #1565c0; font-weight: bold;">🚗 現在の送迎申請数（当日）</span><br>
                <span style="font-size: 24px; font-weight: bold; color: #e91e63;">{dispatch_count}</span> <span style="font-size: 16px; color: #1565c0; font-weight: bold;">名</span>
            </div>
            ''', unsafe_allow_html=True)
            
            search_query = st.text_input("🔍 キャスト検索 (名前または店番)", placeholder="例: ゆみか, 94", key="search_cast")
            act_rng = st.radio("範囲", range_opts, horizontal=True, label_visibility="collapsed")
            st.markdown("<hr style='margin:15px 0;'>", unsafe_allow_html=True)
            
            display_count = 0
            for cast in casts:
                c_id, c_name = str(cast["cast_id"]), str(cast["name"])
                if not c_name: continue
                if search_query:
                    if search_query not in c_name and search_query not in c_id: continue
                else:
                    if not is_in_range(c_id, act_rng): continue
                display_count += 1
                pref = str(cast["area"])
                
                is_dispatch = False
                for row in attendance:
                    if row["target_date"] == "当日" and row["status"] in ["出勤", "自走"] and str(row["cast_id"]) == str(c_id):
                        is_dispatch = True; break
                
                st.markdown('<div class="card" style="padding:10px;">', unsafe_allow_html=True)
                colA, colB = st.columns([3, 2])
                with colA: st.markdown(f'<span class="shop-no-badge-mini">店番 {c_id}</span> <span style="font-weight:bold; font-size:16px;">{c_name}</span> <span style="font-size:12px;color:#777;">({pref})</span>', unsafe_allow_html=True)
                with colB: 
                    if is_dispatch: st.markdown('<div style="color:#e91e63; font-weight:bold; text-align:right; padding-top:5px;">🚙 送迎予定あり</div>', unsafe_allow_html=True)
                    else: st.markdown('<div style="color:#aaa; text-align:right; padding-top:5px;">未定</div>', unsafe_allow_html=True)
                st.markdown("<hr style='margin:5px 0;'>", unsafe_allow_html=True)
                if is_dispatch:
                    if st.button("❌ この送迎を取り消す", key=f"cancel_{c_id}", use_container_width=True):
                        res = post_api({"action": "cancel_dispatch", "cast_id": c_id})
                        if res.get("status") == "success": clear_cache(); st.rerun()
                        else: st.error("取消失敗: " + res.get("message"))
                else:
                    if st.button("☑ 送迎リストに追加する", key=f"add_{c_id}", type="primary", use_container_width=True):
                        payload = {"action": "create_or_update_dispatch", "cast_id": c_id, "cast_name": c_name, "area": pref, "pickup_time": "未定", "driver_name": "未定"}
                        res = post_api(payload)
                        if res.get("status") == "success": clear_cache(); st.rerun()
                        else: st.error("追加失敗: " + res.get("message"))
                st.markdown('</div>', unsafe_allow_html=True)
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
            st.caption("※スタッフ名をタップすると設定を展開します。")
            exist_drvs = {str(d["driver_id"]): d for d in drivers}
            for i in range(1, 31):
                d = exist_drvs.get(str(i), {})
                nm = str(d.get("name", ""))
                if not is_admin and not nm: continue
                st.markdown('<div class="card" style="padding:10px;">', unsafe_allow_html=True)
                col1, col2 = st.columns([1.5, 1])
                with col1: st.markdown(f'<span style="font-size:11px; color:#aaa;">STAFF {i}</span> <span style="font-weight:bold; font-size:16px;">{nm if nm else "未登録"}</span>', unsafe_allow_html=True)
                with col2: st.button("担当 ▼", key=f"tbtn_{i}")
                if is_admin:
                    with st.expander("✏️ 詳細設定・編集"):
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
                        if st.session_state.get(f"saved_driver_{i}", False):
                            st.markdown('<div style="background-color: #4caf50; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold; margin-bottom: 10px;">✅ 登録済</div>', unsafe_allow_html=True)
                            if st.button("内容を変更する", key=f"edit_driver_{i}", use_container_width=True): st.session_state[f"saved_driver_{i}"] = False; st.rerun()
                        else:
                            if st.button("保存する", key=f"ds_{i}", type="primary", use_container_width=True):
                                city_part = d_other_city if d_city == "他" else d_city
                                final_addr = d_pref + city_part + d_rest
                                payload = {"action": "save_driver", "driver_id": i, "name": nn, "password": n_pass, "address": final_addr, "phone": n_tel, "area": n_area, "capacity": n_cap}
                                res = post_api(payload)
                                if res.get("status") == "success":
                                    clear_cache(); st.session_state[f"saved_driver_{i}"] = True; st.success(f"STAFF {i} を保存しました！"); time.sleep(1); st.rerun()
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
                    if res.get("status") == "success": clear_cache(); st.success("✅ 保存しました。"); time.sleep(1); st.rerun()
