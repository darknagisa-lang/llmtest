"""Charts and evidence for the product detail page."""
import json
import re
from html import escape

import pandas as pd
import streamlit as st
from product_specs import manufacturer_search_url

SENTIMENTS = ["긍정", "중립", "부정", "복합"]
COLORS = ["#0b806e", "#668197", "#bf5849", "#7556a4"]
PURCHASE_OPTIONS = {"있음": ("구매 의향 있음", "#0b806e"), "망설임": ("구매 망설임", "#a26b18"),
                    "없음": ("구매 의향 없음", "#bf5849"), "미확인": ("미확인", "#668197")}
LINK = st.column_config.LinkColumn("댓글 원문", display_text="열기")
DISPLAY_TOPICS = {
    "밝기·야외 시인성": r"밝기|밝[다은]|시인성|햇빛|nit|bright|sunlight",
    "반사·눈부심": r"반사|눈부심|glare|reflect",
    "색·명암": r"색감|색상|색재현|명암|검은색|color|contrast|black",
    "주사율·잔상": r"주사율|잔상|\d+\s*hz|refresh|ghosting",
    "가독성·눈 피로": r"가독성|눈\s*피로|깜빡|flicker|pwm|legib",
    "번인·내구성": r"번인|내구|burn.in|durab",
    "전력 소모": r"전력|소비전력|배터리|power|battery",
}


def sentiment_rates(result):
    counts = result["감정"].value_counts().reindex(SENTIMENTS, fill_value=0)
    return pd.DataFrame({"댓글 수": counts, "비율 (%)": counts * 100 / len(result)}) if len(result) else pd.DataFrame()


def display_evidence(result):
    citations = {}
    for number, (_, row) in enumerate(result.iterrows(), 1):
        analysis = json.loads(row["분석 JSON"])
        display = [a for a in analysis["aspects"] if a["feature"] == "디스플레이"]
        if display:
            citations[number] = {"id": number, "excerpt": row["내용"][:700], "url": row["URL"],
                                 "aspects": display, "future": analysis.get("future_features", [])}
    return citations


def video_coverage(videos):
    channels = {}
    peak_views = None
    seen = set()
    for index, video in enumerate(videos):
        url = video.get("원본 URL") or index
        if url in seen:
            continue
        seen.add(url)
        name = (video.get("채널명") or "").strip()
        channel = (video.get("채널 ID") or "").strip() or name.casefold()
        if channel:
            label, count = channels.get(channel, (name or "채널명 미확인", 0))
            channels[channel] = (label, count + 1)
        try:
            views = int(video.get("영상 조회수", ""))
        except (ValueError, TypeError):
            continue
        peak_views = views if peak_views is None else max(views, peak_views)
    return channels, peak_views


def render_insight(insight, evidence):
    st.caption(insight.kind)
    st.text(insight.headline)
    st.write("관찰 · " + insight.observation)
    st.write("기획 제안 · " + insight.proposal)
    st.write("검증 방법 · " + insight.validation)
    ids = [number for number in dict.fromkeys(insight.evidence_ids) if number in evidence]
    with st.expander(f"근거 댓글 {len(ids)}건"):
        for number in ids:
            source = evidence[number]
            st.text(source["excerpt"])
            if source["url"]:
                st.markdown(f"[댓글 {number} 원문]({source['url']})")


def render_purchase_chart(values):
    counts = values.value_counts()
    for status, (label, color) in PURCHASE_OPTIONS.items():
        count = int(counts.get(status, 0))
        ratio = 100 * count / len(values) if len(values) else 0
        st.html(f'<div class="chart-record"><div class="report-row"><span>{label}</span>'
                f'<strong>{count:,}건 <small>{ratio:.0f}%</small></strong></div>'
                f'<div class="report-track" aria-hidden="true"><div style="width:{ratio:.3f}%;background:{color}"></div></div></div>')


def render_feature_chart(features, group):
    features = (features.groupby(["댓글", group], as_index=False)["감정"]
                .agg(lambda votes: votes.iloc[0] if votes.nunique() == 1 else "복합"))
    counts = pd.crosstab(features[group], features["감정"]).reindex(columns=SENTIMENTS, fill_value=0)
    counts["_total"] = counts.sum(axis=1)
    counts = counts.sort_values("_total", ascending=False, kind="stable")
    scale = max(int(counts["_total"].max()), 1)
    for label, row in counts.iterrows():
        chips, segments = [], []
        for sentiment, color in zip(SENTIMENTS, COLORS):
            count = int(row[sentiment])
            if count:
                chips.append(f'<span style="--signal-color:{color}">{sentiment} {count:,}</span>')
                segments.append(f'<div style="width:{100 * count / scale:.3f}%;background:{color}"></div>')
        st.html(f'<div class="chart-record"><div class="report-row"><span>{escape(str(label))}</span>'
                f'<strong>{int(row["_total"]):,}건</strong></div><div class="report-track" aria-hidden="true">{"".join(segments)}</div>'
                f'<div class="chart-key">{"".join(chips)}</div></div>')


def render_product_specs(product, specs):
    with st.container(border=True, key="report_product_specs"):
        st.markdown("#### 제품 주요 사양")
        st.text(product)
        if not specs:
            st.caption("이 모델의 제조사 사양이 아직 등록되지 않았습니다.")
            st.link_button("제조사 사양 찾기", manufacturer_search_url(product))
            return
        if specs.get("image"):
            photo, details = st.columns([1, 2], gap="medium", vertical_alignment="center")
            photo.image(specs["image"], caption="제조사 제품 이미지", width="stretch")
        else:
            details = st.container()
        with details:
            if specs.get("fields"):
                fields = "".join(f'<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>'
                                 for label, value in specs["fields"].items())
                st.html(f'<dl class="report-spec-grid">{fields}</dl>')
            if specs.get("text"):
                st.text(specs["text"])
        st.caption(f"출처 · {specs['source']}")
        st.link_button("제조사 원문 보기" if specs.get("official") else "등록된 출처 보기", specs["url"])


def render(result, insights, *, videos=(), collected=None, product=None, specs=None):
    rates = sentiment_rates(result)
    evidence = display_evidence(result)
    channels, peak_views = video_coverage(videos)
    dominant = rates.index[rates["댓글 수"] == rates["댓글 수"].max()].tolist()
    leading_rate = rates["비율 (%)"].max()
    st.subheader("리포트 개요")
    if collected is not None and collected > len(result):
        st.caption(f"차트 분모 · 수집 댓글 {collected:,}건 중 유효 댓글 {len(result):,}건 ({len(result) / collected:.1%})")
    with st.container(key="report_kpis"):
        columns = st.columns(4)
        cards = [
            ("분석 표본", f"{len(result):,}건", f"수집 댓글 {collected:,}건" if collected is not None else "유효 댓글"),
            ("대표 감정", dominant[0] if len(dominant) == 1 else "공동 최다", f"{leading_rate:.1f}% · 유효 댓글 기준"),
            ("영상 최고 조회수", f"{peak_views:,}회" if peak_views is not None else "미확인", "수집 영상 중 단일 영상 기준"),
            ("리뷰 출처", f"{len(channels):,}개 채널", f"YouTube 영상 {len(videos):,}편"),
        ]
        for column, (name, value, detail) in zip(columns, cards):
            column.metric(name, value, help=detail)
            column.caption(detail)

    overview, display, opinions = st.tabs(["개요", "디스플레이 기획", "고객 의견·원문"])
    parsed = [json.loads(value) for value in result["분석 JSON"]]
    feature_rows = [
        (i, a["feature"], a["sentiment"])
        for i, detail in enumerate(parsed) for a in detail["aspects"]
    ]
    with overview:
        if product:
            render_product_specs(product, specs)
        left, right = st.columns([1, 1], gap="large")
        with left:
            with st.container(border=True):
                st.markdown("#### 데이터 출처와 반응")
                if channels:
                    for name, count in sorted(channels.values(), key=lambda pair: (-pair[1], pair[0]))[:5]:
                        st.html(f'<div class="report-row"><span>{escape(name)}</span><strong>{count}편</strong></div>')
                    if len(channels) > 5:
                        st.caption(f"외 {len(channels) - 5}개 채널 · 아래 영상 메타데이터에서 전체 확인")
                else:
                    st.caption("확인된 YouTube 채널 정보가 없습니다.")
                st.markdown("**감정 분포**")
                for (sentiment, row), color in zip(rates.iterrows(), COLORS):
                    rate = row["비율 (%)"]
                    st.html(f'<div class="report-row"><span>{sentiment}</span><strong>{rate:.1f}% · {int(row["댓글 수"])}건</strong></div>'
                            f'<div class="sentiment-track" aria-hidden="true"><div style="width:{rate:.2f}%;background:{color}"></div></div>')
                st.caption(f"반응 비율 분모 · 유효 댓글 {len(result):,}건")
        with right:
            with st.container(border=True):
                st.markdown("#### 우선 검토")
                priority = {"개선 우선순위": 0, "유지할 강점": 1, "차세대 기회": 2}
                ordered = sorted(insights, key=lambda item: (priority.get(item.kind, 3), -len(set(item.evidence_ids))))
                if not ordered:
                    st.caption("근거가 연결된 검토 항목이 없습니다.")
                for insight in ordered[:3]:
                    with st.container(border=True):
                        render_insight(insight, evidence)
                if len(ordered) > 3:
                    st.caption("전체 제안은 디스플레이 기획 탭에서 확인하세요.")
        purchase, feature = st.columns(2, gap="large")
        with purchase, st.container(border=True):
            st.markdown("#### 구매 의향")
            st.caption("유효 댓글 기준 · 미확인 포함")
            render_purchase_chart(result["구매 의향"])
        with feature, st.container(border=True):
            st.markdown("#### 기능별 반응")
            st.caption("기능을 언급한 댓글 수 · 한 댓글은 여러 기능에 포함될 수 있습니다.")
            if feature_rows:
                features = pd.DataFrame(feature_rows, columns=["댓글", "기능", "감정"]).drop_duplicates()
                render_feature_chart(features, "기능")
            else:
                st.info("기능별 반응을 집계할 근거가 없습니다.")
    with display:
        st.caption(f"디스플레이 관련 댓글 {len(evidence)}건 / 유효 댓글 {len(result)}건")
        if not insights:
            st.info("근거가 연결된 종합 기획 제안이 없습니다. 아래에 개별 근거가 있는 경우 확인할 수 있습니다.")
        for insight in insights:
            with st.container(border=True):
                render_insight(insight, evidence)
        if evidence:
            table = [{"감정": aspect["sentiment"], "사용 조건·평가": aspect["evidence"], "URL": source["url"]}
                     for source in evidence.values() for aspect in source["aspects"]]
            mentions = {
                (source["id"], topic, aspect["sentiment"])
                for source in evidence.values() for aspect in source["aspects"]
                for topic, pattern in DISPLAY_TOPICS.items() if re.search(pattern, aspect["evidence"], re.I)
            }
            if mentions:
                topics = pd.DataFrame(list(mentions), columns=["댓글", "평가 항목", "감정"])
                st.markdown("**디스플레이 세부 평가 · 항목별 댓글 수**")
                render_feature_chart(topics, "평가 항목")
            st.dataframe(table, column_config={"URL": LINK}, hide_index=True, width="stretch")
    with opinions:
        rows = []
        for (_, row), detail in zip(result.iterrows(), parsed):
            aspects = detail["aspects"]
            rows.append({
                "감정": row["감정"], "긍정 요소": " / ".join(a["evidence"] for a in aspects if a["sentiment"] == "긍정"),
                "부정 요소": " / ".join(a["evidence"] for a in aspects if a["sentiment"] == "부정"),
                "구매 의향": row["구매 의향"], "불만·결함 언급": row["불만"], "개선 요구": row["주요 요청"],
                "기존 제품 대비": " / ".join(detail.get("improvements", [])),
                "경쟁 비교": " / ".join(detail.get("comparisons", [])),
                "차세대 기대": " / ".join(detail.get("future_features", [])),
                "요약": row["요약"], "원문": row["내용"], "URL": row["URL"],
            })
        if not any(item["경쟁 비교"] for item in rows):
            st.caption("경쟁 제품 비교 근거 없음")
        st.dataframe(rows, column_config={"URL": LINK}, hide_index=True, width="stretch")
