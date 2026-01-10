"""
중소기업 업무 자동화 RAG 솔루션 - WorkAnswer
(최종 마스터 코드: 기업 전문가 답변 품질 최적화)
"""
import os
import json
import tempfile
import uuid
import re
import io
import csv
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv
from pathlib import Path

# ==================== [1. 시스템 인증 및 라이브러리 설정] ====================
if "gcp_service_account" in st.secrets:
    try:
        service_account_info = dict(st.secrets["gcp_service_account"])
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as temp:
            json.dump(service_account_info, temp)
            temp_path = temp.name
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
    except Exception as e: st.error(f"인증 파일 생성 오류: {e}")

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
    import google.auth
except ImportError: st.error("Google API 라이브러리 누락"); st.stop()

try:
    from rag_module import init_vector_store, sync_drive_to_db, search_similar_documents, get_indexed_documents, reset_database
except Exception as e: st.error(f"🚨 rag_module.py 로딩 실패! 원인: {e}"); st.stop()

# 🌟🌟🌟 기본 동의어 사전 (최종 확인 및 복구) 🌟🌟🌟
DEFAULT_SYNONYMS = {
    "심사료": ["게재료", "투고료", "논문 게재", "학회비", "논문 심사료"],
    "인건비": ["노무비", "인력운영비", "학생 인건비"],
    "물리학": ["새물리", "물리", "KPS"],
    "투고": ["제출", "접수"],
    "인용": ["참고문헌", "레퍼런스", "reference", "citation", "출처", "참조", "문헌", "bibliography"],
    "참고문헌": ["인용", "레퍼런스", "reference", "출처", "참조문헌", "bibliography", "citation"],
    "출처": ["인용", "참고문헌", "reference", "출처스타일", "인용양식", "참조", "citation"],
    "레퍼런스": ["reference", "참고문헌", "인용", "출처", "참조문헌"],
    "양식": ["형식", "포맷", "format", "스타일", "style", "template"]
}

try:
    secrets_dict = dict(st.secrets)
    if "GOOGLE_API_KEY" in secrets_dict:
        os.environ["GOOGLE_API_KEY"] = secrets_dict["GOOGLE_API_KEY"]
        os.environ["SUPABASE_URL"] = secrets_dict["SUPABASE_URL"]
        os.environ["SUPABASE_KEY"] = secrets_dict["SUPABASE_KEY"]
        os.environ["GOOGLE_DRIVE_FOLDER_ID"] = secrets_dict.get("GOOGLE_DRIVE_FOLDER_ID", "")
except: pass

st.set_page_config(page_title="WorkAnswer", layout="wide", initial_sidebar_state="expanded")

# ==================== [2. 세션 초기화] ====================
if 'supabase_client' not in st.session_state: st.session_state.supabase_client = None
if 'embeddings' not in st.session_state: st.session_state.embeddings = None
if 'llm' not in st.session_state: st.session_state.llm = None
if 'admin_mode' not in st.session_state: st.session_state.admin_mode = False
if 'system_initialized' not in st.session_state: st.session_state.system_initialized = False
if 'dynamic_synonyms' not in st.session_state: st.session_state.dynamic_synonyms = DEFAULT_SYNONYMS.copy()
if 'last_unanswered_query' not in st.session_state: st.session_state.last_unanswered_query = None
if 'chat_sessions' not in st.session_state: st.session_state.chat_sessions = {}
if 'current_session_id' not in st.session_state:
    first_session_id = str(uuid.uuid4())
    st.session_state.chat_sessions[first_session_id] = {'messages': [], 'created_at': datetime.now(), 'title': '새로운 대화'}
    st.session_state.current_session_id = first_session_id

if not st.session_state.system_initialized:
    try:
        vector_store = init_vector_store()
        st.session_state.supabase_client = vector_store['supabase_client']
        st.session_state.embeddings = vector_store['embeddings']
        google_api_key = os.getenv("GOOGLE_API_KEY")
        try:
            import google.generativeai as genai
            genai.configure(api_key=google_api_key)
            st.session_state.llm = genai.GenerativeModel('models/gemini-2.5-flash')
        except: st.session_state.llm = None
        st.session_state.system_initialized = True
    except: st.session_state.system_initialized = False

# ==================== [3. CSS 스타일링 (UI 유지)] ====================
st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; }
    .block-container { max-width: 800px !important; padding-top: 2rem; margin: 0 auto; }
    [data-testid="stChatMessage"] { padding: 1.5rem; border-radius: 15px; margin-bottom: 0.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    [data-testid="stChatMessage"][data-testid-user-avatar="true"] { background-color: #E3F2FD; }
    [data-testid="stChatMessage"][data-testid-user-avatar="false"] { background-color: #FFFFFF; border: 1px solid #e0e0e0; }
    [data-testid="stBottom"] > div, [data-testid="stChatInput"] { max-width: 800px !important; margin: 0 auto !important; }
    [data-testid="stChatInput"] { position: relative !important; }
    [data-testid="stChatInput"]::after {
        content: '⚠️ AI 답변은 부정확할 수 있으며, 중요 사안은 반드시 원문 규정을 확인하시기 바랍니다.';
        display: block; text-align: center; font-size: 12px; color: #888; 
        position: absolute; bottom: -25px; left: 50%; transform: translateX(-50%);
        width: 100%; max-width: 800px; visibility: visible;
    }
</style>
""", unsafe_allow_html=True)

# ==================== [4. 유틸리티 함수] ====================
def format_docs(docs):
    return "\n\n".join([f"[문서 {i}] (출처: {doc.metadata.get('source', 'Unknown')})\n{doc.page_content}" for i, doc in enumerate(docs, 1)])

def get_session_title(messages):
    return messages[0][0][:30] + "..." if messages else "새로운 대화"

def get_date_group(created_at):
    diff = (datetime.now() - created_at).days
    return "오늘" if diff == 0 else "어제" if diff == 1 else "이전"

def load_synonyms_from_drive(folder_id):
    try:
        creds, _ = google.auth.default()
        service = build('drive', 'v3', credentials=creds)
        results = service.files().list(q=f"name='dictionary.csv' and '{folder_id}' in parents and trashed=false", fields="files(id)").execute()
        files = results.get('files', [])
        if not files: return None, "사전 파일 없음"
        content = service.files().get_media(fileId=files[0]['id']).execute()
        try: decoded = content.decode('utf-8')
        except: decoded = content.decode('cp949')
        new_synonyms = {}
        for row in csv.reader(io.StringIO(decoded)):
            if len(row) >= 2:
                new_synonyms[row[0].strip()] = [v.strip() for v in row[1].replace('|', ',').split(',') if v.strip()]
        return new_synonyms, f"{len(new_synonyms)}개 키워드 로드 성공"
    except Exception as e: return None, str(e)

def expand_query(original_query, llm):
    """
    AI 기반 쿼리 확장 함수 (하이브리드 방식)

    개선사항:
    - 사전 기반 확장 (정확도 우선)
    - AI 기반 의미적 확장 (커버리지 확대)
    - 완전 단어 매칭으로 노이즈 감소
    """
    final = [original_query]

    # 1. 사전 기반 확장 (완전 단어 매칭)
    for k, v in st.session_state.dynamic_synonyms.items():
        # 순방향: 주요 용어가 쿼리에 있으면 동의어 추가
        if re.search(rf'\b{re.escape(k)}\b', original_query):
            final.extend(v)
        # 역방향: 동의어가 쿼리에 있으면 주요 용어 추가
        elif any(re.search(rf'\b{re.escape(word)}\b', original_query) for word in v):
            final.append(k)

    # 2. AI 기반 의미 확장 (제한적으로 활성화)
    if llm:
        try:
            prompt = f"""다음 검색어와 의미적으로 관련된 학술 용어나 동의어를 3개 이내로 제시하세요.
규칙:
- 논문 작성 및 학술 규정과 관련된 용어만 제시
- 일반적이고 명확한 용어만 사용 (모호한 표현 금지)
- 각 용어는 쉼표로 구분하여 한 줄로 출력
- 원래 검색어와 중복되는 내용은 제외

검색어: "{original_query}"

관련 용어 (3개 이내):"""

            response = llm.generate_content(prompt)
            if response and response.text:
                ai_terms = [term.strip() for term in response.text.strip().split(',') if term.strip()]
                # AI 제안 용어 중 원본과 다르고 짧은 것만 추가 (최대 3개)
                ai_terms = [t for t in ai_terms if t != original_query and len(t) <= 20][:3]
                final.extend(ai_terms)
        except Exception as e:
            print(f"AI 쿼리 확장 실패 (계속 진행): {e}")
            # 실패해도 사전 기반 확장 결과는 유지

    # 중복 제거하되 원본 쿼리는 첫 번째로 유지
    unique_terms = [original_query] + [term for term in final[1:] if term not in final[:final.index(term) + 1]]
    return unique_terms[:10]  # 최대 10개로 확대 (AI 확장 고려)

# ==================== [5. 사이드바] ====================
with st.sidebar:
    if st.button("+ 새 채팅", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.chat_sessions[new_id] = {'messages': [], 'created_at': datetime.now(), 'title': '새로운 대화'}
        st.session_state.current_session_id = new_id
        st.session_state.last_unanswered_query = None
        st.rerun()

    st.divider()
    
    sessions_by_date = {"오늘": [], "어제": [], "이전": []}
    for sid, sdata in st.session_state.chat_sessions.items():
        dg = get_date_group(sdata['created_at'])
        if dg in sessions_by_date: sessions_by_date[dg].append((sid, sdata))
    
    for gname in ["오늘", "어제", "이전"]:
        if sessions_by_date[gname]:
            st.caption(gname)
            for sid, sdata in sorted(sessions_by_date[gname], key=lambda x: x[1]['created_at'], reverse=True):
                title = get_session_title(sdata['messages'])
                btn_type = "primary" if sid == st.session_state.current_session_id else "secondary"
                if st.button(title, key=sid, use_container_width=True, type=btn_type):
                    st.session_state.current_session_id = sid
                    st.session_state.last_unanswered_query = None
                    st.rerun()

    st.divider()
    with st.expander("설정 (관리자)"):
        pw = st.text_input("비밀번호", type="password")
        if pw == st.secrets.get("ADMIN_PASSWORD", "admin"):
            st.session_state.admin_mode = True
        
        if st.session_state.admin_mode:
            st.success("관리자 접속")
            fid = st.text_input("폴더 ID", value=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""))
            
            if st.button("파일 목록 확인"):
                try:
                    creds, _ = google.auth.default()
                    svc = build('drive', 'v3', credentials=creds)
                    fs = svc.files().list(q=f"'{fid}' in parents and trashed=false").execute().get('files', [])
                    st.info(f"{len(fs)}개 파일 감지")
                    for f in fs: st.text(f"- {f['name']}")
                except Exception as e: st.error(f"에러: {e}")

            c1, c2 = st.columns(2)
            force_update = st.checkbox("전체 재색인 (느림, 안전)", value=False, help="체크 해제 시: 변경된 파일만 증분 동기화 (빠름)")

            if c1.button("문서 동기화"):
                try:
                    cnt = sync_drive_to_db(fid, st.session_state.supabase_client, force_update=force_update)
                    st.success(f"{cnt}개 처리 완료")
                except Exception as e: st.error(f"실패: {e}")

            if c2.button("사전 동기화"):
                d, m = load_synonyms_from_drive(fid)
                if d: st.session_state.dynamic_synonyms = d; st.success(m)
                else: st.warning(m)

            # 색인된 문서 목록 조회
            if st.button("색인된 문서 확인"):
                try:
                    docs = get_indexed_documents(st.session_state.supabase_client)
                    st.info(f"📚 총 {len(docs)}개 파일 색인됨")
                    for doc in sorted(docs):
                        st.text(f"- {doc}")
                except Exception as e:
                    st.error(f"조회 실패: {e}")

            # 검색 품질 테스트 도구
            with st.expander("🔍 검색 품질 테스트"):
                test_query = st.text_input("테스트 쿼리", "인건비 지급 규정")
                if st.button("검색 테스트 실행"):
                    try:
                        docs, infos = search_similar_documents(
                            test_query,
                            st.session_state.supabase_client,
                            st.session_state.embeddings,
                            top_k=20
                        )
                        st.write(f"### 검색 결과 ({len(infos)}개)")
                        for i, info in enumerate(infos, 1):
                            score = info['score']
                            if score > 0.7:
                                emoji = "🟢"
                            elif score > 0.5:
                                emoji = "🟡"
                            else:
                                emoji = "🔴"
                            st.write(f"{emoji} {i}. {info['filename']} - **{score:.3f}** (섹션: {info.get('section', 'N/A')})")
                    except Exception as e:
                        st.error(f"테스트 실패: {e}")

            st.divider()
            if st.button("🗑️ DB 전체 삭제", type="primary"):
                with st.spinner("DB 삭제 중..."):
                    try:
                        success = reset_database(st.session_state.supabase_client)
                        if success:
                            st.success("✅ DB 삭제 완료!")
                            st.warning("⚠️ 재색인을 위해 '문서 동기화' 버튼을 클릭하세요")
                        else:
                            st.error("❌ DB 삭제 실패. 로그를 확인하세요.")
                    except Exception as e:
                        st.error(f"❌ DB 삭제 오류: {e}")

# ==================== [6. 메인 화면 로직] ====================
curr_session = st.session_state.chat_sessions[st.session_state.current_session_id]
curr_messages = curr_session['messages']

# (1) 첫 화면 (중앙 로고)
if not curr_messages:
    st.markdown("<div style='height: 30vh'></div>", unsafe_allow_html=True)
    st.markdown("""
    <div style='text-align: center;'>
        <h1 style='color: #2c3e50; font-size: 3rem; margin-bottom: 10px;'>WorkAnswer 🤖</h1>
        <p style='color: #666; font-size: 1.1rem; margin-bottom: 30px;'>
            사내 규정, 매뉴얼, 보고서 양식 등<br>
            업무에 필요한 모든 것을 물어보세요.
        </p>
    </div>
    """, unsafe_allow_html=True)

# (2) 대화 출력
else:
    for q, a in curr_messages:
        st.chat_message("user").write(q)
        with st.chat_message("assistant"):
            if "===DETAIL_START===" in a:
                # [핵심 결론] 섹션 출력
                parts = a.split("===DETAIL_START===")
                st.write(parts[0].strip())
                
                # [상세 규정 해설] 섹션 출력 (Expander 내부)
                if len(parts) > 1:
                    detail_part = parts[1].split("===DOCS:")[0]
                    with st.expander("상세 내용 보기"):
                        st.markdown(detail_part.strip())
            
            elif "[NO_CONTENT]" in a:
                st.write("문서 내용을 분석했으나, 질문에 대한 정확한 답변을 찾을 수 없습니다.")
            else:
                st.write(a)

# (3) 일반 지식 검색 버튼 표시
if st.session_state.last_unanswered_query:
    st.markdown("---")
    st.warning(f"'{st.session_state.last_unanswered_query}'에 대한 정보가 사내 문서에 없습니다.")
    
    st.container()
    if st.button("🌐 일반 지식(Gemini)으로 검색", use_container_width=True, type="primary", key="general_search_btn"):
        with st.spinner("외부 지식 검색 중..."):
            try:
                query = st.session_state.last_unanswered_query
                prompt = f"질문: {query}\n\n너는 유능한 AI 비서다. 위 질문에 대해 너의 일반적인 지식을 바탕으로 정중하고 전문적으로 답변해라."
                
                if st.session_state.llm:
                    res = st.session_state.llm.generate_content(prompt)
                    ans = f"[일반 지식 답변]\n\n{res.text}"
                else: ans = "AI 모델 연결 실패"
                
                curr_messages.append((query, ans))
                st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                st.session_state.last_unanswered_query = None
                st.rerun()
            except Exception as e: st.error(f"오류: {e}")

# (4) 입력창 및 검색 프로세스
if query := st.chat_input("질문을 입력하세요..."):
    st.session_state.last_unanswered_query = None
    st.chat_message("user").write(query)
    
    with st.chat_message("assistant"):
        with st.spinner("분석 중..."):
            try:
                search_queries = expand_query(query, st.session_state.llm)
                st.caption(f"💡 확장 키워드 ({len(search_queries)}개): {', '.join(search_queries)}")

                all_docs, all_infos, seen_hashes = [], [], set()

                # 확장된 쿼리로 검색 (가중치 없음 - 순수 유사도 사용)
                for q in search_queries:
                    if st.session_state.supabase_client:
                        docs, infos = search_similar_documents(
                            q,
                            st.session_state.supabase_client,
                            st.session_state.embeddings,
                            top_k=15,  # 10 → 15 (다양성 필터링 대비)
                            dynamic_threshold=True
                        )

                        for d, i in zip(docs, infos):
                            normalized = re.sub(r'\s+', '', d.page_content)
                            content_hash = hash(normalized)

                            if content_hash not in seen_hashes:
                                seen_hashes.add(content_hash)
                                all_docs.append(d)
                                all_infos.append(i)  # DB 점수 그대로 사용

                # 점수 기준 정렬
                sorted_results = sorted(zip(all_docs, all_infos), key=lambda x: x[1]['score'], reverse=True)

                # 다양성 확보: 파일별 최대 3개 청크로 제한
                MAX_CHUNKS_PER_SOURCE = 3
                source_counts = {}
                combined = []
                for doc, info in sorted_results:
                    source = info.get('filename', 'Unknown')
                    current_count = source_counts.get(source, 0)

                    if current_count >= MAX_CHUNKS_PER_SOURCE:
                        continue  # 이미 이 문서에서 3개를 가져왔으면 스킵

                    source_counts[source] = current_count + 1
                    combined.append((doc, info))

                    if len(combined) >= 15:  # 총 15개까지
                        break

                # 검색 결과 통계 표시
                if combined:
                    avg_score = sum(x[1]['score'] for x in combined) / len(combined)
                    st.caption(f"📊 검색 결과: {len(combined)}개 문서, 평균 관련도: {avg_score:.2f}")
                
                # 결과 없음 처리 (검색 결과 0건)
                if not combined:
                    msg = "죄송합니다. 관련 사내 문서를 찾을 수 없습니다."
                    st.write(msg)
                    curr_messages.append((query, msg))
                    st.session_state.last_unanswered_query = query # 버튼 활성화 트리거
                    st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                    st.rerun()
                else:
                    context_text = format_docs([x[0] for x in combined])
                    
                    # 🌟🌟🌟 [프롬프트 최종 마스터] - 소제목 서식 및 다수 출처 통합 반영 🌟🌟🌟
                    # 참고 문서 목록 생성 (출처 명시를 위해 사용) - 안전한 메타데이터 추출
                    try:
                        source_list = []
                        for x in combined:
                            if x and len(x) > 0 and hasattr(x[0], 'metadata'):
                                source = x[0].metadata.get('source', '문서')
                                if source not in source_list:
                                    source_list.append(source)
                        main_source = "여러 참고 문서" if len(source_list) > 1 else (source_list[0] if source_list else "문서")
                    except Exception as e:
                        st.warning(f"출처 추출 오류: {e}")
                        main_source = "문서"
                    
                    prompt = f"""
                    너는 **{main_source}**에 근거하여 답변하는 유능한 사내 규정 전문가이다. 
                    아래 [Context]를 바탕으로 직원의 질문에 정중하고 명확하게 답변해라.
                    
                    [Context]:
                    {context_text}
                    
                    [지침]
                    1. **존칭/서두 금지:** '존경하는 직원 여러분께,' '안녕하세요,' 등의 불필요한 서두나 존칭을 절대 사용하지 마라. 답변은 중립적이고 건조한 전문가의 어조를 유지해라.
                    2. **내용의 완결성 및 전문성 (최우선):** Context의 내용을 절대 생략하지 말고, 구체적인 수치, 조건, 예외사항을 빠짐없이 포함하여 전문적으로 상세하게 작성해라. **답변의 주체가 {main_source}에 따른 것임을 명확히 언급**해라.
                    3. **다수 출처 통합 (필수):** Context에 여러 문서가 혼합되어 있다면, **[상세 규정 해설]** 섹션에서 내용이 섞이지 않도록 **출처별로 명확히 구분**하여 설명해라. (예: '**[규정 A 기반 해설]**'과 같이 볼드체 헤더 사용)
                    4. **[핵심 결론] 섹션 형식 (강제):** - **반드시** '**[핵심 결론]**'으로 시작하고, 글머리 기호(- )와 **명사형 종결**의 개조식 문장으로만 작성해라.
                    5. **[상세 규정 해설] 섹션 형식:**
                       - 2, 3번 지침을 따라 Context의 내용을 상세하고 충분하게 작성하여 **핵심 결론보다 훨씬 길어야 한다.**
                       - **서식:** 내용 구조화를 위해 **소제목은 일반 폰트 크기의 볼드체(`**소제목**`)**만 사용하고, 문단 간 빈 줄을 사용해라. 중요한 키워드는 **볼드체**로 강조해라. 표 데이터는 **마크다운 표**로 정리해라.
                    6. 답이 없으면 `[NO_CONTENT]` 라고만 써라.
                    
                    질문: {query}
                    
                    답변형식:
                    [핵심 결론]
                    - 결론 1
                    - 결론 2
                    ===DETAIL_START===
                    **상세 규정 해설 소제목 (예: 적용 범위 및 조건)**
                    내용 상세 기술...
                    (반드시 빈 줄)
                    **다음 소제목 (예: 유의사항)**
                    내용 상세 기술...
                    ===DOCS: 참고한 문서 번호===
                    """
                    
                    if st.session_state.llm:
                        res = st.session_state.llm.generate_content(prompt)
                        ans = res.text.strip()
                        
                        if "[NO_CONTENT]" in ans:
                            msg = "문서 내용을 분석했으나, 질문에 대한 정확한 답변을 찾을 수 없습니다."
                            st.write(msg)
                            curr_messages.append((query, msg))
                            st.session_state.last_unanswered_query = query 
                            st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                            st.rerun()
                        else:
                            if "===DETAIL_START===" in ans:
                                parts = ans.split("===DETAIL_START===")
                                st.write(parts[0].strip())
                                with st.expander("상세 내용 보기"):
                                    detail_content = parts[1].split("===DOCS:")[0].strip()
                                    st.markdown(detail_content)
                            else:
                                st.write(ans)
                            
                            # 원문 상세 보기 (실제 답변 생성에 사용된 문서만 표시)
                            st.markdown("---")
                            st.caption("🔍 참고 문서 (답변 생성에 실제 사용된 청크)")

                            # combined 리스트가 이미 답변 생성에 사용된 청크들임
                            # 상위 5개만 표시
                            used_docs = combined[:5]

                            # 키워드 매칭 여부 시각화
                            for i, (doc, info) in enumerate(used_docs, 1):
                                keyword_score = info.get('keyword_score', 0)
                                icon = "🎯" if keyword_score > 0.3 else "📄"

                                with st.expander(f"{icon} {i}. {info['filename']} (관련도: {info['score']:.2f})"):
                                    st.info("💡 답변 생성에 사용된 청크 원문:")
                                    st.text(info.get('content', '내용 없음'))
                                    if keyword_score > 0:
                                        st.caption(f"🎯 키워드 매칭 점수: {keyword_score:.3f}")

                            curr_messages.append((query, ans))
                            st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                    else:
                        st.error("AI 모델 연결 실패")
            except Exception as e:
                st.error(f"오류: {e}")