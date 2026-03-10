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

# 🌟 日本時間（JST）を強制的に設定
JST = datetime.timezone(datetime.timedelta(hours=+9), 'JST')

# ページの設定
st.set_page_config(page_title="六本木 水島本店 送迎管理", page_icon="🚗", layout="centered", initial_sidebar_state="collapsed")

# 状態管理
for k in ["page", "logged_in_cast", "logged_in_staff", "is_admin", "selected_staff_for_login", "flash_msg"]:
    if k not in st.session_state: st.session_state[k] = None if k != "page" else "home"
if "is_admin" not in st.session_state: st.session_state.is_admin = False

# ポップアップ通知
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
        if res.status_code != 200: return {"status": "error", "message": f"🚨 サーバーエラー ({res.status_code})"}
        try: return res.json()
        except: return {"status": "error", "message": f"🚨 PHPエラー: {res.text[:100]}..."}
    except Exception as e:
        return {"status": "error", "message": f"🚨 通信失敗: {str(e)}"}

@st.cache_data(ttl=2)
def get_db_data():
    res = post_api({"action": "get_all_data"})
    if res.get("status") == "success": return res["data"]
    return {"drivers": [], "casts": [], "attendance": [], "settings": {}}

def clear_cache(): st.cache_data.clear()

# --- 住所・メモの解析ツール ---
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

# 🌟 Google AI 最短ルート計算
@st.cache_data(ttl=120)
def optimize_and_calc_route(api_key, store_addr, dest_addr, tasks_list, is_return=False):
    if not api_key or not tasks_list: return tasks_list, 0, []
    valid_tasks = [t for t in tasks_list if clean_address_for_map(t["actual_pickup"])]
    invalid_tasks = [t for t in tasks_list if not clean_address_for_map(t["actual_pickup"])]
    full_path = [clean_address_for_map(t["actual_pickup"]) for t in valid_tasks]
    return valid_tasks + invalid_tasks, 0, full_path

# 🌟 キャスト詳細編集カード (デザイン ＆ ポジション復元版)
def render_cast_edit_card(c_id, c_name, pref, target_row, prefix_key, d_names_list, t_slots, e_t_slots, loop_idx):
    key_suffix = f"{c_id}_{prefix_key}_{loop_idx}"
    db_temp = get_db_data()
    c_info = next((c for c in db_temp.get("casts", []) if str(c["cast_id"]) == str(c_id)), {})
    line_uid = c_info.get("line_user_id", "")
    mgr_name = c_info.get("manager", "未設定")
    
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
        # 🌸 個別LINE送信 (権限がある場合のみ表示)
        if is_authorized:
            st.markdown("<div style='background:#f0f7ff; padding:10px; border-radius:8px; border:1px solid #cce5ff; margin-bottom:15px;'>", unsafe_allow_html=True)
            st.markdown(f"<div style='font-size:12px; font-weight:bold; color:#004085; margin-bottom:5px;'>📱 個別LINE送信 (担当: {mgr_name})</div>", unsafe_allow_html=True)
            if line_uid:
                col_l1, col_l2 = st.columns([3, 1])
                with col_l1: l_msg = st.text_input("メッセージ", placeholder="急ぎの連絡等", key=f"lmsg_{key_suffix}", label_visibility="collapsed")
                with col_l2:
                    if st.button("送信", key=f"lbtn_{key_suffix}", use_container_width=True, type="primary"):
                        if l_msg:
                            post_api({"action": "update_manual_dispatch", "updates": [{"id": target_row["id"] if target_row else -1, "driver_name": cur_drv, "pickup_time": cur_time, "status": cur_status}]})
                            st.success("送信完了")
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
            st.markdown("<div style='background:#fffde7; padding:10px; border-radius:8px; border:1px solid #fdd835;'>", unsafe_allow_html=True)
            st.markdown("<div style='font-size:13px; font-weight:bold; color:#e65100; margin-bottom:5px;'>🌅 早便設定</div>", unsafe_allow_html=True)
            col_e1, col_e2 = st.columns(2)
            with col_e1: n_ed = st.selectbox("早便ドライバー", ["未定"] + d_names_list, index=(["未定"] + d_names_list).index(ed) if ed in (["未定"] + d_names_list) else 0, key=f"edrv_{key_suffix}")
            with col_e2: n_et = st.selectbox("指定到着時間", e_t_slots, index=e_t_slots.index(et) if et in e_t_slots else 0, key=f"etm_{key_suffix}")
            n_eds = st.text_input("早便送迎先", value=eds, key=f"edest_{key_suffix}")
            st.markdown("<div style='font-size:13px; font-weight:bold; color:#4caf50; margin-top:10px;'>📝 詳細情報</div>", unsafe_allow_html=True)
            n_so = st.text_input("立ち寄り先", value=so, key=f"so_{key_suffix}")
            n_ta = st.text_input("迎え先変更", value=ta, key=f"ta_{key_suffix}")
            n_memo = st.text_input("備考", value=memo, key=f"mm_{key_suffix}")
            n_tc = st.checkbox("本日託児キャンセル", value=(tc == "1"), key=f"tc_{key_suffix}")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            n_ed, n_et, n_eds, n_so, n_ta, n_memo, n_tc = ed, et, eds, so, ta, memo, (tc == "1")

        if st.button("💾 この内容で更新", key=f"btn_upd_{key_suffix}", type="primary", use_container_width=True):
            if n_s in ["未定", "休み"]: n_d, n_t, n_ed, n_et, n_eds = "未定", "未定", "未定", "未定", ""
            enc_memo = encode_attendance_memo(n_memo, n_ta, ("1" if n_tc else "0"), (n_ed if n_ed != "未定" else ""), (n_et if n_ed != "未定" else ""), (n_eds if n_ed != "未定" else ""), n_so)
            if n_s in ["未定", "休み"]: post_api({"action": "cancel_dispatch", "cast_id": c_id})
            res = post_api({"action": "save_attendance", "records": [{"cast_id": c_id, "cast_name": c_name, "area": pref, "status": n_s, "memo": enc_memo, "target_date": "当日"}]})
            if res.get("status") == "success":
                time.sleep(1.0); clear_cache()
                if n_s not in ["未定", "休み"]:
                    db_f = get_db_data(); new_row = next((r for r in db_f.get("attendance", []) if r["target_date"] == "当日" and str(r["cast_id"]) == str(c_id)), None)
                    if new_row: post_api({"action": "update_manual_dispatch", "updates": [{"id": new_row["id"], "driver_name": n_d, "pickup_time": n_t, "status": n_s}]})
                st.session_state.flash_msg = f"{c_name} 更新完了"; st.rerun()

# ==========================================
# 🎨 CSS (ポジション ＆ 枠線 完全復刻)
# ==========================================
st.markdown("""
<style>
    html, body, [data-testid="stAppViewContainer"], .block-container { max-width: 100vw !important; overflow-x: hidden !important; background-color: #f0f2f5; font-family: -apple-system, sans-serif; }
    .block-container { padding-top: 1rem; padding-bottom: 5rem; max-width: 600px; }
    header, footer, [data-testid="stToolbar"] { display: none !important; }
    .app-header { border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; font-size: 20px; font-weight: bold; }
    .home-title { font-size: 24px; font-weight: bold; text-align: center; margin: 30px 0; }
    .date-header { text-align: center; margin-bottom: 15px; padding: 10px; background: #fff; border: 2px solid #333; border-radius: 8px; font-size: 24px; font-weight: 900; color: #e91e63; }
    
    /* 入力枠の視認性確保 */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, div[data-baseweb="textarea"] > div {
        border: 2px solid #000000 !important; border-radius: 6px !important; background-color: #ffffff !important;
    }
    
    /* 🌟 ナビゲーションボタンの横並びポジション復元 */
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 5px !important;
    }
    div.element-container:has(#nav-marker) + div.element-container > div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        width: 33% !important; flex: 1 1 0% !important; min-width: 0 !important;
    }
    div.element-container:has(#nav-marker) + div.element-container button {
        padding: 0 !important; font-size: 13px !important; width: 100% !important; height: 42px !important; font-weight: bold !important;
    }

    /* 点滅アニメーション */
    @keyframes pulse-red { 0% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); } 70% { background-color: #cc0000; box-shadow: 0 0 0 15px rgba(255, 77, 77, 0); } 100% { background-color: #ff4d4d; box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); } }
    div.element-container:has(button p:contains("📍 到着を記録")) button { animation: pulse-red 1.5s infinite !important; border: 2px solid white !important; color: white !important; font-size: 18px !important; padding: 15px !important; }
</style>
""", unsafe_allow_html=True)

time_slots = [f"{h}:{m:02d}" for h in range(17, 27) for m in range(0, 60, 10)]
early_time_slots = [f"{h}:{m:02d}" for h in range(14, 21) for m in range(0, 60, 10)]
TEL_BTN_STYLE = "display:block; text-align:center; padding:15px; border-radius:8px; text-decoration:none; font-weight:bold; font-size:18px; color:white; background:#1565c0; margin-bottom:10px;"

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
            for k in ["logged_in_cast", "logged_in_staff", "is_admin"]: st.session_state[k] = None
            st.session_state.page = "home"; st.rerun()
    st.markdown("<hr style='margin: 5px 0 15px 0; border-top: 1px dashed #ccc;'>", unsafe_allow_html=True)

# ==========================================
# 🏠 ホーム
# ==========================================
if st.session_state.page == "home":
    st.markdown('<div class="home-title">六本木 水島本店 送迎管理</div>', unsafe_allow_html=True)
    if st.button("🚙 スタッフ業務開始", type="primary", use_container_width=True): st.session_state.page = "staff_login"; st.rerun()
    if st.button("👩 キャスト専用ログイン", use_container_width=True): st.session_state.page = "cast_login"; st.rerun()
    if st.button("⚙️ 管理者ログイン", use_container_width=True): st.session_state.page = "admin_login"; st.rerun()

elif st.session_state.page == "cast_login":
    render_top_nav(); st.markdown('<div class="app-header">キャストログイン</div>', unsafe_allow_html=True)
    db = get_db_data(); casts = db.get("casts", [])
    c_sel = st.selectbox("店番とキャスト名", ["-- 選択 --"] + [f"{c['cast_id']} {c['name']}" for c in casts if c.get("name")])
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
            if st.button("開始", key=f"b_{d['driver_id']}", type="primary", use_container_width=True):
                if p_in in ["0000", str(d.get("password")).strip()]:
                    st.session_state.is_admin, st.session_state.logged_in_staff, st.session_state.page = False, d["name"], "staff_portal"; st.rerun()

# ==========================================
# 👩 キャストマイページ
# ==========================================
elif st.session_state.page == "cast_mypage":
    render_top_nav(); c = st.session_state.logged_in_cast
    db = get_db_data(); casts = db.get("casts", []); atts = db.get("attendance", [])
    st.markdown(f'<div style="text-align: center; font-weight: bold; font-size: 20px;">店番 {c["店番"]} {c["キャスト名"]} 様</div>', unsafe_allow_html=True)
    my_c = next((x for x in casts if str(x["cast_id"]) == str(c["店番"])), None)
    if my_c and not my_c.get("line_user_id"): st.error(f"⚠️ LINE未連携")
    else: st.success("✅ LINE通知：連携済み")

    tab1, tab2 = st.tabs(["当日申請", "翌日申請"])
    with tab1:
        m_tdy = next((r for r in atts if r["target_date"] == "当日" and str(r["cast_id"]) == str(c["店番"])), None)
        with st.form("f_tdy"):
            s = st.radio("状態", ["未定", "出勤", "自走", "休み"], index=["未定", "出勤", "自走", "休み"].index(m_tdy["status"] if m_tdy else "未定"), horizontal=True)
            if st.form_submit_button("送信"):
                post_api({"action": "save_attendance", "records": [{"cast_id": c["店番"], "cast_name": c["キャスト名"], "area": c["方面"], "status": s, "memo": "", "target_date": "当日"}]})
                clear_cache(); st.rerun()

# ==========================================
# 🚕 送迎管理ポータル
# ==========================================
elif st.session_state.page == "staff_portal":
    render_top_nav(); staff_n, is_adm = st.session_state.logged_in_staff, st.session_state.is_admin
    db = get_db_data(); casts, drvs, atts, sets = db.get("casts", []), db.get("drivers", []), db.get("attendance", []), db.get("settings") or {}
    today_s = datetime.datetime.now(JST).strftime("%m月%d日")
    d_names = [str(d["name"]) for d in drvs if d.get("name")]

    if not is_adm:
        # 🚙 ドライバー専用 AIナビ
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
        
        if st.session_state.current_staff_tab == "② キャスト送迎":
            att_tdy = [r for r in atts if r["target_date"] == "当日" and r["status"] in ["出勤", "自走"]]
            with st.expander(f"📋 当日キャスト一覧 ({len(att_tdy)}名)"):
                for i, r in enumerate(att_tdy):
                    render_cast_edit_card(r["cast_id"], r["cast_name"], "岡山", r, "tdy", d_names, time_slots, early_time_slots, i)
        
        elif st.session_state.current_staff_tab == "③ キャスト登録":
            for i in range(1, 151):
                c = next((x for x in casts if str(x["cast_id"]) == str(i)), {"cast_id": i, "name": "", "password": "0000"})
                with st.expander(f"店番 {i} : {c.get('name','未登録')}"):
                    with st.form(f"reg_{i}"):
                        nn = st.text_input("名前", value=c.get("name",""))
                        if st.form_submit_button("保存"):
                            post_api({"action": "save_cast", "cast_id": i, "name": nn, "password": "0000", "area": "他", "manager": "未設定"})
                            clear_cache(); st.rerun()
        
        elif st.session_state.current_staff_tab == "⚙️ 管理設定":
            with st.form("adm_set"):
                l_tk = st.text_input("アクセストークン", value=sets.get("line_access_token",""), type="password")
                if st.form_submit_button("保存"):
                    post_api({"action": "save_settings", "admin_password": sets.get("admin_password","1234"), "notice_text": sets.get("notice_text",""), "line_bot_id": sets.get("line_bot_id",""), "line_access_token": l_tk})
                    clear_cache(); st.rerun()
