import streamlit as st
import os, sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.utils.ui_components import apply_rtl_style, render_sidebar_brand, get_logo_path

st.set_page_config(
    page_title="قاطب | المنصة الذكية",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_rtl_style()
render_sidebar_brand()

with st.sidebar:
    st.markdown("**النسخة التجريبية (MVP v1.0)**")

col_logo, col_title = st.columns([1, 6])
with col_logo:
    st.image(get_logo_path(), width=90)
with col_title:
    st.title("منصة قاطب للامتثال والتشريعات المالية")
st.subheader("الجمع التلقائي والدفاع التشريعي الذكي لمنشأتك")

col1, col2, col3, col4 = st.columns(4)
col1.metric(label="SAMA", value="مُفعل")
col2.metric(label="ZATCA", value="مُفعل")
col3.metric(label="CMA", value="مُفعل")
col4.metric(label="SDAIA", value="مُفعل")
st.write("---")

feat_col1, feat_col2, feat_col3 = st.columns(3)
with feat_col1:
    st.markdown("### 💬 المستشار الحواري الذكي")
with feat_col2:
    st.markdown("### 📄 التدقيق وكشف المخاطر")
with feat_col3:
    st.markdown("### 📑 توليد التقارير المتوافقة")

st.info("تنبيه: تعمل المنصة كخط دفاع أول (Human-in-the-Loop). يجب مراجعة واعتماد المخرجات النهائية.")
