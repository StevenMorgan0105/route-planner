from __future__ import annotations

import datetime as dt
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import googlemaps
except Exception:
    googlemaps = None

LEAD_COLUMNS = [
    "Lead Name",
    "Address",
    "Duration Minutes",
    "Earliest",
    "Latest",
    "Priority",
    "Required Estimator",
    "Notes",
]

PRIORITY_SCORE = {"Emergency": 5, "High": 4, "Normal": 3, "Low": 2}


@dataclass
class Estimator:
    name: str
    start_address: str
    available_start: dt.time
    available_end: dt.time


@dataclass
class Lead:
    name: str
    address: str
    duration_minutes: int
    earliest: dt.time
    latest: dt.time
    priority: str
    required_estimator: str
    notes: str = ""


def is_blank(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""


def parse_time(value, fallback: dt.time) -> dt.time:
    if is_blank(value):
        return fallback
    if isinstance(value, dt.time):
        return value
    text = str(value).strip()
    for fmt in ["%H:%M", "%I:%M %p", "%I %p", "%H:%M:%S"]:
        try:
            return dt.datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    return fallback


def parse_minutes(value, fallback: int = 45) -> int:
    if is_blank(value):
        return fallback
    try:
        return max(15, min(int(float(value)), 240))
    except Exception:
        return fallback


def clean_priority(value) -> str:
    if is_blank(value):
        return "Normal"
    text = str(value).strip().title()
    return text if text in PRIORITY_SCORE else "Normal"


def normalize_estimator(value) -> str:
    if is_blank(value):
        return "Any"
    text = str(value).strip()
    return "Any" if text.lower() in ["any", "none", "no preference"] else text


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
        df["Duration Minutes"] = df["Duration Minutes"].apply(lambda x: parse_minutes(x, 45))
        df["Earliest"] = df["Earliest"].apply(lambda x: parse_time(x, dt.time(8, 0)).strftime("%H:%M"))
        df["Latest"] = df["Latest"].apply(lambda x: parse_time(x, dt.time(17, 0)).strftime("%H:%M"))
        df["Priority"] = df["Priority"].apply(clean_priority)
        df["Required Estimator"] = df["Required Estimator"].apply(normalize_estimator)
        df["Notes"] = df["Notes"].apply(lambda x: "" if is_blank(x) else str(x).strip())
    return df.reset_index(drop=True)


def combine(date: dt.date, time_value: dt.time) -> dt.datetime:
    return dt.datetime.combine(date, time_value)


def google_address_predictions(client, query: str, country_code: str = "us") -> Tuple[List[str], Optional[str]]:
    if not client:
        return [], "Add a Google Maps API key first."
    if len(query.strip()) < 3:
        return [], "Type at least 3 characters."
    try:
        results = client.places_autocomplete(
            input_text=query.strip(),
            types="address",
            components={"country": country_code},
        )
        return [r.get("description", "") for r in results if r.get("description")], None
    except Exception as exc:
        return [], f"Google address lookup failed: {exc}"


def add_lead(name, address, duration, earliest, latest, priority, required_estimator, notes):
    new_row = pd.DataFrame([
        {
            "Lead Name": name.strip() or "Lead",
            "Address": address.strip(),
            "Duration Minutes": duration,
            "Earliest": earliest.strftime("%H:%M"),
            "Latest": latest.strftime("%H:%M"),
            "Priority": clean_priority(priority),
            "Required Estimator": normalize_estimator(required_estimator),
            "Notes": notes.strip(),
        }
    ])
    st.session_state.leads_df = clean_df(pd.concat([st.session_state.leads_df, new_row], ignore_index=True))


def parse_bulk(text: str, default_duration: int) -> pd.DataFrame:
    rows = []
    for i, line in enumerate([l.strip() for l in text.splitlines() if l.strip()], start=1):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 1:
            name, address, earliest, latest, estimator, notes = f"Lead {i}", parts[0], "08:00", "17:00", "Any", ""
        elif len(parts) == 2:
            name, address, earliest, latest, estimator, notes = parts[0] or f"Lead {i}", parts[1], "08:00", "17:00", "Any", ""
        else:
            name = parts[0] or f"Lead {i}"
            address = parts[1]
            earliest = parts[2] if len(parts) > 2 and parts[2] else "08:00"
            latest = parts[3] if len(parts) > 3 and parts[3] else "17:00"
            estimator = parts[4] if len(parts) > 4 and parts[4] else "Any"
            notes = parts[5] if len(parts) > 5 and parts[5] else ""
        if address:
            rows.append({
                "Lead Name": name,
                "Address": address,
                "Duration Minutes": default_duration,
                "Earliest": parse_time(earliest, dt.time(8, 0)).strftime("%H:%M"),
                "Latest": parse_time(latest, dt.time(17, 0)).strftime("%H:%M"),
                "Priority": "Normal",
                "Required Estimator": normalize_estimator(estimator),
                "Notes": notes,
            })
    return pd.DataFrame(rows, columns=LEAD_COLUMNS)


def drive_minutes(cache: Dict[Tuple[str, str], int], client, origin: str, destination: str) -> int:
    key = (origin, destination)
    if key in cache:
        return cache[key]
    minutes = None
    if client:
        try:
            result = client.distance_matrix([origin], [destination], mode="driving", units="imperial")
            element = result["rows"][0]["elements"][0]
            if element.get("status") == "OK":
                minutes = round(element["duration"]["value"] / 60)
        except Exception:
            minutes = None
    if minutes is None:
        minutes = 12 + (sum(ord(ch) for ch in f"{origin}|{destination}".lower()) % 26)
    cache[key] = minutes
    return minutes


def matches(lead: Lead, estimator: Estimator) -> bool:
    required = normalize_estimator(lead.required_estimator)
    return required == "Any" or required.lower() == estimator.name.lower()


def to_leads(df: pd.DataFrame, default_duration: int) -> List[Lead]:
    leads = []
    for _, row in clean_df(df).iterrows():
        if is_blank(row["Address"]):
            continue
        leads.append(Lead(
            name=str(row["Lead Name"]).strip() or "Lead",
            address=str(row["Address"]).strip(),
            duration_minutes=parse_minutes(row["Duration Minutes"], default_duration),
            earliest=parse_time(row["Earliest"], dt.time(8, 0)),
            latest=parse_time(row["Latest"], dt.time(17, 0)),
            priority=clean_priority(row["Priority"]),
            required_estimator=normalize_estimator(row["Required Estimator"]),
            notes=str(row.get("Notes", "")).strip(),
        ))
    return leads


def choose_next(estimator: Estimator, current_location: str, current_time: dt.datetime, service_date: dt.date, remaining: List[Lead], cache, client, buffer: int):
    candidates = []
    estimator_end = combine(service_date, estimator.available_end)
    for lead in remaining:
        if not matches(lead, estimator):
            continue
        earliest = combine(service_date, lead.earliest)
        latest = combine(service_date, lead.latest)
        drive = drive_minutes(cache, client, current_location, lead.address)
        start = max(current_time + dt.timedelta(minutes=drive), earliest)
        end = start + dt.timedelta(minutes=lead.duration_minutes)
        if start > latest or end > latest or end > estimator_end:
            continue
        priority_score = PRIORITY_SCORE.get(lead.priority, 3)
        deadline_minutes = max(0, int((latest - current_time).total_seconds() // 60))
        score = (-priority_score * 1000) + (deadline_minutes * 2) + (drive * 5)
        candidates.append((score, lead, drive, start, end))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1:]


def build_routes(estimators: List[Estimator], leads: List[Lead], service_date: dt.date, buffer: int, client):
    remaining = leads.copy()
    routes = {e.name: [] for e in estimators}
    cache = {}
    for estimator in sorted(estimators, key=lambda e: e.available_start):
        current_location = estimator.start_address
        current_time = combine(service_date, estimator.available_start)
        while remaining:
            choice = choose_next(estimator, current_location, current_time, service_date, remaining, cache, client, buffer)
            if not choice:
                break
            lead, drive, start, end = choice
            routes[estimator.name].append({
                "Lead": lead.name,
                "Address": lead.address,
                "Priority": lead.priority,
                "Required Estimator": lead.required_estimator,
                "Drive Minutes": drive,
                "Appointment Start": start.strftime("%I:%M %p"),
                "Appointment End": end.strftime("%I:%M %p"),
                "Duration Minutes": lead.duration_minutes,
                "Notes": lead.notes,
            })
            current_location = lead.address
            current_time = end + dt.timedelta(minutes=buffer)
            remaining.remove(lead)
    return routes, remaining


def maps_link(start_address: str, rows: List[dict]) -> str:
    if not rows:
        return ""
    addresses = [r["Address"] for r in rows]
    origin = urllib.parse.quote_plus(start_address)
    destination = urllib.parse.quote_plus(addresses[-1])
    waypoints = "|".join(urllib.parse.quote_plus(a) for a in addresses[:-1])
    url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode=driving"
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url


st.set_page_config(page_title="Estimator Route Planner", page_icon="🌲", layout="wide")
st.title("Estimator Route Planner")
st.caption("Search Google Maps addresses, set customer availability, assign estimators, and build suggested routes.")

if "leads_df" not in st.session_state:
    st.session_state.leads_df = blank_df()
if "address_suggestions" not in st.session_state:
    st.session_state.address_suggestions = []

with st.sidebar:
    st.header("Route Settings")
    service_date = st.date_input("Service date", value=dt.date.today())
    default_duration = int(st.number_input("Default estimate length", min_value=15, max_value=180, value=45, step=15))
    buffer_minutes = int(st.number_input("Buffer between stops", min_value=0, max_value=60, value=10, step=5))
    st.divider()
    st.header("Google Maps")
    google_api_key = st.text_input("Google Maps API key", type="password")
    country_code = st.text_input("Autocomplete country code", value="us", max_chars=2).lower()
    st.caption("Enable Places API for address lookup and Distance Matrix API for real drive times.")

    gmaps_client = None
    if google_api_key:
        if googlemaps is None:
            st.warning("googlemaps is not installed. Run: pip install googlemaps")
        else:
            try:
                gmaps_client = googlemaps.Client(key=google_api_key)
                st.success("Google Maps enabled.")
            except Exception as exc:
                st.error(f"Could not load Google Maps: {exc}")

st.subheader("1. Estimator Setup")
estimator_count = int(st.number_input("How many estimators are scheduling today?", min_value=1, max_value=10, value=2, step=1))
estimator_cols = st.columns(estimator_count)
estimators = []
for i in range(estimator_count):
    with estimator_cols[i]:
        st.markdown(f"**Estimator {i + 1}**")
        name = st.text_input(f"Name {i + 1}", value=f"Estimator {i + 1}", key=f"name_{i}")
        start_address = st.text_input(f"Start address {i + 1}", value="Chattanooga, TN", key=f"start_address_{i}")
        start_time = st.time_input(f"Start time {i + 1}", value=dt.time(8, 0), key=f"start_time_{i}")
        end_time = st.time_input(f"End time {i + 1}", value=dt.time(17, 0), key=f"end_time_{i}")
        estimators.append(Estimator(name.strip() or f"Estimator {i + 1}", start_address.strip() or "Chattanooga, TN", start_time, end_time))

estimator_names = [e.name for e in estimators]
estimator_options = ["Any"] + estimator_names

st.subheader("2. Add Lead with Address Search")
if not gmaps_client:
    st.info("Add a Google Maps API key in the sidebar for live address suggestions. Manual address entry still works.")

lookup_col, button_col = st.columns([4, 1])
with lookup_col:
    address_query = st.text_input("Start typing customer address", placeholder="Example: 123 Main St Chattanooga")
with button_col:
    st.write("")
    st.write("")
    if st.button("Search", use_container_width=True):
        suggestions, err = google_address_predictions(gmaps_client, address_query, country_code)
        st.session_state.address_suggestions = suggestions
        if err:
            st.warning(err)
        elif not suggestions:
            st.warning("No matching addresses found. Try adding city and state.")

if st.session_state.address_suggestions:
    selected_address = st.selectbox("Choose the correct address", st.session_state.address_suggestions)
else:
    selected_address = st.text_input("Manual address", value=address_query or "")

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    new_name = st.text_input("Customer name", placeholder="John Smith")
    new_notes = st.text_input("Notes", placeholder="Gate code, call before arrival, tree concern, etc.")
with c2:
    new_earliest = st.time_input("Customer earliest", value=dt.time(8, 0))
    new_latest = st.time_input("Customer latest", value=dt.time(17, 0))
with c3:
    new_duration = int(st.number_input("Estimate duration", min_value=15, max_value=240, value=default_duration, step=15))
    new_priority = st.selectbox("Priority", ["Emergency", "High", "Normal", "Low"], index=2)
    new_estimator = st.selectbox("Required estimator", estimator_options, index=0)

if st.button("Add Lead to Route List", type="primary"):
    if is_blank(selected_address):
        st.error("Add or select an address before adding the lead.")
    elif combine(dt.date.today(), new_earliest) >= combine(dt.date.today(), new_latest):
        st.error("Customer latest time must be after earliest time.")
    else:
        add_lead(new_name, selected_address, new_duration, new_earliest, new_latest, new_priority, new_estimator, new_notes)
        st.success("Lead added.")

with st.expander("Optional: bulk paste leads"):
    st.code("John Smith | 123 Main St, Chattanooga, TN | 09:00 | 12:00 | Any | Call before arrival", language="text")
    bulk_text = st.text_area("Paste leads", height=120)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Add Pasted Leads", use_container_width=True):
            parsed = parse_bulk(bulk_text, default_duration)
            if len(parsed):
                st.session_state.leads_df = clean_df(pd.concat([st.session_state.leads_df, parsed], ignore_index=True))
                st.success(f"Added {len(parsed)} lead(s).")
            else:
                st.warning("Paste at least one lead first.")
    with b2:
        if st.button("Clear All Leads", use_container_width=True):
            st.session_state.leads_df = blank_df()
            st.success("Lead table cleared.")

st.subheader("3. Review Leads")
current_df = clean_df(st.session_state.leads_df)
column_config = {
    "Priority": st.column_config.SelectboxColumn("Priority", options=["Emergency", "High", "Normal", "Low"], required=True),
    "Required Estimator": st.column_config.SelectboxColumn("Required Estimator", options=estimator_options, required=True),
    "Duration Minutes": st.column_config.NumberColumn("Duration Minutes", min_value=15, max_value=240, step=15, required=True),
}
edited_df = st.data_editor(current_df, num_rows="dynamic", use_container_width=True, column_config=column_config, key="lead_editor")
st.session_state.leads_df = clean_df(edited_df)

st.subheader("4. Generate Routes")
errors = []
for i, row in st.session_state.leads_df.iterrows():
    if is_blank(row["Address"]):
        errors.append(f"Row {i + 1} is missing an address.")
    required = normalize_estimator(row["Required Estimator"])
    if required != "Any" and required.lower() not in [n.lower() for n in estimator_names]:
        errors.append(f"Row {i + 1} is assigned to an estimator that does not exist.")
for e in errors:
    st.error(e)

if st.button("Build Today's Routes", type="primary", use_container_width=True):
    if errors:
        st.stop()
    leads = to_leads(st.session_state.leads_df, default_duration)
    if not leads:
        st.error("Add at least one lead first.")
        st.stop()
    routes, unassigned = build_routes(estimators, leads, service_date, buffer_minutes, gmaps_client)
    st.success(f"Scheduled {sum(len(r) for r in routes.values())} of {len(leads)} lead(s).")

    export_rows = []
    for estimator in estimators:
        rows = routes.get(estimator.name, [])
        st.markdown(f"### {estimator.name}")
        if not rows:
            st.info("No leads scheduled for this estimator.")
            continue
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        link = maps_link(estimator.start_address, rows)
        if link:
            st.markdown(f"[Open {estimator.name}'s route in Google Maps]({link})")
        st.text_area(
            f"Copyable schedule for {estimator.name}",
            value="\n".join([f"{r['Appointment Start']} - {r['Lead']} - {r['Address']}" for r in rows]),
            height=120,
            key=f"schedule_{estimator.name}",
        )
        export_rows.extend([{"Estimator": estimator.name, **r} for r in rows])

    if unassigned:
        st.markdown("### Unscheduled Leads")
        st.dataframe(pd.DataFrame([
            {
                "Lead": l.name,
                "Address": l.address,
                "Earliest": l.earliest.strftime("%I:%M %p"),
                "Latest": l.latest.strftime("%I:%M %p"),
                "Priority": l.priority,
                "Required Estimator": l.required_estimator,
                "Reason": "Could not fit within estimator availability, customer availability, or required estimator rule.",
            }
            for l in unassigned
        ]), use_container_width=True, hide_index=True)

    if export_rows:
        export_df = pd.DataFrame(export_rows)
        st.download_button(
            "Download route schedule CSV",
            data=export_df.to_csv(index=False).encode("utf-8"),
            file_name=f"estimator_routes_{service_date}.csv",
            mime="text/csv",
        )
