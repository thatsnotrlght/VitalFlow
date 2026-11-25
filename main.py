import requests

from datetime import date, timedelta

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

if view == "Progress":
    st.title("Progress")
    start = day - timedelta(days=6)
    st.caption(f"Weekly calorie intake · {start:%b %d} – {day:%b %d, %Y}")
    week = [entry for entry in st.session_state.entries if start <= entry["Date"] <= day]
    if week:
        daily = pd.DataFrame(week).groupby("Date")["Calories (kcal)"].sum()
        st.bar_chart(daily, y_label="Calories (kcal)")
        if goal:
            st.caption(f"Current daily goal: {goal:,} kcal")
    else:
        st.info("Log a food during this week to see your daily calorie totals.")
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


@st.dialog("Add a food")
def food_dialog():
    meal = st.selectbox("Meal", ["Breakfast", "Lunch", "Dinner", "Snack"], key="lookup_meal")
    food = st.text_input("Food Name", key="lookup_food", on_change=clear_product)
    if st.button("Search", disabled=not food.strip()):
        try:
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


log, add = st.columns([3, 2], gap="large")
# with add:
#     st.subheader("Add a food")
#     with st.container(horizontal=True):
#         quick = st.button("Quick add")
#         normal = st.button("Add")
#     if quick or normal:
#         for key in list(st.session_state):
#             if key.startswith("lookup_"):
#                 del st.session_state[key]
#         food_dialog()

    # with st.form("meal_entry", clear_on_submit=True):
    #     meal = st.selectbox("Meal", ["Breakfast", "Lunch", "Dinner", "Snack"])
    #     food = st.text_input("Food and portion", placeholder="e.g. 1 bowl of oatmeal")
    #     calories = st.number_input("Calories (kcal)", min_value=0, value=None, step=1)
    #     macros = macro_inputs()
    #     if st.form_submit_button("Add to journal", type="primary"):
    #         if food.strip() and calories is not None:
    #             st.session_state.entries.append({
    #                 "Date": day, "Meal": meal, "Food Name": food.strip(),
    #                 "Calories (kcal)": calories, **macros,
    #             })
    #             st.rerun()
    #         else:
    #             st.error("Enter a food and its calories to save this entry.")
        


with log:
    st.subheader("Today's meals")
    if entries:
        df = pd.DataFrame(entries)

        if "Food and portion" in df.columns:
            df["Food Name"] = df.get("Food Name", df["Food and portion"]).fillna(df["Food and portion"])

        for meal in ["Breakfast", "Lunch", "Dinner", "Snack"]:
            foods = df.loc[df["Meal"] == meal, ["Food Name", "Calories (kcal)"]]
            if not foods.empty:
                st.subheader(meal)
                st.dataframe(foods, hide_index=True, width="stretch")
    else:
        normaltest = st.button("Log Meal", width = "stretch", icon="➕")
        if normaltest:
            for key in list(st.session_state):
                if key.startswith("lookup_"):
                    del st.session_state[key]
            food_dialog()

        st.info("Your log is empty for this date. Log a meal to start tracking.")
