"""
중소기업 업무 자동화 RAG 솔루션 - WorkAnswer
(최종 수정: 버튼 출력 방식, NO_CONTENT 오류 처리 로직 강화)
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

DEFAULT_SYNONYMS = {"심사료": ["게재료", "투고료", "논문 게재", "학회비"]}

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

# ==================== [3. CSS 스타일링] ====================
st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; }
    .block-container { max-width: 800px !important; padding-top: 2rem; margin: 0 auto; }
    [data-testid="stChatMessage"] { padding: 1.5rem; border-radius: 15px; margin-bottom: 0.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    [data-testid="stChatMessage"][data-testid-user-avatar="true"] { background-color: #E3F2FD; }
    [data-testid="stChatMessage"][data-testid-user-avatar="false"] { background-color: #FFFFFF; border: 1px solid #e0e0e0; }
    [data-testid="stBottom"] > div, [data-testid="stChatInput"] { max-width: 800px !important; margin: 0 auto !important; }
    [data-testid="stChatInput"]::after {
        content: '⚠️ AI 답변은 부정확할 수 있으며, 중요 사안은 반드시 원문 규정을 확인하시기 바랍니다.';
        display: block; text-align: center; font-size: 12px; color: #888; margin-top: 10px; margin-bottom: 20px;
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
    final = [original_query]
    for k, v in st.session_state.dynamic_synonyms.items():
        if k in original_query: final.extend(v)
    try:
        if llm:
            prompt = f"질문 '{original_query}'의 검색 키워드 2개 추천 (단어만, 쉼표로 구분)"
            res = llm.generate_content(prompt)
            final.extend([k.strip() for k in res.text.split(',')])
    except: pass
    return list(set(final))

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
            if c1.button("문서 동기화"):
                try:
                    cnt = sync_drive_to_db(fid, st.session_state.supabase_client)
                    st.success(f"{cnt}개 완료")
                except Exception as e: st.error(f"실패: {e}")
            if c2.button("사전 동기화"):
                d, m = load_synonyms_from_drive(fid)
                if d: st.session_state.dynamic_synonyms = d; st.success(m)
                else: st.warning(m)
            if st.button("DB 삭제", type="primary"):
                if reset_database(st.session_state.supabase_client): st.success("삭제 완료")

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
                parts = a.split("===DETAIL_START===")
                st.write(parts[0].strip())
                if len(parts) > 1:
                    detail_part = parts[1].split("===DOCS:")[0]
                    with st.expander("상세 내용 보기"):
                        st.markdown(detail_part.strip())
            # [수정] NO_CONTENT가 그대로 노출되는 것을 방지하기 위해 일반 텍스트 출력 전에 필터링합니다.
            elif "[NO_CONTENT]" in a:
                st.write("문서 내용을 분석했으나, 질문에 대한 정확한 답변을 찾을 수 없습니다.")
            else:
                st.write(a)

# (3) [일반 지식 검색 복구 및 버튼 출력 방식 수정] 결과 없음 시 버튼 표시
if st.session_state.last_unanswered_query:
    st.markdown("---")
    st.warning(f"'{st.session_state.last_unanswered_query}'에 대한 정보가 사내 문서에 없습니다.")
    
    # 🌟 버튼 출력을 위한 새로운 컨테이너 생성 및 한 줄 출력 강제
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
                st.caption(f"💡 키워드: {', '.join(search_queries)}")
                
                all_docs, all_infos, seen = [], [], set()
                
                for q in search_queries:
                    if st.session_state.supabase_client:
                        docs, infos = search_similar_documents(q, st.session_state.supabase_client, st.session_state.embeddings)
                        for d, i in zip(docs, infos):
                            if d.page_content not in seen:
                                seen.add(d.page_content)
                                all_docs.append(d)
                                all_infos.append(i)
                
                combined = sorted(zip(all_docs, all_infos), key=lambda x: x[1]['score'], reverse=True)[:15]
                
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
                    
                    prompt = f"""
                    너는 사내 규정 전문가다. [Context]를 바탕으로 답변해라.
                    
                    [Context]:
                    {context_text}
                    
                    질문: {query}
                    
                    [지침]
                    1. 내용의 완결성: 내용을 생략하지 말고 구체적 수치/조건을 포함해라.
                    2. 가독성: **### 소제목**과 **문단 간 빈 줄**을 사용해라.
                    3. 표: 마크다운 표(Table)로 변환해라.
                    4. 답이 없으면 `[NO_CONTENT]` 라고만 써라.
                    
                    답변형식:
                    [핵심 요약]
                    - 요약1
                    ===DETAIL_START===
                    ### 제목
                    내용...
                    (빈 줄)
                    ===DOCS: 문서번호===
                    """
                    
                    if st.session_state.llm:
                        res = st.session_state.llm.generate_content(prompt)
                        ans = res.text.strip()
                        
                        # [수정] AI가 NO_CONTENT를 반환한 경우 처리
                        if "[NO_CONTENT]" in ans:
                            msg = "문서 내용을 분석했으나, 질문에 대한 정확한 답변을 찾을 수 없습니다."
                            st.write(msg)
                            curr_messages.append((query, msg))
                            st.session_state.last_unanswered_query = query # 버튼 활성화 트리거
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
                            
                            # 원문 상세 보기
                            st.markdown("---")
                            st.caption("🔍 참고 문서 (클릭하여 원문 확인)")
                            for i, info in enumerate([x[1] for x in combined][:5], 1):
                                with st.expander(f"{i}. {info['filename']} (관련도: {info['score']:.2f})"):
                                    st.info("💡 문서 원문:")
                                    st.text(info.get('content', '내용 없음'))

                            curr_messages.append((query, ans))
                            st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                    else:
                        st.error("AI 모델 연결 실패")
            except Exception as e:
                st.error(f"오류: {e}")