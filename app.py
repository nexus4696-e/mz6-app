import os
import requests
import datetime
import urllib.parse
import time
import re
import xml.etree.ElementTree as ET

import streamlit as st
import streamlit.components.v1 as components


APP_VERSION = 39


# =========================
# Google API KEY
# =========================

try:
    GOOGLE_MAPS_API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]
except Exception:
    GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")



# =========================
# ナビボタンCSS
# =========================

NAV_BTN_STYLE = """
display:block;
text-align:center;
color:white;
padding:10px;
border-radius:8px;
font-weight:bold;
text-decoration:none;
"""


# =========================
# セッション初期化
# =========================

for k in [
    "page",
    "logged_in_cast",
    "logged_in_staff",
    "selected_staff_for_login",
    "flash_msg",
    "current_staff_tab",
]:
    if k not in st.session_state:
        st.session_state[k] = None if k != "page" else "home"

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False



# =========================
# 今日の日付
# =========================

dt = datetime.datetime.now()
today = dt.strftime("%Y-%m-%d")



# =========================
# API通信
# =========================

API_URL = "YOUR_API_ENDPOINT"


def post_api(payload):

    for _ in range(3):

        try:
            res = requests.post(API_URL, json=payload, timeout=10)

            if res.status_code == 200:
                return res.json()

        except Exception:
            time.sleep(1)

    return {}
def optimize_and_calc_route(api_key, origin, destination, tasks_list,
                            is_return=False, manual_order=False):

    if not tasks_list:
        return [], 0, [], 0, "NO_TASK"

    waypoints = []

    for t in tasks_list:

        if not isinstance(t, dict):
            continue

        addr = t.get("actual_pickup", "")

        if addr:
            waypoints.append(addr)

    if not waypoints:
        return [], 0, [], 0, "NO_WAYPOINT"

    wp = "|".join(urllib.parse.quote(x) for x in waypoints)

    url = (
        "https://maps.googleapis.com/maps/api/directions/xml?"
        f"origin={urllib.parse.quote(origin)}"
        f"&destination={urllib.parse.quote(destination)}"
        f"&waypoints=optimize:true|{wp}"
        f"&key={api_key}"
    )

    try:

        res = requests.get(url, timeout=10)

        root = ET.fromstring(res.text)

        total_sec = 0
        first_leg_sec = 0

        legs = root.findall(".//leg")

        for i, leg in enumerate(legs):

            sec = int(leg.find("duration/value").text)

            total_sec += sec

            if i == 0:
                first_leg_sec = sec

        ordered = tasks_list

        full_path = waypoints

        return ordered, total_sec, full_path, first_leg_sec, None

    except Exception:

        return tasks_list, 0, [], 0, "API_ERROR"
def run_ai_dispatch(atts, casts, drvs, active_drivers, sets, store_addr):

    learning_scores = {}

    for r in atts:

        if r.get("status") in ["出勤", "自走"] and r.get("driver_name") not in ["", "未定", None]:

            cid = str(r.get("cast_id"))
            drv = r.get("driver_name")

            if cid not in learning_scores:
                learning_scores[cid] = {}

            learning_scores[cid][drv] = learning_scores[cid].get(drv, 0) + 1


    base_time = str(sets.get("base_arrival_time", "19:50"))

    try:

        bh, bm = map(int, base_time.split(":"))
        b_mins = bh * 60 + bm

    except:

        b_mins = 19 * 60 + 50


    all_driver_updates = []

    for d in drvs:

        if d["name"] not in active_drivers:
            continue

        try:
            cap = int(d.get("capacity", 4))
        except:
            cap = 4

        assigned = atts[:cap]

        try:

            ordered_tasks, total_sec, full_path, first_leg_sec, api_err = optimize_and_calc_route(
                GOOGLE_MAPS_API_KEY,
                store_addr,
                store_addr,
                assigned,
            )

        except Exception:

            ordered_tasks = assigned
            total_sec = 0
            first_leg_sec = 0

        total_casts = len(ordered_tasks)

        if total_casts == 0:
            continue

        interval_mins = 15

        if total_sec > 0:
            interval_mins = max(1, (total_sec // 60) // (total_casts + 1))

        t_mins_list = []

        for idx in range(total_casts):

            mins_to_subtract = (total_casts - idx) * interval_mins

            t_mins = b_mins - mins_to_subtract

            if t_mins < 0:
                t_mins += 1440

            t_mins_list.append(t_mins)

        dep_m = min(t_mins_list) - (first_leg_sec // 60) - 5

        if dep_m < 0:
            dep_m += 1440

        for idx, item in enumerate(ordered_tasks):

            tm = t_mins_list[idx]

            current_calc_time = f"{(tm // 60) % 24:02d}:{tm % 60:02d}"

            all_driver_updates.append({
                "id": item["id"],
                "driver_name": d["name"],
                "pickup_time": current_calc_time
            })

    if all_driver_updates:

        post_api({
            "action": "update_manual_dispatch",
            "updates": all_driver_updates
        })
st.title("送迎管理システム")


if st.button("🚀 AI自動配車"):

    with st.spinner("AI配車計算中..."):

        run_ai_dispatch(
            atts,
            casts,
            drvs,
            active_drivers,
            sets,
            store_addr
        )

        st.success("配車完了")



# 週間表示

for i in range(7):

    d = dt + datetime.timedelta(days=i)

    dow = ["月","火","水","木","金","土","日"][d.weekday()]

    date_disp = "明日" if i == 1 else f"{d.month}/{d.day}({dow})"

    st.write(date_disp)
