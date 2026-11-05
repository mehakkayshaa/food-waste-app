import base64
import json
import uuid
from datetime import date, timedelta

import pandas as pd
import streamlit as st

try:
    import anthropic
except ImportError:  # app still works in manual mode
    anthropic = None

MODEL = "claude-sonnet-5-5"

st.set_page_config(page_title="EcoBite - AI Food Saver", page_icon="🌱", layout="centered")

# ---------------------------------------------------------------------------
# REFERENCE DATA
# ---------------------------------------------------------------------------
# Shelf life in days (pantry, fridge, freezer) when bought fresh, and
# approximate farm-to-retail emissions in kg CO2e per kg (or litre) of food,
# based on Poore & Nemecek (2018). Values are estimates, not exact figures.
FOOD_DB = {
    "banana":   {"pantry": 5,  "fridge": 8,   "freezer": 90,  "co2": 0.86,  "kg": 0.5},
    "tomato":   {"pantry": 5,  "fridge": 10,  "freezer": 180, "co2": 2.09,  "kg": 0.5},
    "apple":    {"pantry": 14, "fridge": 35,  "freezer": 240, "co2": 0.43,  "kg": 0.5},
    "lettuce":  {"pantry": 1,  "fridge": 7,   "freezer": 0,   "co2": 0.5,   "kg": 0.3},
    "spinach":  {"pantry": 1,  "fridge": 5,   "freezer": 240, "co2": 0.5,   "kg": 0.2},
    "potato":   {"pantry": 35, "fridge": 60,  "freezer": 240, "co2": 0.46,  "kg": 1.0},
    "carrot":   {"pantry": 5,  "fridge": 28,  "freezer": 300, "co2": 0.4,   "kg": 0.5},
    "milk":     {"pantry": 0,  "fridge": 6,   "freezer": 90,  "co2": 3.15,  "kg": 1.0},
    "yogurt":   {"pantry": 0,  "fridge": 14,  "freezer": 60,  "co2": 3.15,  "kg": 0.5},
    "cheese":   {"pantry": 1,  "fridge": 28,  "freezer": 180, "co2": 23.88, "kg": 0.25},
    "egg":      {"pantry": 7,  "fridge": 28,  "freezer": 0,   "co2": 4.67,  "kg": 0.5},
    "bread":    {"pantry": 4,  "fridge": 8,   "freezer": 90,  "co2": 1.57,  "kg": 0.5},
    "chicken":  {"pantry": 0,  "fridge": 2,   "freezer": 270, "co2": 9.87,  "kg": 1.0},
    "beef":     {"pantry": 0,  "fridge": 3,   "freezer": 180, "co2": 99.48, "kg": 1.0},
    "fish":     {"pantry": 0,  "fridge": 2,   "freezer": 150, "co2": 13.6,  "kg": 0.5},
    "rice":     {"pantry": 365, "fridge": 365, "freezer": 365, "co2": 4.45, "kg": 1.0},
    "onion":    {"pantry": 30, "fridge": 60,  "freezer": 240, "co2": 0.5,   "kg": 0.5},
    "cucumber": {"pantry": 3,  "fridge": 10,  "freezer": 0,   "co2": 0.8,   "kg": 0.4},
    "pepper":   {"pantry": 4,  "fridge": 12,  "freezer": 240, "co2": 1.0,   "kg": 0.3},
    "orange":   {"pantry": 10, "fridge": 28,  "freezer": 90,  "co2": 0.39,  "kg": 0.5},
    "strawberr": {"pantry": 1, "fridge": 5,   "freezer": 240, "co2": 1.5,   "kg": 0.3},
}
DEFAULT_FOOD = {"pantry": 4, "fridge": 7, "freezer": 90, "co2": 2.5, "kg": 0.5}

# Fraction of remaining shelf life left, based on visible condition.
CONDITIONS = {
    "Fresh": 1.0,
    "Ripe / slightly soft": 0.6,
    "Starting to spoil": 0.3,
    "Past its best": 0.1,
}
STORAGE = ["Fridge", "Pantry", "Freezer"]
KG_CO2_PER_MILE = 0.404  # US EPA average passenger car


def lookup(name: str) -> dict:
    n = name.lower()
    for key, val in FOOD_DB.items():
        if key in n:
            return val
    return DEFAULT_FOOD


def predict_days(name: str, storage: str, purchase: date, condition: str) -> int:
    """Estimated days from today until the item should be used by."""
    base = lookup(name)[storage.lower()]
    age = (date.today() - purchase).days
    remaining = max(0, base - age) * CONDITIONS[condition]
    return int(round(remaining))


# ---------------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------------
if "inventory" not in st.session_state:
    st.session_state["inventory"] = []  # list of dicts
if "scan_df" not in st.session_state:
    st.session_state["scan_df"] = None
if "recipes" not in st.session_state:
    st.session_state["recipes"] = None


def add_item(name, qty_kg, storage, purchase, condition):
    info = lookup(name)
    days = predict_days(name, storage, purchase, condition)
    st.session_state["inventory"].append(
        {
            "id": uuid.uuid4().hex,
            "item": name.strip().title(),
            "qty_kg": float(qty_kg),
            "storage": storage,
            "purchase": purchase,
            "condition": condition,
            "use_by": date.today() + timedelta(days=days),
            "co2_per_kg": info["co2"],
            "status": "active",
        }
    )


def active_items():
    items = [i for i in st.session_state["inventory"] if i["status"] == "active"]
    return sorted(items, key=lambda i: i["use_by"])


def days_left(item) -> int:
    return (item["use_by"] - date.today()).days


# ---------------------------------------------------------------------------
# CLAUDE HELPERS
# ---------------------------------------------------------------------------
def get_client():
    key = st.session_state.get("api_key", "")
    if not key:
        try:
            key = st.secrets.get("ANTHROPIC_API_KEY", "")
        except Exception:
            key = ""
    if anthropic is None or not key:
        return None
    return anthropic.Anthropic(api_key=key)


def extract_json(text: str):
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("No JSON list found in response")
    return json.loads(text[start : end + 1])


def scan_images(client, files):
    blocks = []
    for f in files:
        data = base64.standard_b64encode(f.getvalue()).decode()
        media = f.type if f.type in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg"
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": data}})
    blocks.append(
        {
            "type": "text",
            "text": (
                "Identify every distinct grocery/food item visible in these images. "
                "Return ONLY a JSON list. Each element: "
                '{"item": "singular common name, e.g. banana", '
                '"qty_kg": estimated total weight in kg (or litres for liquids), '
                '"condition": one of ["Fresh", "Ripe / slightly soft", "Starting to spoil", "Past its best"]}. '
                "Judge condition from visible signs such as browning, bruising, wilting or mould. "
                "Do not include non-food objects."
            ),
        }
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=1000, messages=[{"role": "user", "content": blocks}]
    )
    return extract_json(resp.content[0].text)


FALLBACK_RECIPES = {
    "banana": "Banana oat pancakes or freezer banana bread",
    "tomato": "Quick roasted tomato sauce for pasta, or shakshuka",
    "bread": "French toast, croutons or bread pudding",
    "milk": "Creamy soup, pancakes or rice pudding",
    "yogurt": "Yogurt marinade for chicken, or a smoothie",
    "egg": "Veggie frittata",
    "lettuce": "Wilted-greens soup or stir-fry",
    "spinach": "Spinach omelette or saag",
    "potato": "Potato and onion hash",
    "carrot": "Carrot soup or roasted carrots",
    "chicken": "Sheet-pan chicken with whatever veg is going soft",
    "beef": "Slow-cooked beef stew",
    "apple": "Stewed apples or apple crumble",
    "cheese": "Cheese toastie or baked pasta",
}


def fallback_recipes(items):
    out = []
    for it in items:
        for key, idea in FALLBACK_RECIPES.items():
            if key in it["item"].lower():
                out.append(f"**{it['item']}**: {idea}")
                break
        else:
            out.append(f"**{it['item']}**: Add to a soup, stir-fry or frittata")
    return "\n\n".join(out) + "\n\n*Add an API key in the sidebar for full recipes combining your ingredients.*"


def generate_recipes(client, items, extras):
    lines = "\n".join(f"- {i['item']} ({days_left(i)} days left)" for i in items)
    prompt = (
        "Suggest 3 simple recipes that use up these ingredients that are close to spoiling, "
        "most urgent first. Prefer recipes that combine several of them. "
        "For each give: a title, which at-risk items it uses, a short ingredient list, "
        "and 3-5 brief steps. Assume basic pantry staples are available.\n\n"
        f"At-risk ingredients:\n{lines}\n"
        + (f"\nDietary notes / other ingredients on hand: {extras}\n" if extras else "")
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=1500, messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Settings")
    st.text_input(
        "Anthropic API key",
        type="password",
        key="api_key",
        help="Enables AI scanning and recipes. Without it you can add items manually.",
    )
    client = get_client()
    st.caption("🟢 AI enabled" if client else "⚪ Manual mode (no API key)")
    if st.button("Reset all data"):
        st.session_state["inventory"] = []
        st.session_state["scan_df"] = None
        st.session_state["recipes"] = None
        st.rerun()

st.title("🌱 EcoBite: AI Food Waste Manager")
st.markdown("Scan groceries, predict spoilage, rescue food with recipes, and track the carbon you save.")

tab1, tab2, tab3, tab4 = st.tabs(
    ["📸 Scanner", "⚠️ Smart Alerts", "🍲 Recipe Rescue", "🌍 Carbon Tracker"]
)

# ---------------------------------------------------------------------------
# TAB 1: SCANNER
# ---------------------------------------------------------------------------
with tab1:
    st.header("📸 AI Grocery Scanner")

    c1, c2 = st.columns(2)
    purchase_date = c1.date_input("Purchase date", value=date.today(), max_value=date.today())
    storage = c2.selectbox("Storage", STORAGE)

    uploads = st.file_uploader(
        "Upload photos of your groceries", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True
    )
    use_cam = st.toggle("Use camera instead")
    cam = st.camera_input("Take a photo") if use_cam else None

    files = list(uploads or []) + ([cam] if cam else [])

    if files:
        st.image([f.getvalue() for f in files], width=160)
        if st.button("🔍 Identify items", type="primary"):
            if not client:
                st.warning("Add an Anthropic API key in the sidebar to scan, or add items manually below.")
            else:
                with st.spinner("Analyzing image..."):
                    try:
                        found = scan_images(client, files)
                        df = pd.DataFrame(found).rename(
                            columns={"item": "Item", "qty_kg": "Qty (kg/L)", "condition": "Condition"}
                        )
                        df["Condition"] = df["Condition"].where(df["Condition"].isin(CONDITIONS), "Fresh")
                        st.session_state["scan_df"] = df
                    except Exception as e:
                        st.error(f"Scan failed: {e}")

    if st.session_state["scan_df"] is not None and not st.session_state["scan_df"].empty:
        st.subheader("Review detected items")
        st.caption("Fix anything the AI got wrong before adding.")
        edited = st.data_editor(
            st.session_state["scan_df"],
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Condition": st.column_config.SelectboxColumn(options=list(CONDITIONS)),
                "Qty (kg/L)": st.column_config.NumberColumn(min_value=0.01, step=0.05),
            },
            key="scan_editor",
        )
        if st.button("➕ Add to inventory"):
            for _, row in edited.dropna(subset=["Item"]).iterrows():
                add_item(
                    str(row["Item"]),
                    row.get("Qty (kg/L)") or lookup(str(row["Item"]))["kg"],
                    storage,
                    purchase_date,
                    row.get("Condition") or "Fresh",
                )
            st.session_state["scan_df"] = None
            st.success("Added! Check Smart Alerts for use-by dates.")
            st.rerun()

    with st.expander("✍️ Add an item manually"):
        with st.form("manual", clear_on_submit=True):
            m_name = st.text_input("Item (e.g. banana, milk, chicken)")
            m_qty = st.number_input("Quantity (kg or litres)", min_value=0.05, value=0.5, step=0.05)
            m_cond = st.selectbox("Condition", list(CONDITIONS))
            if st.form_submit_button("Add") and m_name.strip():
                add_item(m_name, m_qty, storage, purchase_date, m_cond)
                st.success(f"Added {m_name.title()}")

# ---------------------------------------------------------------------------
# TAB 2: SMART ALERTS
# ---------------------------------------------------------------------------
with tab2:
    st.header("⚠️ Smart Alerts")
    items = active_items()
    if not items:
        st.info("Your inventory is empty. Use the Scanner to add groceries.")
    else:
        urgent = [i for i in items if days_left(i) <= 2]
        if urgent:
            st.error(f"{len(urgent)} item(s) need to be used within 2 days: " + ", ".join(i["item"] for i in urgent))

        for it in items:
            d = days_left(it)
            if d <= 0:
                badge, label = "🔴", "Use today / check before eating"
            elif d <= 2:
                badge, label = "🟠", f"{d} day(s) left"
            elif d <= 5:
                badge, label = "🟡", f"{d} days left"
            else:
                badge, label = "🟢", f"{d} days left"

            col_a, col_b, col_c = st.columns([4, 1.4, 1.4])
            col_a.markdown(
                f"{badge} **{it['item']}** · {it['qty_kg']:.2f} kg  \n"
                f"{label} · use by {it['use_by']:%d %b} · {it['storage']} · {it['condition']}"
            )
            if col_b.button("✅ Used", key=f"used_{it['id']}"):
                it["status"] = "saved"
                st.balloons()
                st.rerun()
            if col_c.button("🗑️ Wasted", key=f"waste_{it['id']}"):
                it["status"] = "wasted"
                st.rerun()
        st.caption(
            "Estimates only. Always check smell, texture and appearance, and follow food-safety guidance, "
            "especially for meat, fish and dairy."
        )

# ---------------------------------------------------------------------------
# TAB 3: RECIPE RESCUE
# ---------------------------------------------------------------------------
with tab3:
    st.header("🍲 AI Recipe Rescue")
    items = active_items()
    at_risk = [i for i in items if days_left(i) <= 5]
    if not at_risk:
        st.info("Nothing is close to spoiling right now. Items within 5 days of their use-by date appear here.")
    else:
        names = [f"{i['item']} ({days_left(i)}d)" for i in at_risk]
        chosen = st.multiselect("Ingredients to rescue", names, default=names)
        extras = st.text_input("Dietary needs or other ingredients you have (optional)")
        if st.button("👩‍🍳 Suggest recipes", type="primary"):
            selected = [i for i, n in zip(at_risk, names) if n in chosen]
            if not selected:
                st.warning("Select at least one ingredient.")
            else:
                with st.spinner("Cooking up ideas..."):
                    try:
                        st.session_state["recipes"] = (
                            generate_recipes(client, selected, extras) if client else fallback_recipes(selected)
                        )
                    except Exception as e:
                        st.error(f"Recipe generation failed: {e}")
        if st.session_state["recipes"]:
            st.markdown(st.session_state["recipes"])
            st.caption("Cooked it? Mark the ingredients as ✅ Used in Smart Alerts to log the carbon saved.")

# ---------------------------------------------------------------------------
# TAB 4: CARBON TRACKER
# ---------------------------------------------------------------------------
with tab4:
    st.header("🌍 Carbon Impact Tracker")
    saved = [i for i in st.session_state["inventory"] if i["status"] == "saved"]
    wasted = [i for i in st.session_state["inventory"] if i["status"] == "wasted"]
    co2_saved = sum(i["qty_kg"] * i["co2_per_kg"] for i in saved)
    co2_wasted = sum(i["qty_kg"] * i["co2_per_kg"] for i in wasted)

    m1, m2 = st.columns(2)
    m1.metric("CO₂e saved", f"{co2_saved:.2f} kg", f"≈ {co2_saved / KG_CO2_PER_MILE:.0f} car miles avoided")
    m2.metric("CO₂e wasted", f"{co2_wasted:.2f} kg", delta_color="inverse")

    if saved or wasted:
        rows = [
            {
                "Item": i["item"],
                "Outcome": "Saved" if i["status"] == "saved" else "Wasted",
                "Qty (kg)": i["qty_kg"],
                "kg CO₂e/kg": i["co2_per_kg"],
                "kg CO₂e": round(i["qty_kg"] * i["co2_per_kg"], 2),
            }
            for i in saved + wasted
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Mark items as ✅ Used or 🗑️ Wasted in Smart Alerts to see your impact.")

    st.markdown(
        "**Method:** quantity × an emissions factor per kg of food (farm to retail), "
        "based on Poore & Nemecek (2018) global averages. Factors are approximate and vary by origin "
        "and production method. Car miles use ~0.404 kg CO₂ per mile (US EPA average)."
    )

