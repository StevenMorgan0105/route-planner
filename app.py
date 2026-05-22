from __future__ import annotations

import datetime as dt
import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import googlemaps
except Exception:
    googlemaps = None

try:
    from streamlit_searchbox import st_searchbox
except Exception:
    st_searchbox = None

ESTIMATE_BLOCKS = [
    {"label": "8:15-9:30", "start": dt.time(8, 15), "end": dt.time(9, 30)},
    {"label": "9:30-11:00", "start": dt.time(9, 30), "end": dt.time(11, 0)},
    {"label": "11:00-12:30", "start": dt.time(11, 0), "end": dt.time(12, 30)},
    {"label": "1:00-2:30", "start": dt.time(13, 0), "end": dt.time(14, 30)},
    {"label": "2:30-4:00", "start": dt.time(14, 30), "end": dt.time(16, 0)},
    {"label": "4:00-5:30", "start": dt.time(16, 0), "end": dt.time(17, 30)},
]
BLOCK_LABELS = [b["label"] for b in ESTIMATE_BLOCKS]
DEFAULT_ESTIMATORS = ["Jon", "Jut", "Lindsay"]
DEFAULT_ESTIMATOR_HOMES = {"Jon": "Tellico Plains, TN", "Jut": "Red Bank, TN", "Lindsay": "Chickamauga, GA"}
DEFAULT_ESTIMATOR_BLOCKS = {"Jon": BLOCK_LABELS, "Jut": BLOCK_LABELS, "Lindsay": BLOCK_LABELS[1:-1]}
HOME_PULL_BY_BLOCK_INDEX = [0.0, 0.2, 0.5, 1.25, 2.5, 4.0]
PRIORITY_SCORE = {"Emergency": 5, "High": 4, "Normal": 3, "Low": 2}
LEAD_COLUMNS = ["Lead Name", "Address", "Available Blocks", "Priority", "Required Estimator", "Notes"]

LOCAL_SEARCH_CENTER = "Chattanooga, TN"
LOCAL_SEARCH_LAT_LNG = (35.0456, -85.3097)
LOCAL_SEARCH_RADIUS_MILES = 75
LOCAL_SEARCH_RADIUS_METERS = int(LOCAL_SEARCH_RADIUS_MILES * 1609.34)
LOCAL_STATES = ["TN", "GA", "AL"]


@dataclass
class Estimator:
    name: str
    home_address: str
    available_blocks: List[str]

    @property
    def start_address(self) -> str:
        return self.home_address


@dataclass
class Lead:
    name: str
    address: str
    available_blocks: List[str]
    priority: str
    required_estimator: str
    notes: str = ""


st.set_page_config(page_title="Tree Estimate Route Planner", page_icon="🌲", layout="wide")
st.markdown("""
<style>
:root{--forest:#064d25;--green:#0f6b2f;--line:#cfe6ca;--text:#0f2416}.stApp{background:linear-gradient(135deg,#f7fbf4 0%,#fff 52%,#edf7ea 100%)}section[data-testid="stSidebar"]{background:linear-gradient(180deg,#043d1d 0%,#075328 55%,#053a1c 100%)}section[data-testid="stSidebar"] *{color:#fff!important}.hero-card,.section-card,.route-card,.estimator-card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px;margin:12px 0;box-shadow:0 10px 24px rgba(6,77,37,.06)}.hero-card{background:linear-gradient(135deg,#fff 0%,#f0faee 100%)}.hero-title{font-size:2rem;font-weight:900;color:var(--forest)}.notice-card{background:#eef9ed;border-left:6px solid #2f9e44;border-radius:14px;padding:14px 16px;margin:8px 0 20px}.step-title{color:var(--forest);font-weight:850;font-size:1.2rem}.step-pill{display:inline-flex;width:28px;height:28px;border-radius:50%;background:var(--green);color:#fff;align-items:center;justify-content:center;margin-right:8px}.block-chip,.metric-pill{display:inline-block;padding:6px 10px;margin:3px;border-radius:8px;background:#dff3d9;border:1px solid #bfe3b8;color:#0b4b22;font-weight:700}.metric-pill{border-radius:999px}.stButton>button,.stDownloadButton>button{background:linear-gradient(180deg,#0f7a36 0%,#075328 100%)!important;color:white!important;border-radius:10px!important;font-weight:800!important}.footer-tree{text-align:center;color:#2a6b38;font-weight:700;margin-top:30px}
</style>
""", unsafe_allow_html=True)


def saved_key() -> str:
    try:
        return str(st.secrets.get("GOOGLE_MAPS_API_KEY", "")).strip()
    except Exception:
        return os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()


def fmt_date(d: dt.date) -> str:
    return d.strftime("%m/%d/%Y")


def file_date(d: dt.date) -> str:
    return d.strftime("%m-%d-%Y")


def date_input_mmddyyyy(label: str, value: dt.date) -> dt.date:
    try:
        return st.date_input(label, value=value, format="MM/DD/YYYY")
    except TypeError:
        selected = st.date_input(label, value=value)
        st.caption(f"Selected date: {fmt_date(selected)}")
        return selected


def block_time(block: dict) -> str:
    return f"{block['start'].strftime('%I:%M %p').lstrip('0')} - {block['end'].strftime('%I:%M %p').lstrip('0')}"


def is_blank(v) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return str(v).strip() == ""


def norm_estimator(v) -> str:
    if is_blank(v):
        return "Any"
    text = str(v).strip()
    return "Any" if text.lower() in ["any", "none", "no preference", "all"] else text


def clean_priority(v) -> str:
    text = "Normal" if is_blank(v) else str(v).strip().title()
    return text if text in PRIORITY_SCORE else "Normal"


def block_display(blocks: List[str]) -> str:
    return "Any" if not blocks or set(blocks) == set(BLOCK_LABELS) else ", ".join(blocks)


def parse_blocks(v) -> List[str]:
    if isinstance(v, list):
        found = [x for x in v if x in BLOCK_LABELS]
        return found or BLOCK_LABELS.copy()
    if is_blank(v) or str(v).strip().lower() in ["any", "all", "open"]:
        return BLOCK_LABELS.copy()
    simplified = str(v).lower().replace(" ", "").replace("am", "").replace("pm", "")
    found = [b for b in BLOCK_LABELS if b.lower().replace(" ", "") in simplified or b.split("-")[0].lower() in simplified]
    return found or BLOCK_LABELS.copy()


def chips(blocks: List[str]) -> str:
    return "".join(f"<span class='block-chip'>{b}</span>" for b in blocks)


def blank_df() -> pd.DataFrame:
    return pd.DataFrame(columns=LEAD_COLUMNS)


def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in LEAD_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[LEAD_COLUMNS].dropna(how="all")
    df = df[~(df["Lead Name"].apply(is_blank) & df["Address"].apply(is_blank))]
    if len(df):
        df["Lead Name"] = df["Lead Name"].apply(lambda x: "Lead" if is_blank(x) else str(x).strip())
        df["Address"] = df["Address"].apply(lambda x: "" if is_blank(x) else str(x).strip())
        df["Available Blocks"] = df["Available Blocks"].apply(lambda x: block_display(parse_blocks(x)))
        df["Priority"] = df["Priority"].apply(clean_priority)
        df["Required Estimator"] = df["Required Estimator"].apply(norm_estimator)
        df["Notes"] = df["Notes"].apply(lambda x: "" if is_blank(x) else str(x).strip())
    return df.reset_index(drop=True)


def local_only(descriptions: List[str]) -> List[str]:
    return [d for d in descriptions if any(f", {state}," in f", {d}," for state in LOCAL_STATES)]


def google_address_predictions(client, query: str, country_code: str = "us") -> List[str]:
    if not client or len(query.strip()) < 3:
        return []
    try:
        results = client.places_autocomplete(
            input_text=query.strip(),
            types="address",
            components={"country": country_code},
            location=LOCAL_SEARCH_LAT_LNG,
            radius=LOCAL_SEARCH_RADIUS_METERS,
            strict_bounds=True,
        )
        descriptions = [r.get("description", "") for r in results if r.get("description")]
        return local_only(descriptions)
    except Exception:
        return []


def add_lead(name, address, blocks, priority, estimator, notes) -> None:
    row = pd.DataFrame([{
        "Lead Name": name.strip() or "Lead",
        "Address": address.strip(),
        "Available Blocks": block_display(blocks),
        "Priority": clean_priority(priority),
        "Required Estimator": norm_estimator(estimator),
        "Notes": notes.strip(),
    }], columns=LEAD_COLUMNS)
    st.session_state.leads_df = clean_df(pd.concat([st.session_state.leads_df, row], ignore_index=True))


def to_leads(df: pd.DataFrame) -> List[Lead]:
    leads = []
    for _, row in clean_df(df).iterrows():
        if not is_blank(row["Address"]):
            leads.append(Lead(row["Lead Name"], row["Address"], parse_blocks(row["Available Blocks"]), clean_priority(row["Priority"]), norm_estimator(row["Required Estimator"]), str(row.get("Notes", "")).strip()))
    return leads


def drive_minutes(cache: Dict[Tuple[str, str], int], client, origin: str, dest: str) -> int:
    key = (origin, dest)
    if key in cache:
        return cache[key]
    minutes = None
    if client:
        try:
            el = client.distance_matrix([origin], [dest], mode="driving", units="imperial")["rows"][0]["elements"][0]
            if el.get("status") == "OK":
                minutes = round(el["duration"]["value"] / 60)
        except Exception:
            pass
    if minutes is None:
        minutes = 12 + (sum(ord(ch) for ch in f"{origin}|{dest}".lower()) % 26)
    cache[key] = minutes
    return minutes


def can_take(est: Estimator, lead: Lead, block: str) -> bool:
    req = norm_estimator(lead.required_estimator)
    return block in est.available_blocks and block in lead.available_blocks and (req == "Any" or req.lower() == est.name.lower())


def choose_lead(est: Estimator, block_index: int, block: str, current: str, remaining: List[Lead], cache, client):
    choices = []
    home_pull = HOME_PULL_BY_BLOCK_INDEX[min(block_index, len(HOME_PULL_BY_BLOCK_INDEX) - 1)]
    for lead in remaining:
        if not can_take(est, lead, block):
            continue
        drive_prev = drive_minutes(cache, client, current, lead.address)
        drive_home = drive_minutes(cache, client, lead.address, est.home_address)
        score = (-PRIORITY_SCORE.get(lead.priority, 3) * 1000) + (len(lead.available_blocks) * 40) + (drive_prev * 5) + (drive_home * home_pull)
        if norm_estimator(lead.required_estimator) != "Any":
            score -= 150
        choices.append((score, lead, drive_prev, drive_home))
    if not choices:
        return None
    return sorted(choices, key=lambda x: x[0])[0][1:]


def build_routes(estimators: List[Estimator], leads: List[Lead], client):
    remaining = leads.copy()
    routes = {e.name: [] for e in estimators}
    current = {e.name: e.start_address for e in estimators}
    summaries = {}
    cache = {}
    for i, block in enumerate(ESTIMATE_BLOCKS):
        for est in estimators:
            choice = choose_lead(est, i, block["label"], current[est.name], remaining, cache, client)
            if not choice:
                continue
            lead, drive_prev, drive_home = choice
            routes[est.name].append({
                "Estimate Block": block["label"],
                "Estimate Time": block_time(block),
                "Lead": lead.name,
                "Address": lead.address,
                "Priority": lead.priority,
                "Required Estimator": lead.required_estimator,
                "Drive From Previous (min)": drive_prev,
                "Drive From Stop To Home (min)": drive_home,
                "Notes": lead.notes,
            })
            current[est.name] = lead.address
            remaining.remove(lead)
    for est in estimators:
        rows = routes.get(est.name, [])
        final_home = drive_minutes(cache, client, rows[-1]["Address"], est.home_address) if rows else 0
        summaries[est.name] = {"home_address": est.home_address, "final_drive_home": final_home}
    return routes, remaining, summaries


def maps_link(home: str, rows: List[dict]) -> str:
    if not rows:
        return ""
    stops = [r["Address"] for r in rows]
    url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote_plus(home)}&destination={urllib.parse.quote_plus(home)}&travelmode=driving"
    return url + "&waypoints=" + "|".join(urllib.parse.quote_plus(s) for s in stops)


def validate(df: pd.DataFrame, estimator_names: List[str]) -> List[str]:
    errors = []
    lookup = [n.lower() for n in estimator_names]
    for i, row in df.iterrows():
        if is_blank(row["Address"]):
            errors.append(f"Row {i + 1} is missing an address.")
        req = norm_estimator(row["Required Estimator"])
        if req != "Any" and req.lower() not in lookup:
            errors.append(f"Row {i + 1} is assigned to {req}, but that estimator is not marked as working today.")
    return errors


st.markdown("""
<div class="hero-card"><div class="hero-title">🌲 TREE ESTIMATE ROUTE PLANNER</div><div>Plan efficient daily routes for tree estimate appointments.</div></div>
<div class="notice-card">🍃 <strong>Each estimate takes the full assigned time block.</strong> Address autocomplete is restricted to the local Chattanooga service area.</div>
""", unsafe_allow_html=True)

if "leads_df" not in st.session_state:
    st.session_state.leads_df = blank_df()

with st.sidebar:
    st.markdown("<div style='text-align:center;padding:10px 0 18px;'><div style='font-size:3rem;'>🌳</div><div style='font-size:1.35rem;font-weight:900;'>TREE ROUTE</div><div>Estimate Planner</div></div>", unsafe_allow_html=True)
    service_date = date_input_mmddyyyy("Service date", dt.date.today())
    st.caption(f"Using date: {fmt_date(service_date)}")
    st.markdown("---")
    st.markdown("**Estimate blocks**")
    for b in ESTIMATE_BLOCKS:
        st.write(f"🌿 {b['label']}")
    st.markdown("---")
    st.header("Google Maps")
    key = saved_key() or st.text_input("Google Maps API key", type="password")
    country_code = st.text_input("Autocomplete country code", value="us", max_chars=2).lower()
    st.caption(f"Autocomplete is locked to about {LOCAL_SEARCH_RADIUS_MILES} miles around {LOCAL_SEARCH_CENTER}.")
    gmaps_client = None
    if key and googlemaps:
        try:
            gmaps_client = googlemaps.Client(key=key)
            st.success("Google Maps enabled.")
        except Exception as exc:
            st.error(f"Could not load Google Maps: {exc}")

st.markdown("<div class='section-card'><div class='step-title'><span class='step-pill'>1</span>Who Is Working Today?</div>", unsafe_allow_html=True)
working = st.multiselect("Select estimators working this date", DEFAULT_ESTIMATORS, default=DEFAULT_ESTIMATORS)
estimators: List[Estimator] = []
if working:
    cols = st.columns(len(working))
    for idx, name in enumerate(working):
        with cols[idx]:
            allowed = DEFAULT_ESTIMATOR_BLOCKS.get(name, BLOCK_LABELS)
            home = st.text_input(f"{name} start/end home location", value=DEFAULT_ESTIMATOR_HOMES.get(name, ""), key=f"home_{name}")
            blocks = st.multiselect(f"{name} available blocks", allowed, default=allowed, key=f"blocks_{name}")
            if name == "Lindsay":
                st.caption("Lindsay does not use the 8:15-9:30 or 4:00-5:30 blocks.")
            st.markdown(f"<div class='estimator-card'><b>🏡 {name}</b><br>{home}<br>{chips(blocks or allowed)}</div>", unsafe_allow_html=True)
            estimators.append(Estimator(name, home.strip() or DEFAULT_ESTIMATOR_HOMES.get(name, ""), blocks or allowed.copy()))
st.markdown("</div>", unsafe_allow_html=True)

estimator_names = [e.name for e in estimators]
estimator_options = ["Any"] + estimator_names

st.markdown("<div class='section-card'><div class='step-title'><span class='step-pill'>2</span>Add Lead with Local Google Autocomplete</div>", unsafe_allow_html=True)
if not gmaps_client:
    st.warning("Google Maps is not enabled yet.")


def address_search(term: str) -> List[str]:
    return google_address_predictions(gmaps_client, term, country_code)

selected_address = ""
if st_searchbox is None:
    st.error("Run: pip install -r requirements.txt")
else:
    selected_address = st_searchbox(address_search, key="address", placeholder="Start typing customer address", label="Customer address", clear_on_submit=False) or ""
    if selected_address:
        st.success(f"Selected Google address: {selected_address}")
    else:
        st.info("Start typing at least 3 characters and choose a local Google suggestion.")

c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    new_name = st.text_input("Customer name", placeholder="John Smith")
    new_notes = st.text_input("Notes", placeholder="Gate code, call before arrival, tree concern, etc.")
with c2:
    new_blocks = st.multiselect("Customer available estimate blocks", BLOCK_LABELS, default=BLOCK_LABELS)
with c3:
    new_priority = st.selectbox("Priority", ["Emergency", "High", "Normal", "Low"], index=2)
    new_estimator = st.selectbox("Required estimator", estimator_options, index=0)
if st.button("➕ Add Google Address Lead", type="primary"):
    if is_blank(selected_address):
        st.error("Select a local Google address suggestion before adding the lead.")
    elif not estimator_names:
        st.error("Select at least one working estimator before adding leads.")
    else:
        add_lead(new_name, selected_address, new_blocks, new_priority, new_estimator, new_notes)
        st.success("Lead added.")
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<div class='section-card'><div class='step-title'><span class='step-pill'>3</span>Review Leads / Estimates</div>", unsafe_allow_html=True)
current_df = clean_df(st.session_state.leads_df)
column_config = {
    "Priority": st.column_config.SelectboxColumn("Priority", options=["Emergency", "High", "Normal", "Low"], required=True),
    "Required Estimator": st.column_config.SelectboxColumn("Required Estimator", options=estimator_options, required=True),
}
edited_df = st.data_editor(current_df, num_rows="dynamic", use_container_width=True, column_config=column_config, key="editor")
st.session_state.leads_df = clean_df(edited_df)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<div class='section-card'><div class='step-title'><span class='step-pill'>4</span>Route Plan</div>", unsafe_allow_html=True)
errors = [] if estimator_names else ["Select at least one working estimator."]
errors.extend(validate(st.session_state.leads_df, estimator_names))
for e in errors:
    st.error(e)

if st.button("🔄 Build / Optimize Routes", type="primary", use_container_width=True):
    if errors:
        st.stop()
    leads = to_leads(st.session_state.leads_df)
    if not leads:
        st.error("Add at least one lead first.")
        st.stop()
    routes, unassigned, summaries = build_routes(estimators, leads, gmaps_client)
    st.success(f"Scheduled {sum(len(r) for r in routes.values())} of {len(leads)} lead(s) for {fmt_date(service_date)}.")
    export_rows = []
    cols = st.columns(max(1, len(estimators)))
    for idx, est in enumerate(estimators):
        rows = routes.get(est.name, [])
        with cols[idx]:
            st.markdown("<div class='route-card'>", unsafe_allow_html=True)
            st.markdown(f"### 🌲 {est.name}")
            st.caption(f"Start/End home: {est.home_address}")
            if rows:
                final = summaries[est.name]["final_drive_home"]
                st.markdown(f"<span class='metric-pill'>Stops: {len(rows)}</span><span class='metric-pill'>Drive home: {final} min</span>", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                st.markdown(f"[Open {est.name}'s full route from home back to home]({maps_link(est.home_address, rows)})")
                copyable = "\n".join([f"{r['Estimate Block']} - {r['Lead']} - {r['Address']}" for r in rows])
                st.text_area(f"Copyable schedule for {est.name}", f"Start at home: {est.home_address}\n{copyable}\nEnd at home: {est.home_address}", height=150)
                export_rows.extend([{ "Date": fmt_date(service_date), "Estimator": est.name, "Start Location": est.home_address, "End Location": est.home_address, "Final Drive Home (min)": final, **r } for r in rows])
            else:
                st.info("No leads scheduled for this estimator.")
            st.markdown("</div>", unsafe_allow_html=True)
    if unassigned:
        st.markdown("### Unscheduled Leads")
        st.dataframe(pd.DataFrame([{ "Lead": l.name, "Address": l.address, "Available Blocks": block_display(l.available_blocks), "Priority": l.priority, "Required Estimator": l.required_estimator, "Reason": "Could not fit within rules." } for l in unassigned]), use_container_width=True, hide_index=True)
    if export_rows:
        export_df = pd.DataFrame(export_rows)
        st.download_button("⬇ Export Routes", export_df.to_csv(index=False).encode("utf-8"), f"estimator_routes_{file_date(service_date)}.csv", "text/csv")
st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<div class='footer-tree'>🍃 Care for trees. Care for tomorrow. 🌳</div>", unsafe_allow_html=True)
