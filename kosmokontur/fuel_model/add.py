import streamlit as st
import pandas as pd
import json
import os

# Импортируем функции из вашего расчётного ядра
from fuel_model.loader import load_case
from fuel_model.model import Plan
from fuel_model.scenarios import get
from fuel_model.engine import evaluate
from fuel_model.errors import PlanValidationError

st.set_page_config(page_title="Топливный космоконтур 2035", layout="wide", page_icon="🚀")

st.title("🚀 Цифровой двойник орбитального топливного узла")
st.markdown("Интерфейс оператора для планирования снабжения, оценки инвестиций и стресс-тестирования.")

# --- 1. Загрузка исходных данных (кешируем для скорости) ---
@st.cache_resource
def load_data():
    # Убедитесь, что папки data и configs лежат в корне репозитория. 
    # Если они внутри fuel_model, измените пути на "fuel_model/data" и т.д.
    return load_case("data", "configs")

try:
    case = load_data()
    st.sidebar.success("✅ Исходные данные (Case) успешно загружены")
except Exception as e:
    st.sidebar.error(f"❌ Ошибка загрузки данных: {e}")
    st.stop()

# --- 2. Загрузка плана ---
st.sidebar.header("1. Загрузка плана")
uploaded_file = st.sidebar.file_uploader("Загрузить JSON файл плана", type=["json"])

if uploaded_file is not None:
    try:
        plan_dict = json.load(uploaded_file)
        plan = Plan.from_dict(plan_dict)
        st.sidebar.success(f"✅ План '{plan.plan_id}' загружен")
    except Exception as e:
        st.sidebar.error(f"❌ Ошибка чтения плана: {e}")
        st.stop()
else:
    st.info("👈 Загрузите файл плана (например, из папки `results/plans/`) в боковой панели, чтобы начать работу.")
    st.stop()

# --- 3. Выбор сценария ---
st.sidebar.header("2. Выбор сценария")
scenario_choice = st.sidebar.selectbox(
    "Выберите сценарий для расчёта:",
    ["BASE", "MANDATORY_STRESS", "LOW_DEMAND", "HIGH_DEMAND"]
)

if st.sidebar.button("🚀 Рассчитать сценарий", type="primary"):
    with st.spinner("Выполняется расчёт материального баланса и экономики..."):
        scenario = get(scenario_choice)
        try:
            result = evaluate(case, plan, scenario)
        except PlanValidationError as exc:
            st.error("❌ **Ошибка валидации плана** (расчёт не запущен):")
            for issue in exc.issues:
                st.warning(f"[{issue.code}] **{issue.field}**: {issue.message}")
            st.stop()
    
    # --- 4. Отображение результатов ---
    st.subheader(f"Результаты расчёта: {scenario.name}")
    
    # Статус исполнимости
    if result.feasible:
        st.success("✅ **План исполним**: все жёсткие ограничения соблюдены.")
    else:
        st.error(f"❌ **План неисполним**: обнаружено {result.kpis['hard_violations']} критических нарушений.")

    # KPI метрики
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Общие затраты (PV)", f"{result.kpis['pv_total_cost']:.1f} млн у.е.")
    col2.metric("Мин. SL (Крит.)", f"{result.kpis['service_level_critical']:.1%}")
    col3.metric("Суммарный дефицит", f"{result.kpis['total_shortage']:.1f} т")
    col4.metric("Критич. нарушения", result.kpis['hard_violations'])

    # Таблица годового баланса
    st.subheader("📊 Годовой материальный баланс")
    df_yearly = pd.DataFrame(result.yearly)
    cols_to_show = ['year', 'demand_total', 'served_total', 'shortage_total', 'service_level_total', 'closing_inventory']
    st.dataframe(df_yearly[cols_to_show].style.format({
        'demand_total': '{:.1f}', 'served_total': '{:.1f}', 'shortage_total': '{:.2f}', 
        'service_level_total': '{:.1%}', 'closing_inventory': '{:.2f}'
    }), use_container_width=True)

    # Нарушения (если есть)
    if result.violations:
        st.subheader("⚠️ Нарушения ограничений")
        df_viol = pd.DataFrame([v.to_dict() for v in result.violations])
        # Красим HARD в красный, BENCHMARK в оранжевый
        def color_severity(val):
            if val == 'HARD': return 'color: red; font-weight: bold'
            if val == 'BENCHMARK': return 'color: orange; font-weight: bold'
            return ''
        st.dataframe(df_viol[['severity', 'code', 'year', 'message']].style.applymap(color_severity, subset=['severity']), use_container_width=True)

    # --- 5. Экспорт ---
    st.subheader("💾 Экспорт результатов")
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        csv_yearly = df_yearly.to_csv(index=False, encoding='utf-8-sig').encode('utf-8')
        st.download_button(
            label="📥 Скачать yearly.csv",
            data=csv_yearly,
            file_name=f"{plan.plan_id}_{scenario_choice}_yearly.csv",
            mime="text/csv"
        )
    
    with col_exp2:
        if result.violations:
            csv_viol = df_viol.to_csv(index=False, encoding='utf-8-sig').encode('utf-8')
            st.download_button(
                label="📥 Скачать violations.csv",
                data=csv_viol,
                file_name=f"{plan.plan_id}_{scenario_choice}_violations.csv",
                mime="text/csv"
            )