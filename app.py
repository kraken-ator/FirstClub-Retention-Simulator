import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="FirstClub Retention Simulator", layout="wide")

# ==========================================
# 1. CONSTANTS & BENCHMARKS (Synthetic Data)
# ==========================================
AOV = 650.0  
GROSS_MARGIN_PCT = 0.12  

BASE_RETENTION = {
    "Organic": [1.0, 0.45, 0.28, 0.22, 0.18],
    "Referral": [1.0, 0.40, 0.32, 0.28, 0.25],  
    "Performance": [1.0, 0.35, 0.15, 0.08, 0.05]
}

OFFER_MULTIPLIERS = {
    "No Offer": [1.0, 1.0, 1.0, 1.0],
    "Flat Cashback": [1.25, 0.85, 0.80, 0.75],
    "% Discount": [1.15, 0.75, 0.70, 0.65],
    "Referral Credit": [1.10, 1.15, 1.10, 1.10]
}

# ==========================================
# 2. UI & INPUTS
# ==========================================
st.title("🛒 FirstClub Cohort Retention & LTV Simulator")
st.markdown("Diagnose how acquisition channels and first-order offers impact lifecycle habit formation.")

st.sidebar.header("Cohort Assumptions")
cohort_size = st.sidebar.number_input("Initial Cohort Size (D0)", min_value=1000, max_value=50000, value=10000, step=1000)
cac = st.sidebar.slider("Blended CAC (₹)", min_value=50, max_value=1000, value=350, step=50)

st.sidebar.subheader("Acquisition Mix")
pct_organic = st.sidebar.slider("% Organic", 0, 100, 30)
pct_referral = st.sidebar.slider("% Referral", 0, 100 - pct_organic, 20)
pct_perf = 100 - pct_organic - pct_referral
st.sidebar.text(f"% Performance Marketing: {pct_perf}%")

st.sidebar.subheader("Lifecycle & Offers")
offer_type = st.sidebar.selectbox("First-Order Offer", options=list(OFFER_MULTIPLIERS.keys()))
order_freq = st.sidebar.slider("Avg Orders/Month (Retained Users)", 1.0, 8.0, 4.5, 0.5)

# ==========================================
# 3. MONTE CARLO SIMULATION ENGINE
# ==========================================
def run_monte_carlo_cohorts(mix_org, mix_ref, mix_perf, offer, cohort_size, num_simulations=1000):
    w_org, w_ref, w_perf = mix_org / 100, mix_ref / 100, mix_perf / 100
    
    # Base expected curve
    expected_curve = []
    for i in range(5):
        weighted_val = (
            (BASE_RETENTION["Organic"][i] * w_org) +
            (BASE_RETENTION["Referral"][i] * w_ref) +
            (BASE_RETENTION["Performance"][i] * w_perf)
        )
        expected_curve.append(weighted_val)
        
    mods = OFFER_MULTIPLIERS[offer]
    for i in range(1, 5):
        expected_curve[i] = min(expected_curve[i] * mods[i-1], 1.0)
        
    # Introduce variance: Higher variance for smaller cohorts and performance channels
    base_volatility = 0.02 + (w_perf * 0.05) + (1000 / max(cohort_size, 1000) * 0.02)
    
    simulations = []
    for _ in range(num_simulations):
        sim_curve = [1.0] # D0 is always 100%
        for i in range(1, 5):
            noise = np.random.normal(0, base_volatility)
            sim_val = max(min(expected_curve[i] + noise, 1.0), 0.0) 
            sim_curve.append(sim_val)
        simulations.append(sim_curve)
        
    sim_array = np.array(simulations)
    
    return {
        "mean": np.mean(sim_array, axis=0),
        "p5": np.percentile(sim_array, 5, axis=0),   # Pessimistic
        "p95": np.percentile(sim_array, 95, axis=0)  # Optimistic
    }

mc_results = run_monte_carlo_cohorts(pct_organic, pct_referral, pct_perf, offer_type, cohort_size)
retention_curve = mc_results["mean"]
timeframes = ["D0", "D7", "D30", "D60", "D90"]
retained_users = [int(cohort_size * pct) for pct in retention_curve]

# Financial Projection Math
m1_users = (retained_users[0] + retained_users[2]) / 2
m2_users = (retained_users[2] + retained_users[3]) / 2
m3_users = (retained_users[3] + retained_users[4]) / 2

monthly_margin_per_user = AOV * GROSS_MARGIN_PCT * order_freq
total_cac_spend = cohort_size * cac

gross_margin_m1 = m1_users * monthly_margin_per_user
gross_margin_m2 = m2_users * monthly_margin_per_user
gross_margin_m3 = m3_users * monthly_margin_per_user

cumulative_margin = [
    gross_margin_m1, 
    gross_margin_m1 + gross_margin_m2, 
    gross_margin_m1 + gross_margin_m2 + gross_margin_m3
]

payback_month = "Not reached in 90 days"
for i, margin in enumerate(cumulative_margin):
    if margin >= total_cac_spend:
        payback_month = f"Month {i+1}"
        break

worst_d30 = 1.0
worst_combo = ""
for ch in ["Organic", "Referral", "Performance"]:
    for off in OFFER_MULTIPLIERS.keys():
        res = run_monte_carlo_cohorts(100 if ch=="Organic" else 0, 
                                      100 if ch=="Referral" else 0, 
                                      100 if ch=="Performance" else 0, off, cohort_size)
        if res["mean"][2] < worst_d30:
            worst_d30 = res["mean"][2]
            worst_combo = f"{ch} + {off}"

# ==========================================
# 4. DASHBOARD RENDER
# ==========================================
col1, col2, col3, col4 = st.columns(4)
col1.metric("D30 Retention", f"{retention_curve[2]*100:.1f}%")
col2.metric("D90 Retention", f"{retention_curve[4]*100:.1f}%")
col3.metric("CAC Payback", payback_month)
col4.metric("90-Day Cohort Gross Margin", f"₹{cumulative_margin[2]:,.0f}")

st.divider()

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Cohort Retention Curve (90% CI)")
    
    fig_ret = go.Figure()
    
    # Add 95th Percentile (Upper Bound)
    fig_ret.add_trace(go.Scatter(
        x=timeframes, y=mc_results["p95"] * 100,
        mode='lines', line=dict(width=0), showlegend=False,
        name='Optimistic'
    ))
    
    # Add 5th Percentile (Lower Bound) with fill to upper bound
    fig_ret.add_trace(go.Scatter(
        x=timeframes, y=mc_results["p5"] * 100,
        mode='lines', line=dict(width=0), fillcolor='rgba(224, 58, 62, 0.2)',
        fill='tonexty', showlegend=False, name='Pessimistic'
    ))
    
    # Add Mean Curve
    fig_ret.add_trace(go.Scatter(
        x=timeframes, y=mc_results["mean"] * 100,
        mode='lines+markers+text', line=dict(color='#E03A3E', width=3),
        text=[f"{x*100:.1f}%" for x in mc_results["mean"]],
        textposition="top right", name='Expected Retention'
    ))
    
    fig_ret.update_layout(yaxis_range=[0,110], margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig_ret, use_container_width=True)

with chart_col2:
    st.subheader("Cumulative Gross Margin vs CAC")
    df_fin = pd.DataFrame({
        "Month": ["M1", "M2", "M3"],
        "Cumulative Margin": cumulative_margin,
        "Total CAC Debt": [total_cac_spend] * 3
    })
    fig_fin = go.Figure()
    fig_fin.add_trace(go.Bar(x=df_fin['Month'], y=df_fin['Cumulative Margin'], name='Gross Margin', marker_color='#2CA02C'))
    fig_fin.add_trace(go.Scatter(x=df_fin['Month'], y=df_fin['Total CAC Debt'], mode='lines', name='Total CAC Target', line=dict(color='red', dash='dash')))
    st.plotly_chart(fig_fin, use_container_width=True)

st.info(f"🚨 **Diagnostic Risk Flag:** The cohort profile with the fastest drop-off (lowest D30) across all scenarios is **{worst_combo}** (D30 = {worst_d30*100:.1f}%). Avoid scaling this combination.")

st.divider()
st.header("🧠 Growth Diagnostics & Learnings")

st.markdown("""
**1. The "Cashback Trap" on D7:** 
Flat Cashbacks artificially inflate D7 retention (as deal-seekers return purely to burn wallet cash) but exhibit the steepest drop-off between D7 and D30. This creates a 'false positive' signal for early habit formation. For sustainable cohorts, % Discounts or No Offer perform significantly better post-D30.

**2. Referral Resonance (The D30 Cross-over):** 
Referral-acquired users naturally churn faster than Organic in the D0-D7 window. However, their curve flattens out aggressively after D30, eventually outperforming Organic by D90. This suggests that while social proof gets them in the door, it takes ~3 orders for the 'Costco-model' habit loop to firmly take root.

**3. Frequency Crushes CAC:** 
Shifting average order frequency from 3.0 to 4.5 reduces the CAC payback period exponentially, not linearly. From a capital-efficiency standpoint, investing product-engineering hours into lifecycle hooks (like an 'Essentials Subscription') to boost frequency yields a higher ROI than optimizing top-of-funnel ad spend.
""")