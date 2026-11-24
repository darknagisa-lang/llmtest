"""Product discovery and permission-gated YouTube comment analysis."""
import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import openai
import pandas as pd
import streamlit as st

from collectors import CollectionError, search_product_reviews, youtube_collect
from discovery import SETTINGS, key_from_files, read_cache, read_json, refresh_all, settings, write_json
from morning_brief import KST, SPECS, edition, read_brief, refresh as refresh_brief
from product_specs import model_key, official_image_url, resolve_specs, safe_source
from youtube_pipeline import analyze_comments
from analysis_engine import synthesize_display
from followup_brief import RULES_VERSION, read_followup, refresh_followup, selection_enabled
from planning_view import display_evidence, render as render_planning

st.html(Path(__file__).with_name("briefing.css"))


def review_heading(item, video):
    image, headline = st.columns([1, 2], vertical_alignment="center")
    with image:
        if video.get("thumbnail"):
            st.image(video["thumbnail"], width="stretch")
    with headline:
        st.html(f'<div class="brief-lane-label">{escape(item["category"])}</div>'
                f'<div class="brief-card-title">{escape(item["name"])}</div>')
        if video.get("published"):
            st.caption(f"영상 게시일 {video['published'][:10]}")


def product_search(key, config, now):
    with st.container(border=True, key="product_search"):
        st.subheader("제품 리뷰 검색")
        with st.form("homepage_product_search"):
            term = st.text_input("제품명", placeholder="예: Galaxy S26 Ultra, Pixel 10 Pro", max_chars=100)
            submitted = st.form_submit_button("YouTube 검색", type="primary", disabled=not key)
        st.caption(f"최근 {config['days']}일 · {'한국어' if config['language'] == 'ko' else '영어'} 검색 설정 적용")
        if submitted:
            st.session_state.pop("product_search_results", None)
            if not any(c.isalnum() for c in term):
                st.warning("정확한 제품명을 입력해 주세요.")
            else:
                try:
                    with st.spinner("제품 리뷰를 검색하는 중"):
                        results = search_product_reviews(key, term.strip(), config["language"],
                                                         (now - timedelta(days=config["days"])).isoformat(),
                                                         now.isoformat(), limit=min(12, config["videos"]))
                    st.session_state.product_search_results = {"product": term.strip(), "videos": results, "at": now}
                except CollectionError as exc:
                    st.error(f"제품 검색 실패 · {exc}")
        saved = st.session_state.get("product_search_results")
        if not saved:
            return
        if now - saved["at"] >= timedelta(minutes=30):
            st.session_state.pop("product_search_results", None)
            st.info("검색 결과가 만료되었습니다. 제품명을 다시 검색해 주세요.")
            return
        videos = saved["videos"]
        if not videos:
            st.info("검색된 영상이 없습니다. 제조사와 모델명을 함께 입력해 보세요.")
            return
        st.write("표에서 분석할 영상의 왼쪽 선택 칸을 클릭하세요. 여러 편을 선택할 수 있습니다.")
        table = st.dataframe(
            pd.DataFrame(videos).drop(columns="id"), width="stretch", hide_index=True,
            key=f"confirmed_videos_{saved['at'].isoformat()}",
            on_select="rerun", selection_mode="multi-row",
            column_order=["썸네일", "영상 제목", "채널", "게시일", "영상 링크"],
            column_config={"썸네일": st.column_config.ImageColumn(width="small"),
                           "영상 링크": st.column_config.LinkColumn(display_text="YouTube에서 보기")},
        )
        selected = [videos[index]["id"] for index in table.selection.rows if 0 <= index < len(videos)]
        action = f"선택한 영상 {len(selected)}편 분석하기" if selected else "선택한 영상 분석하기"
        if st.button(action, key="prepare_selected_videos", disabled=not selected, type="primary"):
            st.session_state.selected_product = {"name": saved["product"], "keyword": saved["product"],
                                                 "video_ids": selected, "searched": True}
            st.session_state.selected_from_brief = True
            st.session_state.pop("hub_result", None)
            st.rerun()

MODEL = "gpt-6-luna"
cloud = os.getenv("APP_DEPLOYMENT", "").strip().lower() == "cloud"


def workspace_read(path, default):
    return st.session_state.get(path.name, default) if cloud else read_json(path, default)


def workspace_write(path, value):
    if cloud:
        st.session_state[path.name] = value
    else:
        write_json(path, value)


cfg = st.session_state.get(SETTINGS.name, settings()) if cloud else settings()
youtube_key = key_from_files()
openai_key = os.getenv("OPENAI_API_KEY", "").strip()
with st.sidebar:
    st.html('<div class="workspace-name">Product Intelligence</div><div class="workspace-section">리서치 워크스페이스</div>')
    page = st.radio("메뉴", ["08시 신제품 브리핑", "관심 제품 검색", "검색 설정", "이용 안내"], label_visibility="collapsed")
    selected = st.session_state.get("selected_product")
    if selected and (page != "08시 신제품 브리핑" or st.session_state.get("selected_from_brief")):
        st.caption("열린 리포트")
        st.text(selected["name"])

if page == "이용 안내":
    st.title("이용 안내")
    st.markdown("YouTube 영상 정보와 공개 댓글을 구분합니다. **영상 제목·설명은 리뷰 전문이 아닙니다.** 제3자 영상의 자막 다운로드에는 영상 편집 권한이 필요합니다. [공식 자막 문서](https://developers.google.com/youtube/v3/docs/captions/download)")
    st.markdown("YouTube 댓글의 파생 분석은 사용 사례에 따라 Google의 감사와 승인이 필요합니다. [YouTube 정책](https://developers.google.com/youtube/terms/developer-policies-guide) · [YouTube 이용약관](https://www.youtube.com/t/terms) · [Google 개인정보처리방침](https://policies.google.com/privacy)")
    st.write("OpenAI 키:", "설정됨" if openai_key else ".env에 OPENAI_API_KEY를 설정해 주세요")
    st.write("YouTube 키:", "설정됨" if youtube_key else "2.env를 확인해 주세요")
    st.info("08시 브리핑은 한국 시간 오전 8시를 기준으로 직전 24시간의 영상을 확인합니다.")
    if cloud:
        st.caption("클라우드에서는 페이지를 열거나 새로 확인할 때 갱신합니다.")
    st.stop()

if page == "검색 설정":
    st.title("검색 설정")
    st.caption("설정은 이 브라우저 세션에 저장됩니다." if cloud else "설정은 이 PC의 프로젝트 폴더에 저장됩니다.")
    with st.form("settings"):
        lang = st.selectbox("검색 언어", ["한국어", "영어"], index=0 if cfg["language"] == "ko" else 1)
        days = st.number_input("상세 검색 기간 (일)", 1, 365, int(cfg["days"]))
        videos = st.number_input("검색 영상 수", 1, 50, int(cfg["videos"]))
        comments = st.number_input("영상당 최대 댓글 수", 1, 500, int(cfg["comments"]))
        limit = st.number_input("표본 분석 시 댓글 상한", 1, 100, int(cfg["analysis_limit"]))
        if st.form_submit_button("설정 저장", type="primary"):
            cfg.update(language="ko" if lang == "한국어" else "en", days=int(days), videos=int(videos), comments=int(comments), analysis_limit=int(limit))
            workspace_write(SETTINGS, cfg)
            st.success("설정을 저장했습니다.")
    st.subheader("주목할 만한 리뷰")
    with st.form("followup_settings"):
        followup_label = "이 세션에서 주목할 만한 리뷰 AI 선정 허용" if cloud else "주목할 만한 리뷰를 매일 오전 8시에 OpenAI로 선정"
        daily_ai = st.checkbox(followup_label, value=selection_enabled(cfg))
        st.caption("후보 영상 제목·게시일과 조회수·채널 신호를 OpenAI에 전송합니다. 해당 집계·전송의 허용 범위와 API 비용을 확인한 뒤 사용하세요.")
        if st.form_submit_button("자동 선정 설정 저장"):
            cfg["followup_ai"] = daily_ai
            cfg["followup_scope"] = RULES_VERSION if daily_ai else None
            workspace_write(SETTINGS, cfg)
            st.success("자동 선정 설정을 저장했습니다.")
    st.subheader("관심 제품")
    st.dataframe(pd.DataFrame(cfg["products"]).rename(columns={"name":"제품", "keyword":"검색어"}), hide_index=True, width="stretch")
    with st.form("add_product", clear_on_submit=True):
        name = st.text_input("제품명")
        keyword = st.text_input("검색 키워드", placeholder="예: iPhone 18 review")
        if st.form_submit_button("관심 제품 추가"):
            if not name.strip() or not keyword.strip(): st.warning("제품명과 검색 키워드를 입력하세요.")
            elif any(x["name"].casefold() == name.strip().casefold() for x in cfg["products"]): st.warning("이미 등록된 제품명입니다.")
            else:
                cfg["products"].append({"name":name.strip()[:100], "keyword":keyword.strip()[:200]})
                workspace_write(SETTINGS, cfg)
                st.rerun()
    remove = st.selectbox("삭제할 관심 제품", [""] + [p["name"] for p in cfg["products"]])
    if st.button("선택한 제품 삭제", disabled=not remove):
        cfg["products"] = [p for p in cfg["products"] if p["name"] != remove]
        workspace_write(SETTINGS, cfg)
        st.rerun()
    st.caption("기본값: 영상 20개, 영상당 댓글 100개. API 할당량과 분석 비용은 실제 검색 규모에 따라 달라집니다.")
    st.stop()

show_brief_detail = page == "08시 신제품 브리핑" and st.session_state.get("selected_from_brief", False)
if page == "08시 신제품 브리핑" and not show_brief_detail:
    now = datetime.now(timezone.utc)
    cutoff = edition(now)
    st.html(f'<section class="brief-hero"><div class="brief-date">{cutoff:%Y.%m.%d} · 08:00 KST</div>'
            '<h1>오늘의 제품 브리핑</h1>'
            '<p>글로벌 전자기기와 AI 글라스의 첫 리뷰, 장기 사용기, 여러 채널에서 주목받는 제품을 확인하세요.</p></section>')
    product_search(youtube_key, cfg, now)
    brief = read_brief(now)
    manual = st.button("브리핑 새로 확인", disabled=not youtube_key)
    attempt = st.session_state.get("brief_attempt")
    current_brief = brief.get("edition") == cutoff.isoformat() and brief.get("rules_version") == 2
    if youtube_key and (manual or (not current_brief and attempt != cutoff)):
        st.session_state.brief_attempt = cutoff
        try:
            with st.spinner("한국어·영어 리뷰를 찾는 중"):
                brief = refresh_brief(now)
        except (CollectionError, OSError) as exc:
            st.warning(f"브리핑을 갱신하지 못했습니다. ({type(exc).__name__})")
    if brief and brief.get("edition") != cutoff.isoformat():
        st.warning("최신 검색 결과를 기다리는 중입니다. 아래는 이전 브리핑입니다.")
    if brief:
        checked = datetime.fromisoformat(brief["checked_at"]).astimezone(KST)
        st.caption(f"마지막 확인 {checked:%m/%d %H:%M} · 리뷰에서 발견한 제품 후보이며 출시일은 별도 확인이 필요합니다.")
    if not youtube_key:
        st.info("YouTube 검색에 필요한 키를 2.env에 설정해 주세요.")
    early_column, followup_column = st.columns(2, gap="large")
    with followup_column:
        st.subheader("주목할 만한 리뷰")
        st.caption("장기 사용기 · 상대 조회수 · 여러 채널의 리뷰")
        followup = st.session_state.get("cloud_followup", {}) if cloud else read_followup(now)
        if not selection_enabled(cfg):
            st.info("검색 설정에서 권한과 비용을 확인하고 자동 선정을 켤 수 있습니다.")
        else:
            current = followup.get("edition") == cutoff.isoformat() and followup.get("rules_version") == RULES_VERSION
            if not current and st.button("오늘의 주목할 리뷰 선정", disabled=not (youtube_key and openai_key)):
                try:
                    with st.spinner("후속 리뷰 후보를 선별하는 중"):
                        if cloud:
                            followup = refresh_followup(now, config=cfg, previous=followup, persist=False)
                            st.session_state.cloud_followup = followup
                        else:
                            followup = refresh_followup(now)
                except (CollectionError, openai.APIError, ValueError, OSError, PermissionError) as exc:
                    st.warning(f"후속 리뷰를 선정하지 못했습니다. ({type(exc).__name__})")
            if followup.get("rules_version") == RULES_VERSION:
                date_label = datetime.fromisoformat(followup["edition"]).astimezone(KST)
                st.caption(f"{date_label:%m/%d} 브리핑 · 최근 {followup.get('lookback_days', 1)}일 영상에서 AI가 선정")
                if not followup["products"]:
                    st.info("조건에 맞는 후속 리뷰 후보가 없습니다.")
                for item in followup["products"]:
                    with st.container(border=True):
                        review_heading(item, item["video"])
                        signals = []
                        if item.get("long_use"):
                            signals.append("장기 사용기")
                        if item.get("channel_count", 0) >= 3:
                            signals.append(f"고유 채널 {item['channel_count']}곳")
                        if item.get("view_signal"):
                            signal = item["view_signal"]
                            signals.append(f"동일 연령대 중앙값 대비 {signal['ratio']:.1f}배")
                            st.caption(f"비교 영상 조회수 {signal['views']:,}회")
                            st.link_button("조회수 근거 영상", signal["url"])
                        if signals:
                            st.html("".join(f'<span class="brief-signal">{escape(label)}</span>' for label in signals))
                        st.write(item["reason"])
                        st.write("살펴볼 질문 · " + item["question"])
                        st.link_button("선정 근거 영상", item["video"]["url"])
                        if len(item.get("source_links", [])) > 1:
                            with st.expander("관련 리뷰 보기"):
                                for index, url in enumerate(item["source_links"], 1):
                                    st.link_button(f"리뷰 {index}", url)
                        if st.button("이 제품 분석하기", key="followup_" + item["name"], width="stretch", type="primary"):
                            st.session_state.selected_product = {**item, "followup": True}
                            st.session_state.selected_from_brief = True
                            st.session_state.pop("hub_result", None)
                            st.rerun()
    with early_column:
        st.subheader("신제품 리뷰")
        st.caption(f"{(cutoff - timedelta(days=1)):%m/%d %H:%M} ~ {cutoff:%m/%d %H:%M} 게시 영상 · 한국 시간")
        products = brief.get("products", [])
        if not products:
            st.info("이 브리핑에서 첫 리뷰가 확인된 제품이 없습니다.")
        specs = workspace_read(SPECS, {})
        for category in dict.fromkeys(p["category"] for p in products):
            for item in (p for p in products if p["category"] == category):
                with st.container(border=True):
                    video = item["videos"][0]
                    review_heading(item, video)
                    st.write(video["title"])
                    st.link_button("대표 리뷰 보기", video["url"])
                    record = specs.get(model_key(item["name"])) or specs.get(item["name"].casefold(), {})
                    if record:
                        st.text(record["text"])
                        st.link_button("등록된 공식 스펙 출처", record["url"])
                    else:
                        st.caption("공식 스펙 확인 전")
                    for mention in {m["value"]: m for m in item["mentions"]}.values():
                        st.markdown(f"[{mention['value']}]({mention['source']}) · 리뷰 제목에서 언급")
                    if st.button("리뷰 살펴보기", key="brief_" + item["name"], width="stretch", type="primary"):
                        st.session_state.selected_product = item
                        st.session_state.selected_from_brief = True
                        st.session_state.pop("hub_result", None)
                        st.rerun()

if page == "관심 제품 검색":
    st.title("관심 제품 검색")
    st.caption("등록한 제품의 최근 YouTube 영상과 소비자 반응을 상품기획 관점에서 살펴봅니다.")
    st.info("최근 영상은 신제품 출시 사실이나 전문 리뷰 여부를 보증하지 않습니다. YouTube 검색 결과를 직접 확인하세요.")
    cache = read_cache()
    missing = [p for p in cfg["products"] if p["name"] not in cache]
    last_attempt = st.session_state.get("discovery_attempt_at")
    if missing and youtube_key and (not last_attempt or (datetime.now(timezone.utc) - last_attempt).total_seconds() > 60):
        st.session_state.discovery_attempt_at = datetime.now(timezone.utc)
        try:
            with st.spinner("등록 제품의 최근 리뷰 영상을 확인하고 있습니다..."):
                cache = refresh_all()
        except (CollectionError, OSError) as exc: st.warning(f"검색하지 못했습니다: {type(exc).__name__}")
    if not youtube_key: st.warning("YouTube API 키가 없습니다. 2.env를 확인하세요.")
    if st.button("지금 새로 확인", disabled=not youtube_key):
        try:
            bar = st.progress(0, text="검색 중")
            cache = refresh_all(lambda done, total: bar.progress(done/max(total,1), text=f"검색 중 {done}/{total}"))
            bar.empty()
        except (CollectionError, OSError) as exc: st.error(f"검색 실패: {type(exc).__name__}")
    st.caption("페이지를 열었을 때 검색 결과가 없거나 24시간이 지나면 갱신합니다. 최근 영상 표시이며 실제 신제품 판정은 아닙니다.")
    for start in range(0, len(cfg["products"]), 3):
        cols = st.columns(3)
        for col, product in zip(cols, cfg["products"][start:start+3]):
            record = cache.get(product["name"], {})
            with col:
                with st.container(border=True):
                    v = record.get("videos", [])
                    if v and v[0].get("thumbnail"): st.image(v[0]["thumbnail"], width="stretch")
                    else: st.markdown("### 📱")
                    st.markdown("**" + product["name"].replace("*", "") + "**")
                    if v: st.link_button("최근 영상 보기", v[0]["url"])
                    if record.get("error"): st.warning("검색 오류: " + record["error"])
                    elif v: st.caption(f"최근 24시간 영상 {len(v)}건 표시 · 검색 최대 5건")
                    else: st.caption("최근 영상 없음" if record else "아직 검색하지 않음")
                    if record.get("checked_at"): st.caption("확인: " + record["checked_at"][:16].replace("T", " ") + " UTC")
                    if st.button("리뷰 살펴보기", key="product_"+product["name"], width="stretch"):
                        st.session_state.selected_product = product
                        st.session_state.selected_from_brief = False
                        st.session_state.pop("hub_result", None)
                        st.session_state.pop("hub_youtube_timestamp", None)
                        st.rerun()
if "selected_product" not in st.session_state or (page == "08시 신제품 브리핑" and not show_brief_detail):
    st.stop()
if show_brief_detail and st.button("← 오늘의 브리핑"):
    st.session_state.selected_from_brief = False
    st.session_state.pop("selected_product", None)
    st.session_state.pop("hub_result", None)
    st.rerun()
product = st.session_state.selected_product
st.caption("제품 반응 리포트 · YouTube 공개 댓글")
stage = "제품 반응" if product.get("searched") else "출시 후 반응" if product.get("followup") else "초기 반응"
st.header(f"{product['name']} · {stage}")
records = workspace_read(SPECS, {})
spec_key = model_key(product["name"])
existing = records.get(spec_key) or records.get(product["name"].casefold(), {})
specs = resolve_specs(product["name"], existing)
if specs is None or existing:
    with st.expander("제품 사양·공식 사진 등록"):
        with st.form("manufacturer_specs"):
            spec_text = st.text_area("출처에서 확인한 사양", existing.get("text", ""), max_chars=1200,
                                     placeholder="디스플레이: 6.3인치 OLED\n주사율: 120 Hz")
            spec_url = st.text_input("사양 출처 URL", existing.get("url", ""), max_chars=500)
            spec_image = st.text_input("제조사 제품 이미지 URL (선택)", existing.get("image", ""), max_chars=700)
            if st.form_submit_button("리포트에 사양 반영"):
                if not safe_source(spec_url.strip()) or not spec_text.strip():
                    st.warning("스펙과 HTTPS 출처를 입력해 주세요.")
                elif spec_image.strip() and not official_image_url(spec_image.strip(), spec_url.strip()):
                    st.warning("사양 출처와 같은 제조사의 HTTPS 이미지 주소를 입력해 주세요.")
                else:
                    records = workspace_read(SPECS, {})
                    records[spec_key] = {"text": spec_text.strip(), "url": spec_url.strip(), "image": spec_image.strip()}
                    workspace_write(SPECS, records)
                    st.rerun()
if product.get("searched"):
    st.caption(f"확인한 영상 {len(product['video_ids'])}편 · 영상당 댓글 최대 {cfg['comments']}개")
else:
    st.caption(f"검색어: {product['keyword']} · 최근 {cfg['days']}일 · 영상 최대 {cfg['videos']}개 · 영상당 댓글 최대 {cfg['comments']}개")
st.markdown("**분석 대상은 시청자 댓글입니다.** 리뷰어가 영상에서 말한 내용이나 구매자 여부는 확인하지 않습니다.")
scope = st.radio("분석 범위", ["수집한 댓글 전체", f"표본 분석 · 최대 {cfg['analysis_limit']}건"], horizontal=True)
analysis_limit = None if scope == "수집한 댓글 전체" else int(cfg["analysis_limit"])
with st.expander("YouTube 분석 승인 및 OpenAI 전송 확인", expanded=not st.session_state.get("hub_result")):
    st.markdown("YouTube 파생 지표는 승인된 사용 사례에 한해 허용될 수 있습니다. [감사 및 정책 안내](https://developers.google.com/youtube/terms/developer-policies-guide)")
    approved = st.checkbox("이 프로젝트와 해당 범위의 YouTube 파생 분석 승인을 받았습니다.")
    transfer = st.checkbox("댓글을 OpenAI에 전송할 권한과 허용 범위를 확인했습니다.")
    cost = st.checkbox(f"{scope} 범위의 OpenAI API 비용 발생에 동의합니다.", key=f"analysis_cost_{product['name']}_{scope}")
    st.caption("댓글을 최대 8건씩 묶어 분석합니다. 응답 형식에 문제가 있으면 묶음을 나눠 다시 시도하며, 디스플레이 근거가 있으면 종합 제안 요청 1건을 추가합니다.")
if not openai_key: st.warning("프로젝트 폴더의 .env에 OPENAI_API_KEY가 없습니다. 설정 후 앱을 재시작하세요.")
run_analysis = st.button("리뷰 수집 및 분석 시작", type="primary", disabled=not (youtube_key and openai_key and approved and transfer and cost))
if run_analysis:
    st.session_state.pop("hub_result", None)
    bar = st.progress(0, text="영상 검색 중")
    now = datetime.now(timezone.utc)
    try:
        selected_ids = {"selected_video_ids": product["video_ids"]} if product.get("searched") else {}
        vids, rows, failures = youtube_collect(
            youtube_key, product["keyword"], cfg["language"], (now-timedelta(days=cfg["days"])).isoformat(),
            now.isoformat(), "date", int(cfg["videos"]), int(cfg["comments"]), False,
            lambda i, total, ok, fail: bar.progress(i/max(total,1), text=f"수집 영상 {i}/{total} · 댓글 {ok}건 · 실패 {fail}건"),
            **selected_ids,
        )
        st.session_state.hub_youtube_timestamp = datetime.now(timezone.utc).isoformat()
        insights, report_error = [], ""
        if rows:
            client = openai.OpenAI(api_key=openai_key, timeout=90, max_retries=1)
            result, stats = analyze_comments(rows, product["name"], client, MODEL, analysis_limit, approved=approved, transfer_authorized=transfer,
                progress=lambda i,total,ok,skip,fail: bar.progress(i/max(total,1), text=f"AI 분석 {i}/{total} · 완료 {ok} · 제외 {skip} · 실패 {fail}"))
            if not result.empty:
                try:
                    evidence = [{key: value for key, value in item.items() if key != "url"}
                                for item in list(display_evidence(result).values())[:30]]
                    if evidence:
                        bar.progress(1.0, text="디스플레이 상품기획 제안 정리 중")
                        insights = synthesize_display(client, product["name"], evidence)
                except (openai.APIError, ValueError) as exc:
                    report_error = type(exc).__name__
        else:
            result, stats = pd.DataFrame(), {"완료":0, "제외":0, "실패":0, "미처리":len(rows), "오류":""}
        st.session_state.hub_result = {"product":product["name"], "videos":vids, "comments":rows, "result":result,
                                      "stats":stats, "failures":failures, "insights":insights, "report_error":report_error}
    except CollectionError as exc: st.error("수집 실패: " + str(exc))
    finally: bar.empty()

saved = st.session_state.get("hub_result")
timestamp = st.session_state.get("hub_youtube_timestamp")
if saved and timestamp and datetime.now(timezone.utc) - datetime.fromisoformat(timestamp) >= timedelta(minutes=30):
    st.session_state.pop("hub_result", None)
    st.session_state.pop("hub_youtube_timestamp", None)
    st.info("YouTube 임시 분석 결과가 만료되었습니다. 다시 수집해 주세요.")
    st.stop()
if saved and saved["product"] == product["name"]:
    videos, rows, result, stats = saved["videos"], saved["comments"], saved["result"], saved["stats"]
    for error in saved["failures"]: st.warning(error)
    target = stats.get("분석 대상")
    target_label = f" · 분석 대상 {target}건" if target is not None else ""
    st.caption(f"수집 영상 {len(videos)}건 · 댓글 {len(rows)}건{target_label} · 유효 댓글 {stats['완료']}건 · 제외 {stats['제외']}건 · 실패 {stats['실패']}건 · 미처리 {stats['미처리']}건")
    if stats.get("설정 상한 제외"):
        st.caption(f"미처리 중 {stats['설정 상한 제외']}건은 이번 실행의 분석 건수 상한을 초과했습니다.")
    if stats.get("댓글 오류"):
        details = " · ".join(f"{reason} {count}건" for reason, count in stats["댓글 오류"].items())
        st.warning(f"일부 댓글 분석 실패 · {details}. 나머지 결과는 아래에서 확인할 수 있습니다.")
    if stats["오류"]: st.error("분석 중단: " + stats["오류"])
    if saved.get("report_error"):
        st.warning(f"디스플레이 종합 제안을 생성하지 못했습니다. ({saved['report_error']}) 개별 댓글 분석은 아래에서 확인할 수 있습니다.")
    if not result.empty:
        render_planning(result, saved.get("insights", []), videos=videos, collected=len(rows),
                        product=product["name"], specs=specs)
    elif not videos:
        st.info("검색된 영상 없음")
    elif not rows:
        st.info("수집된 공개 댓글 없음")
    else:
        st.info("유효 분석 댓글이 없어 반응 비율을 집계할 수 없습니다.")
    with st.expander(f"영상 메타데이터 · {len(videos)}건"):
        st.caption("영상 설명은 리뷰 전문이 아닙니다."); st.dataframe(pd.DataFrame(videos), hide_index=True, width="stretch")
    with st.expander(f"시청자 댓글 원본 · {len(rows)}건"):
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

