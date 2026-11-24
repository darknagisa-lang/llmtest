import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from discovery import load_api_keys

try:
    for name in ("OPENAI_API_KEY", "YOUTUBE_API_KEY", "OPENAI_MODEL", "APP_DEPLOYMENT"):
        value = st.secrets.get(name)
        if isinstance(value, str) and value.strip():
            os.environ[name] = value.strip()
except StreamlitSecretNotFoundError:
    pass
load_api_keys()
st.set_page_config(page_title="Product Intelligence", page_icon="📊", layout="wide", initial_sidebar_state="auto")
pages = [st.Page("product_hub.py", title="신제품 리뷰 탐색", icon="📱"),
         st.Page("dashboard.py", title="기존 분석 대시보드", icon="📊"),
         st.Page("legacy_inquiries.py", title="기존 고객 문의 분석", icon="💬")]
st.navigation(pages).run()
