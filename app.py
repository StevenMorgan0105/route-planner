from __future__ import annotations

import datetime as dt
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


# -----------------------------
# Core schedule settings
# -----------------------------

ESTIMATE_BLOCKS = [
    {"label": "8:15-9:30", "start": dt.time(8, 15), "end": dt.time(9, 30)},
    {"label": "9:30-11:00", "start": dt.time(9, 30), "end": dt.time(11, 0)},
    {"label": "11:00-12:30", "start": dt.time(11, 0), "end": dt.time(12, 30)},
    {"label": "1:00-2:30", "start": dt.time(13, 0), "end": dt.time(14, 30)},
    {"label": "2:30-4:00", "start": dt.time(14, 30), "end": dt.time(16, 0)},
    {"label": "4:00-5:30", "start": dt.time(16, 0), "end": dt.time(17, 30)},
]

BLOCK_LABELS = [block["label"] for block in ESTIMATE_BLOCKS]
DEFAULT_ESTIMATORS = ["Jon", "Jut", "Lindsay"]
DEFAULT_ESTIMATOR_HOMES = {
    "Jon": "Tellico Plains, TN",
    "Jut": "Red Bank, TN",
    "Lindsay": "Chickamauga, GA",
}

# Lindsay permanently does not work the first or last estimate block.
DEFAULT_ESTIMATOR_BLOCKS = {
    "Jon": BLOCK_LABELS,
    "Jut": BLOCK_LABELS,
    "Lindsay": BLOCK_LABELS[1:-1],
}

# Pull routes toward home more strongly later in the day.
HOME_PULL_BY_BLOCK_INDEX = [0.0, 0.2, 0.5, 1.25, 2.5, 4.0]

LEAD_COLUMNS = [
    "Lead Name",
    "Address",
    "Available Blocks",
    "Priority",
    "Required Estimator",
    "Notes",
]

PRIORITY_SCORE = {"Emergency": 5, "High": 4, "Normal": 3, "Low": 2}


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


# -----------------------------
# Streamlit setup and styling
# -----------------------------

st.set_page_config(page_title="Tree Estimate Route Planner", page_icon="🌲", layout="wide")

st.markdown(
    """
<style>
:root {
    --forest: #064d25;
    --forest-2: #0f6b2f;
    --leaf: #2f9e44;
    --line: #cfe6ca;
    --text: #0f2416;
}
html, body, [class*="css"] { color: var(--text); }
.stApp { background: linear-gradient(135deg, #f7fbf4 0%, #ffffff 52%, #edf7ea 100%); }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #043d1d 0%, #075328 55%, #053a1c 100%); }
section[data-testid="stSidebar"] * { color: #ffffff !important; }
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stDateInput input { background: rgba(255,255,255,.12) !important; color: #ffffff !important; border: 1px solid rgba(255,255,255,.25) !important; }
.main .block-container { padding-top: 1.4rem; max-width: 1500px; }
.hero-card { background: linear-gradient(135deg, #ffffff 0%, #f0faee 100%); border: 1px solid var(--line); border-radius: 18px; padding: 22px 24px; margin-bottom: 16px; box-shadow: 0 12px 30px rgba(6,77,37,.08); }
.hero-title { font-size: 2.05rem; font-weight: 900; color: var(--forest); letter-spacing: .02em; margin-bottom: 2px; }
.hero-subtitle { font-size: 1rem; color: #395545; }
.notice-card { background: #eef9ed; border: 1px solid #b9dfb5; border-left: 6px solid var(--leaf); border-radius: 14px; padding: 14px 16px; margin: 8px 0 20px; color: #123b20; }
.section-card { background: rgba(255,255,255,.94); border: 1px solid #dcebd8; border-radius: 16px; padding: 18px; margin: 12px 0 18px; box-shadow: 0 10px 24px rgba(6,77,37,.06); }
.step-title { color: var(--forest); font-weight: 850; font-size: 1.2rem; margin-bottom: .5rem; }
.step-pill { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 50%; background: var(--forest-2); color: white; font-weight: 800; margin-right: 8px; }
.estimator-card { border: 1px solid #b9dfb5; background: linear-gradient(180deg, #ffffff 0%, #f1faef 100%); border-radius: 16px; padding: 14px; min-height: 120px; box-shadow: 0 6px 18px rgba(6,77,37,.08); }
.estimator-name { color: var(--forest); font-size: 1.1rem; font-weight: 850; }
.home-line { color: #3c5b43; font-size: .9rem; margin-bottom: .4rem; }
.block-chip { display: inline-block; padding: 5px 9px; margin: 3px 4px 3px 0; border-radius: 8px; background: #dff3d9; border: 1px solid #bfe3b8; color: #0b4b22; font-weight: 700; font-size: .8rem; }
.route-card { background: #ffffff; border: 1px solid #cfe6ca; border-top: 5px solid var(--forest-2); border-radius: 16px; padding: 16px; box-shadow: 0 8px 22px rgba(6,77,37,.06); margin-bottom: 16px; }
.metric-pill { display: inline-block; background: #edf8ea; border: 1px solid #cfe6ca; border-radius: 999px; padding: 7px 11px; margin: 4px 4px 8px 0; color: #0b4b22; font-weight: 750; font-size: .86rem; }
.footer-tree { margin-top: 30px; color: #2a6b38; font-weight: 700; text-align: center; opacity: .8; }
.stButton > button, .stDownloadButton > button { background: linear-gradient(180deg, #0f7a36 0%, #075328 100%) !important; color: white !important; border: 1px solid #064d25 !important; border-radius: 10px !important; font-weight: 800 !important; box-shadow: 0 6px 14px rgba(6,77,37,.18); }
.stButton > button:hover, .stDownloadButton > button:hover { background: linear-gradient(180deg, #148c3f 0%, #08612f 100%) !important; }
div[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; border: 1px solid #dcebd8; }
</style>
""",
    unsafe_allow_html=True,
)


# -----------------------------
# Helpers
# -----------------------------

def sidebar_brand() -> None:
    st.sidebar.markdown(
        """
        <div style='text-align:center; padding: 10px 0 18px;'>
            <div style='font-size:3rem; line-height:1;'>🌳</div>
            <div style='font-size:1.35rem; font-weight:900; letter-spacing:.04em;'>TREE ROUTE</div>
            <div style='font-size:.88rem; opacity:.82;'>Estimate Planner</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_date(date_value: dt.date) -> str:
    return date_value.strftime("%m/%d/%Y")


def format_date_for_file(date_value: dt.date) -> str:
    return date_value.strftime("%m-%d-%Y")


def date_input_mmddyyyy(label: str, value: dt.date) -> dt.date:
    try:
        return st.date_input(label, value=value, format="MM/DD/YYYY")
    except TypeError:
        selected = st.date_input(label, value=value)
        st.caption(f"Selected date: {format_date(selected)}")
        return selected


def block_time_text(block: dict) -> str:
    start = block["start"].strftime("%I:%M %p").lstrip("0")
    end = block["end"].strftime("%I:%M %p").lstrip("0")
    return f"{start} - {end}"


def chips_html(blocks: List[str]) -> str:
    return "".join([f"<span class='block-chip'>{block}</span>" for block in blocks])


def estimator_allowed_blocks(estimator_name: str) -> List[str]:
    return DEFAULT_ESTIMATOR_BLOCKS.get(estimator_name, BLOCK_LABELS)


def is_blank(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""


def block_display(blocks: List[str]) -> str:
    if not blocks or set(blocks) == set(BLOCK_LABELS):
        return "Any"
    return ", ".join(blocks)


def clean_priority(value) -> str:
    if is_blank(value):
        return "Normal"
    text = str(value).strip().title()
    return text if text in PRIORITY_SCORE else "Normal"


def normalize_estimator(value) -> str:
    if is_blank(value):
        return "Any"
    text = str(value).strip()
    return "Any" if text.lower() in ["any", "none", "no preference", "all"] else text


def simplify_block_text(value: str) -> str:
    return str(value).lower().strip().replace(" ", "").replace("am", "").replace("pm", "").replace("–", "-").replace("—", "-")


def parse_blocks(value) -> List[str]:
    if isinstance(value, list):
        chosen = [item for item in value if item in BLOCK_LABELS]
        return chosen if chosen else BLOCK_LABELS.copy()

    if is_blank(value):
        return BLOCK_LABELS.copy()

    raw = str(value).strip()
    if raw.lower() in ["any", "all", "open", ""]:
        return BLOCK_LABELS.copy()

    pieces = [piece.strip() for piece in re.split(r"[,;|]", raw) if piece.strip()]
    chosen: List[str] = []
    alias_map = {}
    for label in BLOCK_LABELS:
        alias_map[simplify_block_text(label)] = label
        alias_map[simplify_block_text(label.replace(":00", ""))] = label

    for piece in pieces:
        simplified = simplify_block_text(piece)
        if simplified in alias_map:
            chosen.append(alias_map[simplified])
            continue
        for label in BLOCK_LABELS:
            if simplified == simplify_block_text(label.split("-")[0]):
                chosen.append(label)
                break

    deduped = []
    for label in chosen:
        if label not in deduped:
            deduped.append(label)
    return deduped if deduped else BLOCK_LABELS.copy()


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
        df["Required Estimator"] = df["Required Estimator"].apply(normalize_estimator)
        df["Notes"] = df["Notes"].apply(lambda x: "" if is_blank(x) else str(x).strip())
    return df.reset_index(drop=True)


def google_address_predictions(client, query: str, country_code: str = "us") -> Tuple[List[str], Optional[str]]:
    if not client:
        return [], "Add your Google Maps API key in the sidebar before searching addresses."
    if len(query.strip()) < 3:
        return [], "Type at least 3 characters."
    try:
        results = client.places_autocomplete(input_text=query.strip(), types="address", components={"country": country_code})
        return [r.get("description", "") for r in results if r.get("description")], None
    except Exception as exc:
        return [], f"Google address lookup failed: {exc}"


def add_lead(name: str, address: str, available_blocks: List[str], priority: str, required_estimator: str, notes: str) -> None:
    new_row = pd.DataFrame(
        [{
            "Lead Name": name.strip() or "Lead",
            "Address": address.strip(),
            "Available Blocks": block_display(available_blocks),
            "Priority": clean_priority(priority),
            "Required Estimator": normalize_estimator(required_estimator),
            "Notes": notes.strip(),
        }],
        columns=LEAD_COLUMNS,
    )
    st.session_state.leads_df = clean_df(pd.concat([st.session_state.leads_df, new_row], ignore_index=True))


def to_leads(df: pd.DataFrame) -> List[Lead]:
    leads = []
    for _, row in clean_df(df).iterrows():
        if is_blank(row["Address"]):
            continue
        leads.append(
            Lead(
                name=str(row["Lead Name"]).strip() or "Lead",
                address=str(row["Address"]).strip(),
                available_blocks=parse_blocks(row["Available Blocks"]),
                priority=clean_priority(row["Priority"]),
                required_estimator=normalize_estimator(row["Required Estimator"]),
                notes=str(row.get("Notes", "")).strip(),
            )
        )
    return leads


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


def estimator_can_take_lead(estimator: Estimator, lead: Lead, block_label: str) -> bool:
    required = normalize_estimator(lead.required_estimator)
    if block_label not in estimator.available_blocks:
        return False
    if block_label not in lead.available_blocks:
        return False
    if required != "Any" and required.lower() != estimator.name.lower():
        return False
    return True


def choose_lead_for_slot(estimator: Estimator, block_index: int, block_label: str, current_location: str, remaining: List[Lead], cache, client):
    candidates = []
    home_pull = HOME_PULL_BY_BLOCK_INDEX[min(block_index, len(HOME_PULL_BY_BLOCK_INDEX) - 1)]

    for lead in remaining:
        if not estimator_can_take_lead(estimator, lead, block_label):
            continue

        drive_from_previous = drive_minutes(cache, client, current_location, lead.address)
        drive_to_home = drive_minutes(cache, client, lead.address, estimator.home_address) if estimator.home_address else 0
        priority_score = PRIORITY_SCORE.get(lead.priority, 3)
        availability_tightness = len(lead.available_blocks)
        required_bonus = -150 if normalize_estimator(lead.required_estimator) != "Any" else 0

        score = (
            (-priority_score * 1000)
            + (availability_tightness * 40)
            + (drive_from_previous * 5)
            + (drive_to_home * home_pull)
            + required_bonus
        )
        candidates.append((score, lead, drive_from_previous, drive_to_home))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    _, lead, drive_from_previous, drive_to_home = candidates[0]
    return lead, drive_from_previous, drive_to_home


def build_routes(estimators: List[Estimator], leads: List[Lead], client):
    remaining = leads.copy()
    routes = {estimator.name: [] for estimator in estimators}
    route_summaries = {}
    current_locations = {estimator.name: estimator.start_address for estimator in estimators}
    cache = {}

    for block_index, block in enumerate(ESTIMATE_BLOCKS):
        block_label = block["label"]
        estimate_time = block_time_text(block)

        for estimator in estimators:
            choice = choose_lead_for_slot(estimator, block_index, block_label, current_locations[estimator.name], remaining, cache, client)
            if not choice:
                continue

            lead, drive_from_previous, drive_to_home = choice
            routes[estimator.name].append({
                "Estimate Block": block_label,
                "Estimate Time": estimate_time,
                "Lead": lead.name,
                "Address": lead.address,
                "Priority": lead.priority,
                "Required Estimator": lead.required_estimator,
                "Drive From Previous (min)": drive_from_previous,
                "Drive From Stop To Home (min)": drive_to_home,
                "Notes": lead.notes,
            })
            current_locations[estimator.name] = lead.address
            remaining.remove(lead)

    for estimator in estimators:
        rows = routes.get(estimator.name, [])
        if rows:
            last_stop = rows[-1]["Address"]
            final_drive_home = drive_minutes(cache, client, last_stop, estimator.home_address) if estimator.home_address else 0
        else:
            final_drive_home = 0

        route_summaries[estimator.name] = {
            "home_address": estimator.home_address,
            "final_drive_home": final_drive_home,
        }

    return routes, remaining, route_summaries


def maps_link(home_address: str, rows: List[dict]) -> str:
    if not rows:
        return ""
    stop_addresses = [row["Address"] for row in rows]
    origin = urllib.parse.quote_plus(home_address)
    destination = urllib.parse.quote_plus(home_address)
    waypoints = "|".join(urllib.parse.quote_plus(address) for address in stop_addresses)
    url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode=driving"
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url


def validate_leads(df: pd.DataFrame, estimator_names: List[str]) -> List[str]:
    errors = []
    estimator_lookup = [name.lower() for name in estimator_names]
    for i, row in df.iterrows():
        if is_blank(row["Address"]):
            errors.append(f"Row {i + 1} is missing an address.")
        required = normalize_estimator(row["Required Estimator"])
        if required != "Any" and required.lower() not in estimator_lookup:
            errors.append(f"Row {i + 1} is assigned to {required}, but that estimator is not marked as working today.")
        if not parse_blocks(row["Available Blocks"]):
            errors.append(f"Row {i + 1} needs at least one available estimate block.")
    return errors


# -----------------------------
# App UI
# -----------------------------

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-title">🌲 TREE ESTIMATE ROUTE PLANNER</div>
        <div class="hero-subtitle">Plan efficient daily routes for tree estimate appointments.</div>
    </div>
    <div class="notice-card">
        🍃 <strong>Each estimate takes the full assigned time block.</strong>
        Addresses must come from Google autocomplete. Estimators start and end from home.
    </div>
    """,
    unsafe_allow_html=True,
)

if "leads_df" not in st.session_state:
    st.session_state.leads_df = blank_df()
if "address_suggestions" not in st.session_state:
    st.session_state.address_suggestions = []

sidebar_brand()
with st.sidebar:
    st.header("Schedule Settings")
    service_date = date_input_mmddyyyy("Service date", dt.date.today())
    st.caption(f"Using date: {format_date(service_date)}")

    st.markdown("---")
    st.markdown("**Estimate blocks**")
    for block in ESTIMATE_BLOCKS:
        st.write(f"🌿 {block['label']}")

    st.markdown("---")
    st.header("Google Maps")
    google_api_key = st.text_input("Google Maps API key", type="password")
    country_code = st.text_input("Autocomplete country code", value="us", max_chars=2).lower()
    st.caption("Places API powers address lookup. Distance Matrix powers real drive times.")

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

st.markdown("<div class='section-card'><div class='step-title'><span class='step-pill'>1</span>Who Is Working Today?</div>", unsafe_allow_html=True)
working_estimators = st.multiselect("Select estimators working this date", DEFAULT_ESTIMATORS, default=DEFAULT_ESTIMATORS)

if not working_estimators:
    st.warning("Select at least one estimator before building routes.")

estimators = []
if working_estimators:
    estimator_cols = st.columns(len(working_estimators))
    for estimator_name in working_estimators:
        with estimator_cols[working_estimators.index(estimator_name)]:
            allowed_blocks = estimator_allowed_blocks(estimator_name)
            home_address = st.text_input(
                f"{estimator_name} start/end home location",
                value=DEFAULT_ESTIMATOR_HOMES.get(estimator_name, ""),
                key=f"home_address_{estimator_name}",
            )
            available_blocks = st.multiselect(
                f"{estimator_name} available blocks",
                allowed_blocks,
                default=allowed_blocks,
                key=f"estimator_blocks_{estimator_name}",
            )
            if estimator_name == "Lindsay":
                st.caption("Lindsay does not use the 8:15-9:30 or 4:00-5:30 blocks.")
            st.markdown(
                f"""
                <div class="estimator-card">
                    <div class="estimator-name">🏡 {estimator_name}</div>
                    <div class="home-line">{home_address}</div>
                    <div>{chips_html(available_blocks or allowed_blocks)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            estimators.append(
                Estimator(
                    name=estimator_name,
                    home_address=home_address.strip() or DEFAULT_ESTIMATOR_HOMES.get(estimator_name, ""),
                    available_blocks=available_blocks or allowed_blocks.copy(),
                )
            )
st.markdown("</div>", unsafe_allow_html=True)

estimator_names = [estimator.name for estimator in estimators]
estimator_options = ["Any"] + estimator_names

st.markdown("<div class='section-card'><div class='step-title'><span class='step-pill'>2</span>Add Lead with Google Autocomplete</div>", unsafe_allow_html=True)
if not gmaps_client:
    st.warning("Paste your Google Maps API key in the sidebar to search and add addresses.")

lookup_col, button_col = st.columns([4, 1])
with lookup_col:
    address_query = st.text_input("Start typing customer address", placeholder="Example: 123 Main St Chattanooga")
with button_col:
    st.write("")
    st.write("")
    if st.button("Search Google", use_container_width=True):
        suggestions, error = google_address_predictions(gmaps_client, address_query, country_code)
        st.session_state.address_suggestions = suggestions
        if error:
            st.warning(error)
        elif not suggestions:
            st.warning("No matching Google addresses found. Try adding city and state.")

selected_address = ""
if st.session_state.address_suggestions:
    selected_address = st.selectbox("Choose the correct Google address", st.session_state.address_suggestions)
else:
    st.info("Search Google and select a suggested address before adding the lead.")

lead_col_1, lead_col_2, lead_col_3 = st.columns([2, 2, 1])
with lead_col_1:
    new_name = st.text_input("Customer name", placeholder="John Smith")
    new_notes = st.text_input("Notes", placeholder="Gate code, call before arrival, tree concern, etc.")
with lead_col_2:
    new_blocks = st.multiselect(
        "Customer available estimate blocks",
        BLOCK_LABELS,
        default=BLOCK_LABELS,
        help="Choose every full block the customer could take.",
    )
with lead_col_3:
    new_priority = st.selectbox("Priority", ["Emergency", "High", "Normal", "Low"], index=2)
    new_estimator = st.selectbox("Required estimator", estimator_options, index=0)

if st.button("➕ Add Google Address Lead", type="primary"):
    if is_blank(selected_address):
        st.error("Search Google and select an address before adding the lead.")
    elif not new_blocks:
        st.error("Choose at least one customer availability block.")
    elif not estimator_names:
        st.error("Select at least one working estimator before adding leads.")
    else:
        add_lead(new_name, selected_address, new_blocks, new_priority, new_estimator, new_notes)
        st.session_state.address_suggestions = []
        st.success("Lead added from Google autocomplete.")
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<div class='section-card'><div class='step-title'><span class='step-pill'>3</span>Review Leads / Estimates</div>", unsafe_allow_html=True)
current_df = clean_df(st.session_state.leads_df)
column_config = {
    "Available Blocks": st.column_config.TextColumn("Available Blocks", help="Use Any, or comma-separated blocks like 8:15-9:30, 2:30-4:00", required=True),
    "Priority": st.column_config.SelectboxColumn("Priority", options=["Emergency", "High", "Normal", "Low"], required=True),
    "Required Estimator": st.column_config.SelectboxColumn("Required Estimator", options=estimator_options, required=True),
}
edited_df = st.data_editor(current_df, num_rows="dynamic", use_container_width=True, column_config=column_config, key="lead_editor")
st.session_state.leads_df = clean_df(edited_df)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<div class='section-card'><div class='step-title'><span class='step-pill'>4</span>Route Plan</div>", unsafe_allow_html=True)
errors = []
if not estimator_names:
    errors.append("Select at least one working estimator.")
errors.extend(validate_leads(st.session_state.leads_df, estimator_names))
for error in errors:
    st.error(error)

if st.button("🔄 Build / Optimize Routes", type="primary", use_container_width=True):
    if errors:
        st.stop()
    leads = to_leads(st.session_state.leads_df)
    if not leads:
        st.error("Add at least one lead first.")
        st.stop()

    routes, unassigned, route_summaries = build_routes(estimators, leads, gmaps_client)
    scheduled_count = sum(len(rows) for rows in routes.values())
    st.success(f"Scheduled {scheduled_count} of {len(leads)} lead(s) for {format_date(service_date)}.")

    export_rows = []
    route_cols = st.columns(max(1, len(estimators)))

    for idx, estimator in enumerate(estimators):
        rows = routes.get(estimator.name, [])
        summary = route_summaries.get(estimator.name, {})
        with route_cols[idx]:
            st.markdown("<div class='route-card'>", unsafe_allow_html=True)
            st.markdown(f"### 🌲 {estimator.name}")
            st.caption(f"Start/End home: {summary.get('home_address', estimator.home_address)}")

            if not rows:
                st.info("No leads scheduled for this estimator.")
            else:
                final_drive = summary.get("final_drive_home", 0)
                st.markdown(f"<span class='metric-pill'>Stops: {len(rows)}</span><span class='metric-pill'>Drive home: {final_drive} min</span>", unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

                link = maps_link(estimator.home_address, rows)
                if link:
                    st.markdown(f"[Open {estimator.name}'s full route from home back to home]({link})")

                copyable = "\n".join([f"{row['Estimate Block']} - {row['Lead']} - {row['Address']}" for row in rows])
                copyable = f"Start at home: {estimator.home_address}\n" + copyable + f"\nEnd at home: {estimator.home_address}"
                st.text_area(f"Copyable schedule for {estimator.name}", value=copyable, height=150, key=f"schedule_{estimator.name}")

                export_rows.extend([
                    {
                        "Date": format_date(service_date),
                        "Estimator": estimator.name,
                        "Start Location": estimator.home_address,
                        "End Location": estimator.home_address,
                        "Final Drive Home (min)": final_drive,
                        **row,
                    }
                    for row in rows
                ])
            st.markdown("</div>", unsafe_allow_html=True)

    if unassigned:
        st.markdown("### Unscheduled Leads")
        st.dataframe(
            pd.DataFrame([
                {
                    "Lead": lead.name,
                    "Address": lead.address,
                    "Available Blocks": block_display(lead.available_blocks),
                    "Priority": lead.priority,
                    "Required Estimator": lead.required_estimator,
                    "Reason": "Could not fit within estimator availability, customer availability, required estimator rule, or route/home preference.",
                }
                for lead in unassigned
            ]),
            use_container_width=True,
            hide_index=True,
        )

    if export_rows:
        export_df = pd.DataFrame(export_rows)
        st.download_button(
            "⬇ Export Routes",
            data=export_df.to_csv(index=False).encode("utf-8"),
            file_name=f"estimator_routes_{format_date_for_file(service_date)}.csv",
            mime="text/csv",
        )

st.markdown("</div>", unsafe_allow_html=True)
st.markdown("<div class='footer-tree'>🍃 Care for trees. Care for tomorrow. 🌳</div>", unsafe_allow_html=True)
