import hashlib
import json
import os
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO

import openai
import pandas as pd
import streamlit as st

from analysis_engine import analyze_pdf_page, analyze_text, cache_key
from collectors import CollectionError, youtube_collect
from youtube_pipeline import analyze_comments

st.markdown("""<style>
.stApp {background:#f8f9fb;color:#15171b} [data-testid="stMetric"] {background:white;padding:1rem;border-radius:16px;border:1px solid #e8ebef}
h1,h2,h3 {letter-spacing:-.03em} [data-testid="stSidebar"] {background:#f0f2f5}
</style>""", unsafe_allow_html=True)

MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna").strip() or "gpt-6-luna"
if "youtube_timestamp" in st.session_state and clock.time() - st.session_state.youtube_timestamp > 1800:
    st.session_state.pop("youtube_result", None)
    st.session_state.pop("youtube_timestamp", None)
    if st.session_state.get("analysis_origin") == "youtube":
        st.session_state.pop("analysis_data", None)
        st.session_state.pop("analysis_origin", None)
MENU = ["Overview", "Data Collection", "Sentiment Analysis", "Feature Analysis", "Product Comparison", "Customer Needs", "AI Insights", "Data Explorer", "Reports", "Settings"]


def mock_data():
    examples = [
        ("MacBook", "화면은 정말 좋은데 가격이 너무 비싸요.", "복합", "디스플레이", "긍정", "가격", "부정", "가격 인하"),
        ("MacBook", "Battery lasts all day, but it gets hot.", "복합", "배터리", "긍정", "신뢰성", "부정", "발열 개선"),
        ("Galaxy Book", "가볍고 성능도 만족합니다. 구매하고 싶어요.", "긍정", "디자인", "긍정", "성능", "긍정", "더 긴 배터리"),
        ("Apple Watch", "배터리가 너무 빨리 닳아서 구매를 망설입니다.", "부정", "배터리", "부정", "가격", "중립", "배터리 개선"),
        ("Galaxy Watch", "The display is bright outdoors and I like the design.", "긍정", "디스플레이", "긍정", "디자인", "긍정", "야외 시인성"),
        ("iPhone", "다음 세대에는 온디바이스 AI 기능이 더 좋아졌으면 합니다.", "중립", "미래 기능", "중립", "성능", "중립", "온디바이스 AI"),
    ]
    result = []
    for i in range(24):
        p, text, sentiment, f1, s1, f2, s2, need = examples[i % len(examples)]
        result.append({"제품":p, "내용":text, "출처":"가상 데이터", "유형":"가상 댓글", "날짜":(date(2026, 9, 1)+timedelta(days=i)).isoformat(), "URL":"", "언어":"영어" if text[0].isascii() else "한국어", "감정":sentiment,
            "기능":f1, "기능 감정":s1, "기능2":f2, "기능2 감정":s2, "주요 요청":need, "불만":need if sentiment in ("부정", "복합") else "", "구매 의향":"있음" if "구매하고" in text else "망설임" if "망설" in text else "미확인", "요약":text, "국가":"미확인", "분석 상태":"완료", "데이터 구분":"가상"})
    return pd.DataFrame(result)


def frame():
    return st.session_state.get("analysis_data", pd.DataFrame())


def apply_filters(df):
    if df.empty: return df
    with st.sidebar.expander("대시보드 필터", expanded=True):
        for column in ["제품", "출처", "언어", "감정"]:
            options = sorted(df[column].fillna("미확인").astype(str).unique())
            chosen = st.multiselect(column, options, key="filter_"+column)
            if chosen: df = df[df[column].isin(chosen)]
        feature = st.multiselect("기능", sorted(set(df["기능"].dropna()) | set(df["기능2"].dropna())))
        if feature: df = df[df["기능"].isin(feature) | df["기능2"].isin(feature)]
        dates = pd.to_datetime(df["날짜"], errors="coerce")
        if dates.notna().any():
            bounds = st.date_input("기간", (dates.min().date(), dates.max().date()), key="date_filter")
            if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
                df = df[(dates.dt.date >= bounds[0]) & (dates.dt.date <= bounds[1])]
    return df


def aspects(df):
    a = df[["제품", "내용", "출처", "URL", "기능", "기능 감정"]].copy()
    b = df[["제품", "내용", "출처", "URL", "기능2", "기능2 감정"]].copy()
    b.columns = a.columns
    return pd.concat([a, b], ignore_index=True).query("기능 != ''")


def show_evidence(df):
    if df.empty: return
    st.caption("근거 확인: 아래에서 항목을 선택하면 해당 원문과 출처를 표시합니다.")
    feature = st.selectbox("근거 항목", ["전체"] + sorted(set(df["기능"].dropna()) | set(df["기능2"].dropna())))
    if feature != "전체": df = df[(df["기능"] == feature) | (df["기능2"] == feature)]
    st.dataframe(df[["제품", "내용", "출처", "URL"]], hide_index=True, use_container_width=True)


st.sidebar.title("Product Intelligence")
menu = st.sidebar.radio("메뉴", MENU, label_visibility="collapsed")
st.sidebar.caption("분석 수치는 표본에 한정되며 모집단을 대표하지 않습니다.")

if menu == "Settings":
    st.title("Settings")
    st.write("API 키는 서버의 .env 또는 환경변수로 설정합니다. 화면이나 로그에 키를 표시하지 않습니다.")
    for name in ["OPENAI_API_KEY", "YOUTUBE_API_KEY"]:
        st.write(f"{name}: {'설정됨' if os.getenv(name, '').strip() else '미설정'}")
    st.write(f"OpenAI 모델: {MODEL}")
    approve_test = st.checkbox("OpenAI 연결 테스트 1회에 따른 API 비용 발생에 동의합니다.")
    if st.button("OpenAI 연결 테스트", disabled=not approve_test or not os.getenv("OPENAI_API_KEY")):
        try:
            check = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=30, max_retries=0).responses.create(model=MODEL, input="Reply OK.", max_output_tokens=100, store=False)
            if check.status == "completed" and check.output_text: st.success("OpenAI 응답 확인됨")
            else: st.warning("요청은 전송되었지만 완전한 텍스트 응답을 받지 못했습니다.")
        except openai.APIError as exc: st.error(f"연결 실패: {type(exc).__name__}. 키와 접근 권한, 연결 상태를 확인하세요.")
    st.markdown("[Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 만들고 YouTube Data API v3를 활성화한 뒤 API 키를 발급해 `.env`에 `YOUTUBE_API_KEY`로 추가하세요. 제한된 API 키 사용을 권장합니다. 앱을 재실행하면 적용됩니다.")
    st.markdown("[YouTube 정책 및 감사](https://developers.google.com/youtube/terms/developer-policies-guide) · [할당량 안내](https://developers.google.com/youtube/v3/determine_quota_cost) · [OpenAI 요금](https://platform.openai.com/pricing/) · [YouTube 이용약관](https://www.youtube.com/t/terms) · [Google 개인정보처리방침](https://policies.google.com/privacy)")
    st.info("YouTube 파생 지표는 승인된 분석 사용 사례와 감사가 필요할 수 있습니다. 해당 승인과 외부 전송 권한 및 비용 동의를 확인한 경우에만 분석을 실행하세요. 출처 간 결합은 지원하지 않습니다. 네이버 검색은 제외했습니다.")
    st.stop()

if menu == "Data Collection":
    st.title("Data Collection")
    tab_demo, tab_csv, tab_pdf, tab_youtube = st.tabs(["가상 데이터", "CSV 업로드", "PDF 이미지", "YouTube 공개 데이터"])
    with tab_demo:
        st.write("가상 리뷰를 사용해 모든 분석 화면을 비용 없이 체험합니다.")
        if st.button("가상 데이터 불러오기", type="primary"):
            st.session_state.analysis_data = mock_data()
            st.session_state.analysis_origin = "demo"
            st.success("가상 데이터 24건을 불러왔습니다. 실제 고객 반응이 아닙니다.")
    with tab_csv:
        st.write("분석 권한을 보유한 자체 데이터만 업로드하세요. YouTube API 또는 네이버 검색 결과는 업로드하지 마세요.")
        file = st.file_uploader("CSV 파일", type="csv")
        if file:
            try:
                data = file.getvalue()
                try: raw = pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig")
                except UnicodeDecodeError: raw = pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False, encoding="cp949")
                if raw.empty: st.warning("데이터가 없습니다."); st.stop()
                st.dataframe(raw.head(10), hide_index=True, use_container_width=True)
                default = next((i for i, c in enumerate(raw.columns) if any(x in c.lower() for x in ["문의", "내용", "comment", "text"])), 0)
                textcol = st.selectbox("분석할 내용 열", list(raw.columns), index=default)
                product = st.text_input("제품명", "MacBook", key="csv_product")
                cap = st.number_input("이번 실행 최대 분석 건수", 1, 100, 5, help="호출마다 비용이 발생합니다. 상한은 요청 건수 기준이며 금액 보장은 아닙니다.")
                confirmed = st.checkbox("권리를 확인했으며 OpenAI 전송과 API 요금 발생에 동의합니다.", key="csv_consent")
                if st.button("CSV 분석 시작", disabled=not confirmed or not os.getenv("OPENAI_API_KEY")):
                    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90, max_retries=1)
                    results, cache = [], st.session_state.setdefault("analysis_cache", {})
                    values = [v.strip() for v in raw[textcol] if v.strip()][:int(cap)]
                    progress = st.progress(0)
                    for i, text in enumerate(values):
                        try:
                            key = cache_key(MODEL, product, text)
                            if key not in cache: cache[key] = analyze_text(client, MODEL, product, text[:12000])
                            r = cache[key]
                            if r["is_spam"] or not r["is_relevant"]: continue
                            asp = r["aspects"][:2] + [{"feature":"", "sentiment":""}]*2
                            results.append({"제품":product, "내용":text, "출처":"사용자 CSV", "유형":"사용자 제공", "날짜":date.today().isoformat(), "URL":"", "언어":r["language"], "감정":r["sentiment"], "기능":asp[0]["feature"], "기능 감정":asp[0]["sentiment"], "기능2":asp[1]["feature"], "기능2 감정":asp[1]["sentiment"], "주요 요청":"; ".join(r["needs"]+r["future_features"]), "불만":"; ".join(r["complaints"]+r["defects"]), "구매 의향":r["purchase_intent"], "요약":r["summary"], "국가":"미확인", "분석 상태":"완료", "데이터 구분":"사용자 제공", "분석 JSON":json.dumps(r, ensure_ascii=False)})
                        except (openai.APIError, ValueError) as exc:
                            st.error(f"{i+1}번째 요청에서 오류가 발생해 중단했습니다. {type(exc).__name__}")
                            break
                        finally: progress.progress((i+1)/len(values))
                    if results:
                        st.session_state.analysis_data = pd.DataFrame(results)
                        st.session_state.analysis_origin = "csv"
                    st.success(f"완료 {len(results)}건. 스팸·무관 데이터는 결과에서 제외됩니다.")
            except (ValueError, pd.errors.ParserError, pd.errors.EmptyDataError): st.error("CSV 파일을 읽을 수 없습니다. UTF-8 또는 CP949 형식을 확인하세요.")
    with tab_pdf:
        st.write("이미지 PDF는 페이지를 이미지로 변환하여 OpenAI에 전송합니다. 권한이 있는 자료만 사용하세요.")
        pdf = st.file_uploader("고객 반응 PDF", type="pdf")
        pname = st.text_input("제품명", "MacBook", key="pdf_product")
        consent = st.checkbox("자료 사용 권한과 외부 전송 및 API 비용 발생에 동의합니다.", key="pdf_consent")
        if st.button("PDF 첫 페이지 분석", disabled=not pdf or not consent or not os.getenv("OPENAI_API_KEY")):
            try:
                import fitz
                doc = fitz.open(stream=pdf.getvalue(), filetype="pdf")
                if len(doc) == 0: raise ValueError("빈 PDF")
                image = doc[0].get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).tobytes("png")
                r = analyze_pdf_page(openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90), MODEL, image, pname)
                st.json(r)
                st.caption(f"총 {len(doc)}페이지 중 첫 페이지만 분석했습니다.")
                doc.close()
            except (ImportError, ValueError, RuntimeError, openai.APIError) as exc: st.error(f"PDF 분석 실패: {type(exc).__name__}")
    with tab_youtube:
        st.markdown("**YouTube 수집 → 댓글 AI 분석 → 대시보드** · 영상 메타데이터와 시청자 댓글은 별도입니다. 영상 설명은 리뷰 전문이 아닙니다.")
        st.markdown("이 기능을 이용하면 [YouTube 이용약관](https://www.youtube.com/t/terms)이 적용됩니다. [Google 개인정보처리방침](https://policies.google.com/privacy)을 확인하세요.")
        q = st.text_input("제품명 및 검색 키워드", "MacBook review")
        youtube_product = st.text_input("분석 대상 제품명", "MacBook", key="youtube_product")
        lang = st.selectbox("검색 언어", ["한국어", "영어"])
        order = st.selectbox("정렬", ["관련도", "최신순", "조회수"])
        a,b = st.columns(2)
        with a: nvideos = st.number_input("영상 수", 1, 50, 20)
        with b: ncomments = st.number_input("영상당 최대 댓글 수", 1, 500, 100)
        dates = st.date_input("영상 검색 기간", (date.today()-timedelta(days=30), date.today()), key="youtube_dates")
        reply = st.checkbox("대댓글 포함 (추가 API 호출)")
        auto_analysis = st.checkbox("수집 후 댓글 AI 분석 및 대시보드 자동 연결", value=False)
        approved = transfer = paid = False
        max_analysis = 10
        if auto_analysis:
            st.warning("YouTube 감성 분석 등 파생 지표는 API 프로젝트와 해당 사용 사례에 대한 Google의 감사·승인이 필요할 수 있습니다. [정책 및 감사 안내](https://developers.google.com/youtube/terms/developer-policies-guide)를 확인하세요. 출처 간 결합은 지원하지 않습니다.")
            approved = st.checkbox("이 프로젝트와 수집 대상 범위의 YouTube 파생 분석 승인을 받았습니다.")
            transfer = st.checkbox("이 데이터의 OpenAI 전송을 포함해 필요한 권리와 허용 범위를 확인했습니다.")
            paid = st.checkbox("OpenAI 분석 호출에 따른 비용 발생에 동의합니다.")
            max_analysis = st.number_input("최대 분석 댓글 수", 1, 100, 10, help="댓글 1건당 최대 1회 호출하며, 실패 시 재시도가 발생할 수 있습니다. 금액 상한은 아닙니다.")
        key = os.getenv("YOUTUBE_API_KEY", "").strip()
        if not key: st.warning("YOUTUBE_API_KEY가 없습니다. Settings에서 발급 방법을 확인하세요.")
        st.caption("기본 할당량은 search.list 하루 100회, 기타 호출 하루 10,000단위입니다. 페이지마다 호출됩니다.")
        blocked = auto_analysis and (not approved or not transfer or not paid or not os.getenv("OPENAI_API_KEY") or not youtube_product.strip())
        if st.button("YouTube 검색 및 수집", disabled=not key or not q.strip() or blocked):
            if len(dates) != 2: st.error("검색 시작일과 종료일을 모두 선택하세요.")
            else:
                bar = st.progress(0, text="영상 검색 중")
                def progress(i,total,ok,fail): bar.progress(i/max(total,1), text=f"영상 {i}/{total} · 댓글 {ok}건 · 실패 {fail}건")
                try:
                    if auto_analysis or st.session_state.get("analysis_origin") == "youtube":
                        st.session_state.pop("analysis_data", None)
                        st.session_state.pop("analysis_origin", None)
                    st.session_state.pop("youtube_result", None)
                    start = datetime.combine(dates[0], time.min, timezone.utc).isoformat().replace("+00:00", "Z")
                    end = datetime.combine(dates[1]+timedelta(days=1), time.min, timezone.utc).isoformat().replace("+00:00", "Z")
                    videos, comments, failures = youtube_collect(key, q.strip(), "ko" if lang == "한국어" else "en", start, end, {"관련도":"relevance", "최신순":"date", "조회수":"viewCount"}[order], int(nvideos), int(ncomments), reply, progress)
                    st.session_state.youtube_result = (videos, comments, failures)
                    st.session_state.youtube_timestamp = clock.time()
                    if auto_analysis and comments:
                        def ai_progress(i, total, ok, skipped, fail):
                            bar.progress(i/max(total, 1), text=f"AI 분석 {i}/{total} · 완료 {ok} · 제외 {skipped} · 실패 {fail}")
                        analysis, stats = analyze_comments(comments, youtube_product.strip(), openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90, max_retries=1), MODEL, int(max_analysis), approved=approved, transfer_authorized=transfer, progress=ai_progress)
                        if not analysis.empty:
                            st.session_state.analysis_data = analysis
                            st.session_state.analysis_origin = "youtube"
                        st.info(f"AI 분석: 완료 {stats['완료']}건 · 제외 {stats['제외']}건 · 실패 {stats['실패']}건 · 미처리 {stats['미처리']}건. Overview에서 결과를 확인하세요.")
                        if stats.get("댓글 오류"):
                            details = " · ".join(f"{reason} {count}건" for reason, count in stats["댓글 오류"].items())
                            st.warning(f"일부 댓글 분석 실패 · {details}")
                        if stats["오류"]: st.error(f"분석이 중단되었습니다: {stats['오류']}")
                    elif auto_analysis:
                        st.warning("분석할 댓글이 없습니다.")
                except CollectionError as exc: st.error(str(exc))
                bar.empty()
        if "youtube_result" in st.session_state:
            videos, comments, failures = st.session_state.youtube_result
            st.subheader(f"리뷰어 영상 메타데이터 · {len(videos)}건")
            st.dataframe(pd.DataFrame(videos), use_container_width=True, hide_index=True)
            st.subheader(f"시청자 댓글·대댓글 · {len(comments)}건")
            st.dataframe(pd.DataFrame(comments), use_container_width=True, hide_index=True)
            for failure in failures: st.warning(failure)
            if st.button("YouTube 임시 결과 지우기"):
                st.session_state.pop("youtube_result", None)
                st.session_state.pop("youtube_timestamp", None)
                if st.session_state.get("analysis_origin") == "youtube":
                    st.session_state.pop("analysis_data", None)
                    st.session_state.pop("analysis_origin", None)
                st.rerun()
    st.stop()

data = apply_filters(frame())
st.title(menu)
if data.empty:
    st.info("Data Collection에서 가상 데이터를 불러오거나 CSV를 분석하세요.")
    st.stop()
st.caption(f"표본 {len(data):,}건 · {', '.join(data['데이터 구분'].unique())} · 국가와 구매 여부는 확인되지 않은 경우 미확인으로 표시")
if menu == "Overview":
    a,b,c,d = st.columns(4)
    a.metric("표본", len(data)); b.metric("분석 완료", int((data["분석 상태"] == "완료").sum()))
    c.metric("긍정 비율", f"{(data['감정'] == '긍정').mean():.0%}"); d.metric("구매 의향 언급", f"{(data['구매 의향'] == '있음').mean():.0%}")
    left,right=st.columns(2)
    with left: st.subheader("감정 분포"); st.bar_chart(data["감정"].value_counts())
    with right: st.subheader("출처별 분포"); st.bar_chart(data["출처"].value_counts())
    st.subheader("기능별 반응"); st.bar_chart(pd.crosstab(aspects(data)["기능"], aspects(data)["기능 감정"]))
    st.subheader("주요 불만"); st.dataframe(data.loc[data["불만"] != "", "불만"].value_counts().head(10), use_container_width=True)
    show_evidence(data)
elif menu == "Sentiment Analysis":
    st.bar_chart(data["감정"].value_counts()); st.subheader("기간별 반응"); st.line_chart(pd.crosstab(data["날짜"], data["감정"])); show_evidence(data)
elif menu == "Feature Analysis":
    st.bar_chart(pd.crosstab(aspects(data)["기능"], aspects(data)["기능 감정"])); show_evidence(data)
elif menu == "Product Comparison":
    st.bar_chart(pd.crosstab(data["제품"], data["감정"])); st.caption("동일 기준 표본 비교이며 표본 수와 수집 방식 차이를 고려하세요.")
    release = st.date_input("공식 출시일", date(2026, 9, 1))
    dated = data.copy(); dated["경과일"] = (pd.to_datetime(dated["날짜"], errors="coerce").dt.date - release).apply(lambda x: x.days if pd.notna(x) else None)
    st.write("출시일 기준 경과일별 표본"); st.dataframe(dated[["제품", "날짜", "경과일", "감정", "내용"]], hide_index=True, use_container_width=True)
elif menu == "Customer Needs":
    st.subheader("주요 요청"); st.dataframe(data.loc[data["주요 요청"] != "", "주요 요청"].value_counts().head(10), use_container_width=True); show_evidence(data)
elif menu == "AI Insights":
    st.write("행별 분석 요약과 근거를 확인하세요. 가상 데이터 요약은 실제 AI 분석 결과가 아닙니다.")
    st.dataframe(data[["제품", "요약", "불만", "주요 요청"]], use_container_width=True, hide_index=True)
elif menu == "Data Explorer":
    st.dataframe(data, hide_index=True, use_container_width=True)
elif menu == "Reports":
    if st.session_state.get("analysis_origin") == "youtube":
        st.info("YouTube 데이터의 다운로드는 제공하지 않습니다. 승인된 저장·공유 범위를 별도로 확인하세요.")
    else:
        st.write("현재 필터가 적용된 분석 결과를 CSV로 내보냅니다.")
        st.download_button("분석 결과 CSV 다운로드", data.to_csv(index=False).encode("utf-8-sig"), "product_intelligence.csv", "text/csv")
