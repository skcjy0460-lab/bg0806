# -*- coding: utf-8 -*-
"""
병원 블로그 AI 자동 생성기 (Hospital Blog AI Generator)
------------------------------------------------------
황금 키워드 분석 → 제목 추천 → 글 구조 설계 → 본문 자동 작성 → 의료광고법 위반 소지 자동 체크
까지 한 번에 처리하는 병원 마케팅 전용 블로그 콘텐츠 생성 도구.

제작: 주식회사 메디엄 (조정윤)
AI 엔진: Google Gemini API (google-genai SDK)
"""

import streamlit as st
import json
import re
import io
from datetime import datetime

from google import genai
from google.genai import types


# =========================================================================
# 0. 페이지 설정
# =========================================================================
st.set_page_config(
    page_title="병원 블로그 AI 자동 생성기",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    .main .block-container { padding-top: 2rem; max-width: 1100px; }
    .step-badge {
        display: inline-flex; align-items: center; justify-content: center;
        width: 32px; height: 32px; border-radius: 50%;
        font-weight: 700; font-size: 14px; margin-right: 8px;
    }
    .step-active { background-color: #1e6f5c; color: white; }
    .step-done { background-color: #a8d5c4; color: #1e6f5c; }
    .step-todo { background-color: #e9ecef; color: #868e96; }
    .warn-box {
        background-color: #fff3f3; border-left: 4px solid #e03131;
        padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;
    }
    .ok-box {
        background-color: #f1f8f4; border-left: 4px solid #2f9e44;
        padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;
    }
    .keyword-chip {
        display: inline-block; background-color: #eef6ff; color: #1864ab;
        border-radius: 14px; padding: 4px 12px; margin: 3px; font-size: 13px;
    }
    .keyword-chip-sub {
        display: inline-block; background-color: #fff9db; color: #997404;
        border-radius: 14px; padding: 4px 12px; margin: 3px; font-size: 13px;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# =========================================================================
# 1. 상수 정의
# =========================================================================
DEPARTMENTS = [
    "내과", "외과", "정형외과", "신경외과", "신경과", "산부인과", "소아청소년과",
    "피부과", "성형외과", "안과", "이비인후과", "비뇨의학과", "치과", "정신건강의학과",
    "재활의학과", "가정의학과", "한방과", "영상의학과", "건강검진센터", "기타(직접입력)",
]

PURPOSES = {
    "정보 전달": "질환/시술/검사에 대한 정확한 정보를 알기 쉽게 전달하는 글",
    "후기·리뷰": "환자 경험을 재구성한 신뢰감 있는 후기형 글 (실제 후기 인용 금지, 가상 사례로만 구성)",
    "비교·추천": "치료법/병원 선택 기준을 비교해주는 글",
    "노하우·꿀팁": "관리법, 예방법, 생활 습관 등 실용 정보 위주의 글",
    "문제 해결": "특정 증상/고민에 대한 원인과 해결 방향을 제시하는 글",
}

TONES = ["친근하고 편안한 말투", "전문적이고 신뢰감 있는 말투", "따뜻하고 공감적인 말투", "간결하고 정보 위주의 말투"]

# 진료과별 심의 민감도 (사전심의 대상 및 특별 유의 진료과)
HIGH_SENSITIVITY_DEPTS = {"피부과", "성형외과", "치과", "한방과", "비뇨의학과"}

MODEL_OPTIONS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro", "gemini-1.5-flash"]

# 의료법 제56조 및 의료광고 자율심의기준 참고 - 금지/위험 표현 룰베이스
# ※ 완전한 법적 판단 기준이 아니며, 실제 게재 전 반드시 자율심의기구 심의를 거쳐야 함
PROHIBITED_PATTERNS = {
    "치료효과 보장·확언 (의료법 제56조 2항 2호)": [
        r"100\s*%\s*(완치|치료|효과)", r"완치\s*보장", r"무조건\s*(완치|성공|낫)",
        r"반드시\s*(낫습니다|치료됩니다|좋아집니다)", r"부작용\s*(이|가)?\s*(전혀\s*)?없", r"통증\s*(이|가)?\s*(전혀\s*)?없",
        r"즉시\s*효과", r"평생\s*보장", r"재발\s*(이|가)?\s*없", r"실패\s*(율|없)\s*0",
    ],
    "비교 우위·최상급 표현 (의료법 제56조 2항 3호)": [
        r"국내\s*(최고|최다|1위|유일)", r"업계\s*1위", r"세계\s*최초", r"국내\s*최초",
        r"타\s*병원.{0,10}(비교|보다\s*낫)", r"가장\s*저렴", r"최상의\s*의료진",
    ],
    "체험담·후기 오남용 (의료법 제56조 2항 4·5호)": [
        r"환자\s*후기", r"체험담", r"수술\s*전후\s*사진", r"before\s*[-/]?\s*after", r"비포\s*애프터",
        r"실제\s*환자\s*사진", r"수술\s*전\s*[.]{0,3}\s*수술\s*후",
    ],
    "할인·유인성 이벤트 표현 (의료법 제27조 3항, 환자 유인·알선 금지)": [
        r"파격\s*할인", r"반값", r"무료\s*시술", r"이벤트\s*진행\s*중", r"선착순\s*\d+\s*명",
        r"지금\s*예약하면.{0,10}할인", r"오늘만\s*특가",
    ],
    "미검증·과장 신뢰성 표현": [
        r"부작용\s*zero", r"의학적으로\s*증명된\s*바\s*없", r"임상\s*(시험|검증)\s*없이",
        r"기적의", r"신의\s*손", r"만병통치",
    ],
}

DISCLAIMER_TEXT = (
    "본 체크 결과는 의료법 제56조 및 의료광고 자율심의기준을 참고한 자동 스크리닝이며, "
    "실제 법적 판단을 대체하지 않습니다. 게재 전 반드시 대한의사협회 등 자율심의기구의 "
    "사전심의를 받으시기 바랍니다."
)


# =========================================================================
# 2. 세션 상태 초기화
# =========================================================================
def init_session_state():
    defaults = {
        "step": 1,
        "api_key": "",
        "model_name": MODEL_OPTIONS[0],
        "keywords_result": None,
        "selected_title": "",
        "custom_title": "",
        "structure_result": None,
        "final_content": "",
        "compliance_result": None,
        "history": [],
        # step1 입력값 보존
        "input_topic": "",
        "input_department": DEPARTMENTS[0],
        "input_department_custom": "",
        "input_purpose": list(PURPOSES.keys())[0],
        "input_tone": TONES[0],
        "input_region": "",
        "input_target_length": 2000,
        "input_hospital_name": "",
        "input_doctor_name": "",
        "input_address": "",
        "input_phone": "",
        "input_usp": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session_state()


# =========================================================================
# 3. Gemini 클라이언트 & 호출 함수
# =========================================================================
def get_client():
    api_key = st.session_state.api_key
    if not api_key:
        try:
            api_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            api_key = ""
    if not api_key:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception as e:
        st.error(f"Gemini 클라이언트 생성 실패: {e}")
        return None


def call_gemini_json(prompt: str, system_instruction: str = ""):
    """JSON 구조화 응답을 요구하는 호출"""
    client = get_client()
    if not client:
        st.error("⚠️ Gemini API 키가 설정되지 않았습니다. 사이드바에서 입력해주세요.")
        return None
    try:
        response = client.models.generate_content(
            model=st.session_state.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.85,
            ),
        )
        raw = response.text.strip()
        raw = re.sub(r"^```json\s*|\s*```$", "", raw.strip())
        return json.loads(raw)
    except json.JSONDecodeError as e:
        st.error(f"AI 응답을 JSON으로 해석하지 못했습니다: {e}")
        with st.expander("원본 응답 보기"):
            st.code(raw if "raw" in locals() else "응답 없음")
        return None
    except Exception as e:
        st.error(f"AI 호출 중 오류가 발생했습니다: {e}")
        return None


def call_gemini_text(prompt: str, system_instruction: str = ""):
    """자연어 텍스트 응답을 요구하는 호출"""
    client = get_client()
    if not client:
        st.error("⚠️ Gemini API 키가 설정되지 않았습니다. 사이드바에서 입력해주세요.")
        return None
    try:
        response = client.models.generate_content(
            model=st.session_state.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.75,
            ),
        )
        return response.text.strip()
    except Exception as e:
        st.error(f"AI 호출 중 오류가 발생했습니다: {e}")
        return None


# =========================================================================
# 4. 의료광고 컴플라이언스 체크 (룰베이스 + AI 이중 체크)
# =========================================================================
def check_compliance_rule_based(text: str):
    findings = []
    for category, patterns in PROHIBITED_PATTERNS.items():
        for pat in patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                snippet_start = max(0, m.start() - 15)
                snippet_end = min(len(text), m.end() + 15)
                findings.append({
                    "category": category,
                    "matched": m.group(),
                    "context": "..." + text[snippet_start:snippet_end] + "...",
                })
    return findings


def check_compliance_ai(text: str, department: str):
    system_instruction = (
        "당신은 대한민국 의료법 제56조(의료광고의 금지 등) 및 의료광고 자율심의기준에 정통한 "
        "의료광고 심의 전문가입니다. 주어진 블로그 본문을 검토하여 위반 소지가 있는 표현을 찾아내고, "
        "합법적인 대체 표현을 제안하세요. 과장·단정적 효과 표현, 비교 우위 표현, 환자 후기·체험담 "
        "오남용, 환자 유인·알선성 표현, 미승인 신의료기술 암시 등을 중점적으로 확인하세요. "
        "반드시 JSON 형식으로만 응답하세요."
    )
    prompt = f"""
다음은 '{department}' 진료과 병원 블로그 본문입니다. 의료광고법 위반 소지를 검토해주세요.

[본문]
{text}

다음 JSON 형식으로만 응답하세요:
{{
  "risk_level": "낮음|보통|높음",
  "issues": [
    {{"phrase": "문제 표현 원문", "reason": "위반 소지 이유 (관련 법조항 언급)", "suggestion": "대체 표현 제안"}}
  ],
  "overall_comment": "전반적인 총평 2~3문장"
}}
issues가 없으면 빈 배열로 응답하세요.
"""
    return call_gemini_json(prompt, system_instruction)


# =========================================================================
# 5. AI 생성 함수 (키워드/제목 → 구조 → 본문)
# =========================================================================
def generate_keywords_and_titles():
    dept = (
        st.session_state.input_department_custom
        if st.session_state.input_department == "기타(직접입력)"
        else st.session_state.input_department
    )
    region_line = f"- 지역: {st.session_state.input_region} (지역 SEO 키워드 포함)" if st.session_state.input_region else ""

    system_instruction = (
        "당신은 병원 블로그 SEO 전문가입니다. 네이버/구글 검색엔진 상위노출 로직을 분석하여 "
        "실제 환자들이 검색할 법한 자연스러운 키워드와 클릭을 유도하는 제목을 제안합니다. "
        "의료광고법상 과장·단정적 표현은 절대 사용하지 않습니다. 반드시 JSON 형식으로만 응답하세요."
    )
    prompt = f"""
아래 조건에 맞는 병원 블로그 글의 키워드와 제목 후보를 만들어주세요.

- 주제: {st.session_state.input_topic}
- 진료과: {dept}
{region_line}
- 글의 목적/분위기: {st.session_state.input_purpose} ({PURPOSES[st.session_state.input_purpose]})
- 톤앤매너: {st.session_state.input_tone}

다음 JSON 형식으로만 응답하세요:
{{
  "main_keyword": "핵심 대표 키워드 1개",
  "sub_keywords": ["서브 키워드 5개"],
  "related_keywords": ["연관 키워드 5개"],
  "titles": ["SEO에 강하고 클릭을 유도하는 제목 후보 3개 (의료광고법 준수, 과장 표현 금지)"]
}}
"""
    return call_gemini_json(prompt, system_instruction)


def generate_structure():
    kw = st.session_state.keywords_result
    title = st.session_state.selected_title
    dept = (
        st.session_state.input_department_custom
        if st.session_state.input_department == "기타(직접입력)"
        else st.session_state.input_department
    )
    system_instruction = (
        "당신은 병원 블로그 콘텐츠 기획 전문가입니다. 검색엔진 상위노출에 유리한 논리적 글 구조(H2 소제목 단위)를 "
        "설계합니다. 각 소제목은 핵심 내용 bullet 2~3개와 예상 글자 수를 포함합니다. "
        "의료 정보의 정확성과 의료광고법 준수를 최우선으로 합니다. 반드시 JSON 형식으로만 응답하세요."
    )
    prompt = f"""
아래 정보를 바탕으로 블로그 글의 목차(구조)를 설계해주세요.

- 제목: {title}
- 진료과: {dept}
- 핵심 키워드: {kw.get('main_keyword', '')}
- 서브 키워드: {', '.join(kw.get('sub_keywords', []))}
- 목표 전체 글자 수: 약 {st.session_state.input_target_length}자

다음 JSON 형식으로만 응답하세요 (H2 소제목 5~7개):
{{
  "sections": [
    {{
      "heading": "H2 소제목",
      "bullets": ["핵심 내용 bullet 1", "핵심 내용 bullet 2", "핵심 내용 bullet 3"],
      "keywords": ["이 섹션에 배치할 키워드 1~2개"],
      "estimated_chars": 300
    }}
  ]
}}
첫 섹션은 도입부(공감 유발+글의 핵심 요약 예고), 마지막 섹션은 병원 내원 유도 및 상담 안내(CTA)로 구성하세요.
CTA 섹션에서는 특정 병원명을 언급하지 말고 '가까운 병원 상담'처럼 일반적으로 표현하세요 (병원 정보는 이후 단계에서 사용자가 직접 삽입합니다).
"""
    return call_gemini_json(prompt, system_instruction)


def generate_full_body():
    structure = st.session_state.structure_result
    title = st.session_state.selected_title
    dept = (
        st.session_state.input_department_custom
        if st.session_state.input_department == "기타(직접입력)"
        else st.session_state.input_department
    )
    sections_text = "\n".join(
        f"- {s['heading']}: {', '.join(s['bullets'])} (키워드: {', '.join(s.get('keywords', []))}, 약 {s.get('estimated_chars', 300)}자)"
        for s in structure["sections"]
    )

    prohibited_summary = "; ".join(
        [f"[{cat.split(' (')[0]}]" for cat in PROHIBITED_PATTERNS.keys()]
    )

    system_instruction = (
        "당신은 대한민국 병원 블로그 전문 카피라이터입니다. 의학적으로 정확하고, 환자 눈높이에 맞춰 "
        "쉽고 신뢰감 있게 작성합니다. 의료법 제56조에 따라 치료효과를 보장하거나 단정하는 표현, "
        f"비교 우위 표현, 실제 환자 후기·전후사진 언급, 환자 유인성 할인/이벤트 표현({prohibited_summary} 등)은 "
        "절대 사용하지 않습니다. 실제 후기가 필요한 경우 '가상의 사례'임을 암시하는 자연스러운 표현으로 대체합니다."
    )
    prompt = f"""
아래 목차를 바탕으로 병원 블로그 본문 전체를 작성해주세요. 마크다운 형식(## 소제목)을 사용하세요.

- 제목: {title}
- 진료과: {dept}
- 톤앤매너: {st.session_state.input_tone}
- 목표 글자 수: 약 {st.session_state.input_target_length}자

[목차]
{sections_text}

작성 규칙:
1. 각 H2 소제목(##)마다 자연스러운 문단으로 작성 (bullet을 그대로 나열하지 말고 문장으로 풀어쓸 것)
2. 키워드는 자연스럽게 1~2회씩만 녹여 넣기 (키워드 반복 남용 금지)
3. 의학 정보는 일반적으로 통용되는 정확한 내용만 사용, 특정 시술명/약품명의 효과를 단정하지 말 것
4. 글 말미에는 "정확한 진단과 치료는 반드시 전문의와의 상담을 통해 결정하시기 바랍니다" 형태의 안내 문구 포함
5. 병원 상호명, 주소, 전화번호는 언급하지 말 것 (사용자가 별도로 삽입)
"""
    return call_gemini_text(prompt, system_instruction)


# =========================================================================
# 6. 사이드바
# =========================================================================
def render_sidebar():
    with st.sidebar:
        st.markdown("### ⚙️ AI 설정")
        st.session_state.api_key = st.text_input(
            "Gemini API 키", value=st.session_state.api_key, type="password",
            help="Streamlit Cloud 배포 시에는 Secrets에 GEMINI_API_KEY로 등록하면 이 입력은 생략 가능합니다.",
            key="widget_api_key",
        )
        st.session_state.model_name = st.selectbox(
            "모델 선택", MODEL_OPTIONS,
            index=MODEL_OPTIONS.index(st.session_state.model_name) if st.session_state.model_name in MODEL_OPTIONS else 0,
            help="모델별 가용 여부는 시기에 따라 달라질 수 있습니다. 오류 발생 시 다른 모델로 변경해보세요.",
            key="widget_model_name",
        )

        st.divider()
        st.markdown("### 📊 진행 단계")
        step_labels = ["① 주제/조건 입력", "② 키워드·제목", "③ 글 구조 설계", "④ 본문 작성·검수"]
        for i, label in enumerate(step_labels, start=1):
            if st.session_state.step > i:
                icon = "✅"
            elif st.session_state.step == i:
                icon = "▶️"
            else:
                icon = "⬜"
            st.markdown(f"{icon} {label}")

        st.divider()
        if st.button("🔄 처음부터 새로 시작", use_container_width=True):
            st.session_state.step = 1
            st.session_state.keywords_result = None
            st.session_state.selected_title = ""
            st.session_state.custom_title = ""
            st.session_state.structure_result = None
            st.session_state.final_content = ""
            st.session_state.compliance_result = None
            st.rerun()

        if st.session_state.history:
            st.divider()
            st.markdown(f"### 🗂️ 이번 세션 생성 기록 ({len(st.session_state.history)}건)")
            st.caption("※ 세션 임시 저장 - 브라우저를 새로고침하면 사라집니다.")
            for idx, item in enumerate(reversed(st.session_state.history)):
                with st.expander(f"{item['created_at']} · {item['title'][:25]}"):
                    st.caption(f"진료과: {item['department']} / {len(item['content'])}자")
                    st.download_button(
                        "다운로드 (.md)", data=item["content"],
                        file_name=f"blog_{item['created_at'].replace(':', '').replace(' ', '_')}.md",
                        mime="text/markdown", key=f"hist_dl_{idx}",
                    )


# =========================================================================
# 7. 단계별 화면
# =========================================================================
def render_step_header():
    st.title("🏥 병원 블로그 AI 자동 생성기")
    st.caption("황금 키워드 분석 → 제목 추천 → 구조 설계 → 본문 작성 → 의료광고법 자동 검수까지 한 번에")


def render_step1():
    st.subheader("① 어떤 주제로 글을 쓸까요?")

    st.session_state.input_topic = st.text_input(
        "글 주제 (예: 무릎 인공관절 수술 회복 기간, 겨울철 안구건조증 관리법)",
        value=st.session_state.input_topic, key="widget_topic",
    )

    col1, col2 = st.columns(2)
    with col1:
        st.session_state.input_department = st.selectbox(
            "진료과", DEPARTMENTS,
            index=DEPARTMENTS.index(st.session_state.input_department) if st.session_state.input_department in DEPARTMENTS else 0,
            key="widget_department",
        )
        if st.session_state.input_department == "기타(직접입력)":
            st.session_state.input_department_custom = st.text_input(
                "진료과 직접 입력", value=st.session_state.input_department_custom, key="widget_department_custom"
            )
    with col2:
        st.session_state.input_region = st.text_input(
            "지역 (선택 - 입력 시 지역 SEO 키워드 포함, 예: 대구 수성구)",
            value=st.session_state.input_region, key="widget_region",
        )

    st.markdown("**글의 목적·분위기**")
    st.session_state.input_purpose = st.radio(
        "목적", list(PURPOSES.keys()),
        index=list(PURPOSES.keys()).index(st.session_state.input_purpose),
        horizontal=True, label_visibility="collapsed", key="widget_purpose",
    )
    st.caption(PURPOSES[st.session_state.input_purpose])

    col3, col4 = st.columns(2)
    with col3:
        st.session_state.input_tone = st.selectbox(
            "톤앤매너", TONES, index=TONES.index(st.session_state.input_tone), key="widget_tone"
        )
    with col4:
        st.session_state.input_target_length = st.slider(
            "목표 글자 수", min_value=1000, max_value=4000, step=250,
            value=st.session_state.input_target_length, key="widget_target_length",
        )

    dept_check = (
        st.session_state.input_department_custom
        if st.session_state.input_department == "기타(직접입력)"
        else st.session_state.input_department
    )
    if dept_check in HIGH_SENSITIVITY_DEPTS:
        st.info(
            f"💡 **{dept_check}**는 의료광고 사전심의 민감 진료과입니다. 특히 전후사진, 비교 우위 표현, "
            "환자 후기 관련 문구에 유의해서 검수해드리겠습니다."
        )

    st.markdown("")
    if st.button("🔍 황금 키워드 찾기", type="primary", use_container_width=True, disabled=not st.session_state.input_topic.strip()):
        with st.spinner("검색엔진 상위노출 로직을 분석하여 키워드를 찾는 중..."):
            result = generate_keywords_and_titles()
        if result:
            st.session_state.keywords_result = result
            st.session_state.selected_title = result.get("titles", [""])[0]
            st.session_state.step = 2
            st.rerun()


def render_step2():
    st.subheader("② 키워드 분석 결과 · 제목 선택")
    kw = st.session_state.keywords_result

    st.markdown(f"**대표 키워드**  \n<span class='keyword-chip'>{kw.get('main_keyword','')}</span>", unsafe_allow_html=True)

    st.markdown("**서브 키워드**")
    st.markdown(
        " ".join(f"<span class='keyword-chip'>{k}</span>" for k in kw.get("sub_keywords", [])),
        unsafe_allow_html=True,
    )
    st.markdown("**연관 키워드**")
    st.markdown(
        " ".join(f"<span class='keyword-chip-sub'>{k}</span>" for k in kw.get("related_keywords", [])),
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("**제목 후보 (하나를 선택하세요)**")
    titles = kw.get("titles", [])
    choice = st.radio(
        "제목", titles, index=titles.index(st.session_state.selected_title) if st.session_state.selected_title in titles else 0,
        label_visibility="collapsed", key="widget_title_radio",
    )
    st.session_state.selected_title = choice

    custom = st.text_input("직접 수정하기 (선택)", value=st.session_state.selected_title, key="widget_title_custom")
    if custom.strip():
        st.session_state.selected_title = custom.strip()

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        if st.button("⬅️ 이전 단계", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
    with col_b:
        if st.button("🔄 키워드 다시 찾기", use_container_width=True):
            with st.spinner("다시 분석 중..."):
                result = generate_keywords_and_titles()
            if result:
                st.session_state.keywords_result = result
                st.session_state.selected_title = result.get("titles", [""])[0]
                st.rerun()
    with col_c:
        if st.button("📐 글 구조 설계하기", type="primary", use_container_width=True):
            with st.spinner("SEO에 유리한 글 구조를 설계하는 중..."):
                result = generate_structure()
            if result:
                st.session_state.structure_result = result
                st.session_state.step = 3
                st.rerun()


def render_step3():
    st.subheader("③ 글 구조 설계 결과")
    st.caption("각 소제목의 핵심 내용을 확인하고, 필요하면 표를 직접 수정하세요.")

    structure = st.session_state.structure_result
    total_chars = sum(s.get("estimated_chars", 0) for s in structure["sections"])
    st.caption(f"예상 총 분량: 약 {total_chars:,}자 ({len(structure['sections'])}개 섹션)")

    for i, section in enumerate(structure["sections"]):
        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                new_heading = st.text_input(f"H2 소제목 {i+1}", value=section["heading"], key=f"heading_{i}")
            with col2:
                new_chars = st.number_input("예상 글자수", value=section.get("estimated_chars", 300), step=50, key=f"chars_{i}")
            bullets_text = st.text_area(
                "핵심 내용 (한 줄에 하나씩)", value="\n".join(section["bullets"]), key=f"bullets_{i}", height=90,
            )
            structure["sections"][i]["heading"] = new_heading
            structure["sections"][i]["estimated_chars"] = new_chars
            structure["sections"][i]["bullets"] = [b.strip() for b in bullets_text.split("\n") if b.strip()]

    st.session_state.structure_result = structure

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        if st.button("⬅️ 이전 단계", use_container_width=True, key="s3_back"):
            st.session_state.step = 2
            st.rerun()
    with col_b:
        if st.button("🔄 구조 다시 설계", use_container_width=True, key="s3_retry"):
            with st.spinner("다시 설계 중..."):
                result = generate_structure()
            if result:
                st.session_state.structure_result = result
                st.rerun()
    with col_c:
        if st.button("✍️ 본문 자동 작성하기", type="primary", use_container_width=True, key="s3_next"):
            with st.spinner("본문을 작성하는 중... (약 30초 소요)"):
                body = generate_full_body()
            if body:
                st.session_state.final_content = body
                st.session_state.compliance_result = None
                st.session_state.step = 4
                st.rerun()


def render_step4():
    st.subheader("④ 본문 작성 완료")
    content = st.session_state.final_content
    st.caption(f"{len(content):,}자 · SEO 구조 반영 완료")

    with st.container(border=True):
        st.markdown(f"**블로그 제목**")
        st.markdown(f"### {st.session_state.selected_title}")

    edited = st.text_area("본문 (직접 수정 가능)", value=content, height=500, key="widget_final_content")
    st.session_state.final_content = edited

    col_a, col_b, col_c, col_d = st.columns([1, 1, 1, 1])
    with col_a:
        if st.button("⬅️ 이전 단계", use_container_width=True):
            st.session_state.step = 3
            st.rerun()
    with col_b:
        if st.button("🔄 본문 다시 작성", use_container_width=True):
            with st.spinner("다시 작성 중..."):
                body = generate_full_body()
            if body:
                st.session_state.final_content = body
                st.session_state.compliance_result = None
                st.rerun()
    with col_c:
        st.download_button(
            "⬇️ 다운로드 (.md)", data=edited,
            file_name=f"{st.session_state.selected_title[:20]}.md", mime="text/markdown",
            use_container_width=True,
        )
    with col_d:
        if st.button("💾 이번 세션에 저장", use_container_width=True):
            dept_val = (
                st.session_state.input_department_custom
                if st.session_state.input_department == "기타(직접입력)"
                else st.session_state.input_department
            )
            st.session_state.history.append({
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "title": st.session_state.selected_title,
                "department": dept_val,
                "content": edited,
            })
            st.success("이번 세션 기록에 저장했습니다. (사이드바에서 확인)")

    render_copy_button(edited)

    st.divider()
    render_compliance_section(edited)


def render_copy_button(text: str):
    """클립보드 복사 버튼 (JS clipboard API 사용)"""
    import streamlit.components.v1 as components
    safe_text = json.dumps(text)
    components.html(
        f"""
        <button id="copyBtn" style="
            width:100%; padding:10px; border-radius:8px; border:1px solid #1e6f5c;
            background-color:#1e6f5c; color:white; font-size:14px; cursor:pointer; margin-top:4px;">
            📋 본문 전체 복사하기
        </button>
        <script>
        const btn = document.getElementById("copyBtn");
        btn.addEventListener("click", function() {{
            navigator.clipboard.writeText({safe_text}).then(function() {{
                btn.innerText = "✅ 복사 완료!";
                setTimeout(function() {{ btn.innerText = "📋 본문 전체 복사하기"; }}, 1500);
            }});
        }});
        </script>
        """,
        height=55,
    )


def render_compliance_section(text: str):
    st.subheader("🛡️ 의료광고법 위반 소지 자동 검수")
    st.caption("룰베이스 1차 체크 + AI 정밀 검토(2차) 순으로 진행됩니다.")

    if st.button("🔍 검수 시작하기", type="primary"):
        rule_findings = check_compliance_rule_based(text)
        dept_val = (
            st.session_state.input_department_custom
            if st.session_state.input_department == "기타(직접입력)"
            else st.session_state.input_department
        )
        with st.spinner("AI가 정밀 검토하는 중..."):
            ai_result = check_compliance_ai(text, dept_val)
        st.session_state.compliance_result = {"rule": rule_findings, "ai": ai_result}
        st.rerun()

    result = st.session_state.compliance_result
    if result is None:
        return

    rule_findings = result["rule"]
    ai_result = result["ai"]

    st.markdown("#### 1차: 금지표현 룰베이스 체크")
    if not rule_findings:
        st.markdown("<div class='ok-box'>✅ 사전 등록된 금지표현 패턴이 발견되지 않았습니다.</div>", unsafe_allow_html=True)
    else:
        for f in rule_findings:
            st.markdown(
                f"<div class='warn-box'>⚠️ <b>{f['category']}</b><br>"
                f"발견된 표현: <code>{f['matched']}</code><br>"
                f"문맥: {f['context']}</div>",
                unsafe_allow_html=True,
            )

    st.markdown("#### 2차: AI 정밀 검토")
    if ai_result is None:
        st.warning("AI 검토 결과를 가져오지 못했습니다. 다시 시도해주세요.")
    else:
        risk = ai_result.get("risk_level", "알 수 없음")
        risk_color = {"낮음": "🟢", "보통": "🟡", "높음": "🔴"}.get(risk, "⚪")
        st.markdown(f"**종합 위험도: {risk_color} {risk}**")
        st.write(ai_result.get("overall_comment", ""))

        issues = ai_result.get("issues", [])
        if not issues:
            st.markdown("<div class='ok-box'>✅ AI 검토에서도 특이사항이 발견되지 않았습니다.</div>", unsafe_allow_html=True)
        else:
            for issue in issues:
                st.markdown(
                    f"<div class='warn-box'>⚠️ <b>{issue.get('phrase','')}</b><br>"
                    f"사유: {issue.get('reason','')}<br>"
                    f"제안 표현: <i>{issue.get('suggestion','')}</i></div>",
                    unsafe_allow_html=True,
                )

    st.caption(f"⚖️ {DISCLAIMER_TEXT}")


# =========================================================================
# 8. 메인 실행
# =========================================================================
def main():
    render_sidebar()
    render_step_header()
    st.divider()

    if not st.session_state.api_key:
        try:
            has_secret = bool(st.secrets.get("GEMINI_API_KEY", ""))
        except Exception:
            has_secret = False
        if not has_secret:
            st.warning("👈 먼저 사이드바에서 Gemini API 키를 입력해주세요.")

    step = st.session_state.step
    if step == 1:
        render_step1()
    elif step == 2:
        render_step2()
    elif step == 3:
        render_step3()
    elif step == 4:
        render_step4()


if __name__ == "__main__":
    main()
