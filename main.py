import time

import requests

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

MACROS = ("Protein", "Carbs", "Fat")


def macro_inputs(prefix="manual"):
    amounts = {}
    with st.expander("Macros for this portion (optional)"):
        for name in MACROS:
            amounts[name] = st.number_input(f"{name} (g)", min_value=0.0, value=None, step=0.1, key=f"{prefix}_{name}")
    return amounts


headers = {
    "User-Agent": "VitalFlow/1.0 (jartiste23@gmail.com)"
}

def search_foods(food_name):
    response = requests.get(
        "https://search.openfoodfacts.org/search",
        headers=headers,
        params={
            "q": food_name,
            "page_size": 5,
            "fields": "code,product_name,brands,nutriments,serving_size,serving_quantity,serving_quantity_unit",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["hits"]

st.set_page_config(page_title="VitalFlow", layout="wide", initial_sidebar_state="expanded")
st.html("""
    <style>
    @media (min-width: 769px) {
        section[data-testid="stSidebar"][aria-expanded="true"] {
            width: 15rem !important;
            min-width: 15rem !important;
            max-width: 15rem !important;
        }
    }
    </style>
""")
if "entries" not in st.session_state:
    st.session_state.entries = []

# ---- Sidebar ----
with st.sidebar:
    view = st.radio("Navigation", ["Dashboard", "Progress"])
    st.divider()
    st.header("Journal settings")
    day = st.date_input("Journal date", value=date.today(), max_value=date.today())
    goal = st.number_input("Daily calorie goal (kcal)", min_value=1, value=None,
                           placeholder="Optional", step=1)
    with st.expander("Daily macro goals"):
        macro_goals = {
            name: st.number_input(f"{name} goal (g)", min_value=0.1, value=None, step=1.0)
            for name in MACROS
        }

@st.dialog("Log my weight")
def weight_dialog():
    with st.form("weight_entry", enter_to_submit=False):
        entry_date = st.date_input("Date", value=day, max_value=date.today())
        amount = st.number_input("Weight (lb)", min_value=0.1, value=None, step=0.1)
        st.caption("Saving another weight for the same date updates that day's point.")
        with st.container(horizontal=True):
            cancel = st.form_submit_button("Cancel")
            done = st.form_submit_button("Done", type="primary")
    if cancel:
        st.rerun()
    if done:
        if amount is None:
            st.error("Enter a weight before saving.")
        else:
            st.session_state.weights[entry_date] = amount
            st.rerun()


if view == "Progress":
    if "weights" not in st.session_state:
        st.session_state.weights = {}
    heading, action = st.columns([3, 1], vertical_alignment="center")
    heading.title("Progress")
    if action.button("Add Weight Entry", type="primary"):
        weight_dialog()

    st.subheader("Weight history")
    if st.session_state.weights:
        history = pd.DataFrame(sorted(st.session_state.weights.items()), columns=["Date", "Weight (lb)"])
        chart = alt.Chart(history).mark_line(point=True).encode(
            x=alt.X("Date:T", scale=alt.Scale(type="utc"),
                    axis=alt.Axis(format="%m/%d", tickMinStep=86_400_000)),
            y=alt.Y("Weight (lb):Q", scale=alt.Scale(zero=False)),
            tooltip=["Date:T", "Weight (lb):Q"],
        )
        st.altair_chart(chart, width="stretch")
        with st.expander("Logged weight entries", expanded=True):
            st.dataframe(
                history.sort_values("Date", ascending=False),
                hide_index=True,
                width="stretch",
                column_config={"Date": st.column_config.DateColumn(format="MM/DD/YYYY")},
            )
    else:
        st.info("Add your first weight entry to start your graph.")
    st.stop()

st.title("VitalFlow")
st.subheader(day.strftime("%A, %B %d, %Y"))
entries = [entry for entry in st.session_state.entries if entry["Date"] == day]
total = sum(entry["Calories (kcal)"] for entry in entries)

logged, target, balance = st.columns(3)
logged.metric("Consumed", f"{total:,} kcal", border=True)
target.metric("Daily goal", f"{goal:,} kcal" if goal else "Unset", border=True)
above = goal is not None and total > goal
balance.metric("Above goal" if above else "Remaining",
               f"{abs(goal - total):,} kcal" if goal else "—", border=True)
if goal:
    st.progress(min(total / goal, 1.0))

for name, column in zip(MACROS, st.columns(3)):
    grams = sum(entry.get(name) or 0 for entry in entries)
    daily_goal = macro_goals[name]
    column.progress(min(grams / daily_goal, 1.0) if daily_goal else 0.0, text=name)
    goal_text = f"{daily_goal:g} g" if daily_goal else "goal unset"
    column.caption(f"{grams:g} g / {goal_text}")

def portion_details(product):
    nutrients = product.get("nutriments") or {}
    size = product.get("serving_size")
    quantity = pd.to_numeric(product.get("serving_quantity"), errors="coerce")
    unit = product.get("serving_quantity_unit") or "g"
    has_quantity = quantity > 0 and unit in ("g", "ml")
    use_serving = has_quantity or any(
        nutrients.get(f"{key}_serving") is not None
        for key in ("energy-kcal", "proteins", "carbohydrates", "fat")
    )
    serving = size or (f"{quantity:g} {unit}" if has_quantity else "unlisted")
    basis = f"per serving ({serving})" if use_serving else "per 100 g or 100 ml"
    values = {}
    for label, key in zip(("Calories", *MACROS), ("energy-kcal", "proteins", "carbohydrates", "fat")):
        value = nutrients.get(f"{key}_serving") if use_serving else None
        if value is None and (has_quantity or not use_serving):
            per_100 = nutrients.get(f"{key}_100g")
            if per_100 is not None:
                value = float(per_100) * (quantity / 100 if has_quantity else 1)
        values[label] = round(float(value), 2) if value is not None else None
    return serving, basis, values


def select_product(name, basis, values):
    st.session_state.lookup_food = name
    st.session_state.lookup_basis = basis
    st.session_state.lookup_calories = round(values["Calories"]) if values["Calories"] is not None else None
    for macro in MACROS:
        st.session_state[f"lookup_{macro}"] = values[macro]
    st.session_state.pop("lookup_results", None)


def clear_product():
    if st.session_state.pop("lookup_basis", None):
        for field in ("calories", *MACROS):
            st.session_state[f"lookup_{field}"] = None
    st.session_state.pop("lookup_results", None)


@st.dialog("Log meal")
def food_dialog():
    meal = st.selectbox("Meal", ["Breakfast", "Lunch", "Dinner", "Snack"], key="lookup_meal")
    method = st.radio("Entry method", ["Search foods", "Enter manually"], horizontal=True,
                      key="lookup_method", on_change=clear_product)
    food = st.text_input("Food Name", key="lookup_food", on_change=clear_product)
    if method == "Search foods" and st.button("Search", disabled=not food.strip()):
        try:
            with st.spinner("Loading..."):
                time.sleep(2)
            st.session_state.lookup_results = search_foods(food.strip())
        except requests.HTTPError as error:
            st.error(f"Food search returned HTTP {error.response.status_code}. Please try again later.")
        except requests.RequestException as error:
            st.error(f"Search failed: {error}")

    results = st.session_state.get("lookup_results")
    if results == []:
        st.info("No products found.")
    for index, product in enumerate(results or []):
        name = product.get("product_name") or "Unnamed product"
        brand = product.get("brands") or "Brand unlisted"
        if isinstance(brand, list):
            brand = ", ".join(brand)
        serving, basis, values = portion_details(product)
        energy = values["Calories"]
        kcal = f"{energy:g} kcal {basis}" if energy is not None else "Calories unlisted"
        with st.container(border=True):
            st.button(f"{name} · {brand}", key=f"lookup_result_{index}",
                      on_click=select_product, args=(name, basis, values))
            st.caption(f"{kcal} · Serving size: {serving}")
            code = str(product.get("code") or "")
            if code.isdigit():
                st.caption(f"[Open Food Facts](https://world.openfoodfacts.org/product/{code})")
            else:
                st.caption("Open Food Facts")

    if "lookup_basis" in st.session_state:
        st.caption(f"Nutrition {st.session_state.lookup_basis}. Adjust the amounts for your portion.")
    calories = st.number_input("Calories (kcal)", min_value=0, value=None, step=1, key="lookup_calories")
    macros = macro_inputs("lookup")
    if st.button("Add to journal", type="primary", key="lookup_save"):
        if food.strip() and calories is not None:
            st.session_state.entries.append({
                "Date": day, "Meal": meal, "Food Name": food.strip(),
                "Calories (kcal)": calories, **macros,
            })
            st.rerun()
        else:
            st.error("Enter a food and its calories to save this entry.")


heading, action = st.columns([3, 1], vertical_alignment="center")
heading.subheader("Today's meals" if day == date.today() else "Meals")
if action.button("Log meal", type="primary", icon=":material/add:"):
    for key in list(st.session_state):
        if key.startswith("lookup_"):
            del st.session_state[key]
    food_dialog()

if not entries:
    st.info("Your log is empty for this date. Log a meal to start tracking.")

for meal in ["Breakfast", "Lunch", "Dinner", "Snack"]:
    foods = [entry for entry in entries if entry["Meal"] == meal]
    if foods:
        subtotal = sum(food["Calories (kcal)"] for food in foods)
        with st.expander(f"{meal}  ·  {subtotal:,} kcal", expanded=False):
            for food in foods:
                name, calories = st.columns([3, 1])
                name.text(food.get("Food Name") or food.get("Food and portion") or "Unnamed food")
                calories.text(f"{food['Calories (kcal)']:,} kcal")
