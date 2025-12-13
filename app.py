"""
중소기업 업무 자동화 RAG 솔루션 - WorkAnswer
(최종 완결: PDF/PPT/XLS/DOC/OCR 통합 + UI 개선 + 문법 오류 수정)
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

# ==================== [1. 시스템 인증 강제 적용] ====================
# rag_module.py 등 외부 파일에서 구글 인증을 찾을 수 있도록 환경변수 강제 주입
if "gcp_service_account" in st.secrets:
    try:
        service_account_info = dict(st.secrets["gcp_service_account"])
        # 임시 JSON 파일 생성 (구글 라이브러리 호환용)
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as temp:
            json.dump(service_account_info, temp)
            temp_path = temp.name
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
    except Exception as e:
        st.error(f"인증 파일 생성 에러: {e}")

# ==================== [2. 라이브러리 임포트] ====================
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
    import google.auth
except ImportError:
    st.error("Google API 라이브러리가 없습니다. requirements.txt를 확인하세요.")
    st.stop()

try:
    # rag_module.py가 같은 폴더에 있어야 함
    from rag_module import init_vector_store, sync_drive_to_db, search_similar_documents, get_indexed_documents, reset_database
except ImportError:
    st.error("rag_module.py 파일을 찾을 수 없습니다. GitHub에 파일이 있는지 확인하세요.")
    st.stop()

# ==================== [3. 기본 설정 및 세션 초기화] ====================
DEFAULT_SYNONYMS = {"심사료": ["게재료", "투고료", "논문 게재", "학회비"]}

# Secrets 로드 시도
try:
    secrets_dict = dict(st.secrets)
    if "GOOGLE_API_KEY" in secrets_dict:
        os.environ["GOOGLE_API_KEY"] = secrets_dict["GOOGLE_API_KEY"]
        os.environ["SUPABASE_URL"] = secrets_dict["SUPABASE_URL"]
        os.environ["SUPABASE_KEY"] = secrets_dict["SUPABASE_KEY"]
        os.environ["GOOGLE_DRIVE_FOLDER_ID"] = secrets_dict.get("GOOGLE_DRIVE_FOLDER_ID", "")
except:
    pass

st.set_page_config(page_title="WorkAnswer", layout="wide", initial_sidebar_state="expanded")

# 세션 상태 변수 초기화
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

# 시스템 연결 (RAG 모듈 연동)
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
        except:
            st.session_state.llm = None
            
        st.session_state.system_initialized = True
    except:
        st.session_state.system_initialized = False

# ==================== [4. 스타일링] ====================
st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; }
    [data-testid="stChatMessage"] { padding: 1rem; border-radius: 15px; margin-bottom: 0.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    [data-testid="stChatMessage"][data-testid-user-avatar="true"] { background-color: #E3F2FD; }
    [data-testid="stChatMessage"][data-testid-user-avatar="false"] { background-color: #FFFFFF; border: 1px solid #e0e0e0; }
</style>
""", unsafe_allow_html=True)

# ==================== [5. 유틸리티 함수] ====================
def format_docs(docs):
    """검색된 문서들을 하나의 텍스트로 합침"""
    return "\n\n".join([f"[문서 {i}] (출처: {doc.metadata.get('source', 'Unknown')})\n{doc.page_content}" for i, doc in enumerate(docs, 1)])

def get_session_title(messages):
    """대화 제목 생성"""
    return messages[0][0][:30] + "..." if messages else "새로운 대화"

def get_date_group(created_at):
    """날짜별 그룹화"""
    diff = (datetime.now() - created_at).days
    return "오늘" if diff == 0 else "어제" if diff == 1 else "이전"

def load_synonyms_from_drive(folder_id):
    """구글 드라이브에서 dictionary.csv 로드"""
    try:
        creds, _ = google.auth.default()
        service = build('drive', 'v3', credentials=creds)
        results = service.files().list(q=f"name='dictionary.csv' and '{folder_id}' in parents and trashed=false", fields="files(id)").execute()
        files = results.get('files', [])
        
        if not files: return None, "사전 파일(dictionary.csv) 없음"
        
        content = service.files().get_media(fileId=files[0]['id']).execute()
        try: decoded = content.decode('utf-8')
        except: decoded = content.decode('cp949')
        
        new_synonyms = {}
        for row in csv.reader(io.StringIO(decoded)):
            if len(row) >= 2:
                new_synonyms[row[0].strip()] = [v.strip() for v in row[1].replace('|', ',').split(',') if v.strip()]
        return new_synonyms, f"{len(new_synonyms)}개 키워드 로드 성공"
    except Exception as e:
        return None, str(e)

def expand_query(original_query, llm):
    """검색어 확장 함수 (동의어 + LLM 추천)"""
    final = [original_query]
    # 1. 사전 기반 확장
    for k, v in st.session_state.dynamic_synonyms.items():
        if k in original_query: final.extend(v)
    
    # 2. LLM 기반 확장
    try:
        if llm:
            prompt = f"질문 '{original_query}'를 검색하기 위한 핵심 키워드 2개만 추천해줘 (단어만, 쉼표로 구분)"
            res = llm.generate_content(prompt)
            final.extend([k.strip() for k in res.text.split(',')])
    except:
        pass
    return list(set(final))

# ==================== [6. 사이드바 구성] ====================
with st.sidebar:
    # 새 채팅 버튼
    if st.button("+ 새 채팅", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.chat_sessions[new_id] = {'messages': [], 'created_at': datetime.now(), 'title': '새로운 대화'}
        st.session_state.current_session_id = new_id
        st.rerun()

    st.divider()
    
    # 대화 목록 출력
    sessions_by_date = {"오늘": [], "어제": [], "이전": []}
    for sid, sdata in st.session_state.chat_sessions.items():
        dg = get_date_group(sdata['created_at'])
        if dg in sessions_by_date: sessions_by_date[dg].append((sid, sdata))
    
    for gname in ["오늘", "어제", "이전"]:
        if sessions_by_date[gname]:
            st.caption(gname)
            for sid, sdata in sorted(sessions_by_date[gname], key=lambda x: x[1]['created_at'], reverse=True):
                title = get_session_title(sdata['messages'])
                # 현재 활성화된 채팅방은 primary 색상으로 표시
                btn_type = "primary" if sid == st.session_state.current_session_id else "secondary"
                if st.button(title, key=sid, use_container_width=True, type=btn_type):
                    st.session_state.current_session_id = sid
                    st.rerun()

    st.divider()
    
    # 관리자 설정 패널
    with st.expander("설정 (관리자)"):
        pw = st.text_input("비밀번호", type="password")
        if pw == st.secrets.get("ADMIN_PASSWORD", "admin"):
            st.session_state.admin_mode = True
        
        if st.session_state.admin_mode:
            st.success("관리자 모드 ON")
            fid = st.text_input("폴더 ID", value=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""))
            
            # [디버깅] 파일 목록 확인 버튼
            if st.button("📁 파일 목록 확인 (디버깅)"):
                try:
                    creds, _ = google.auth.default()
                    svc = build('drive', 'v3', credentials=creds)
                    fs = svc.files().list(q=f"'{fid}' in parents and trashed=false").execute().get('files', [])
                    st.info(f"{len(fs)}개 파일 감지됨")
                    for f in fs: st.text(f"- {f['name']}")
                except Exception as e: st.error(f"에러: {e}")

            col1, col2 = st.columns(2)
            with col1:
                # 문서 동기화 버튼
                if st.button("문서 동기화"):
                    with st.spinner("동기화 중..."):
                        try:
                            # rag_module.py의 함수 호출 (인자 2개 확인)
                            cnt = sync_drive_to_db(fid, st.session_state.supabase_client)
                            st.success(f"{cnt}개 처리 완료")
                        except Exception as e: st.error(f"실패: {e}")
            
            with col2:
                # 사전 동기화 버튼
                if st.button("사전 동기화"):
                    with st.spinner("동기화 중..."):
                        d, m = load_synonyms_from_drive(fid)
                        if d:
                            st.session_state.dynamic_synonyms = d
                            st.success(m)
                        else: st.warning(m)
            
            if st.button("DB 전체 삭제 (초기화)", type="primary"):
                if reset_database(st.session_state.supabase_client):
                    st.success("삭제 완료")
                else:
                    st.error("삭제 실패")

# ==================== [7. 메인 채팅 화면] ====================
curr_session = st.session_state.chat_sessions[st.session_state.current_session_id]

# 초기 화면 안내 메시지
if not curr_session['messages']:
    st.markdown("<div style='height: 10vh'></div>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center;'>WorkAnswer</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: grey;'>사내 규정, 매뉴얼, 보고서 양식을 질문해보세요.</p>", unsafe_allow_html=True)
else:
    # 기존 대화 내용 표시
    for q, a in curr_session['messages']:
        st.chat_message("user").write(q)
        with st.chat_message("assistant"):
            if "===DETAIL_START===" in a:
                parts = a.split("===DETAIL_START===")
                st.write(parts[0].strip())
                if len(parts) > 1:
                    detail_part = parts[1].split("===DOCS:")[0]
                    with st.expander("상세 내용 보기"):
                        st.markdown(detail_part.strip())
            else:
                st.write(a)

# 질문 입력 처리
if query := st.chat_input("질문을 입력하세요..."):
    # 1. 사용자 질문 표시
    st.chat_message("user").write(query)
    
    # 2. 답변 생성 프로세스
    with st.chat_message("assistant"):
        with st.spinner("문서를 검색하고 답변을 생성 중입니다..."):
            try:
                # (1) 검색어 확장
                search_queries = expand_query(query, st.session_state.llm)
                st.caption(f"💡 검색 키워드: {', '.join(search_queries)}")
                
                # (2) 문서 검색 수행
                all_docs = []
                all_infos = []
                seen_contents = set()
                
                for q in search_queries:
                    if st.session_state.supabase_client:
                        docs, infos = search_similar_documents(q, st.session_state.supabase_client, st.session_state.embeddings)
                        for d, i in zip(docs, infos):
                            if d.page_content not in seen_contents:
                                seen_contents.add(d.page_content)
                                all_docs.append(d)
                                all_infos.append(i)
                
                # (3) 결과 정렬 및 상위 15개 선택
                combined = sorted(zip(all_docs, all_infos), key=lambda x: x[1]['score'], reverse=True)[:15]
                
                if not combined:
                    msg = "죄송합니다. 관련 문서를 찾을 수 없습니다."
                    st.write(msg)
                    curr_session['messages'].append((query, msg))
                else:
                    # (4) LLM 답변 생성
                    source_docs = [x[0] for x in combined]
                    context_text = format_docs(source_docs)
                    
                    prompt = f"""
                    너는 유능한 사내 업무 전문가다. 아래 [Context]를 바탕으로 사용자의 질문에 답변해라.
                    
                    [Context]:
                    {context_text}
                    
                    질문: {query}
                    
                    [지침]
                    1. 정보가 없으면 '[NO_CONTENT]'라고 답해라.
                    2. [핵심 요약]은 불릿포인트로 간결하게 요약해라.
                    3. [상세 내용]은 전문성을 갖추되, 가독성을 위해 **### 소제목**과 **문단 간 빈 줄**을 반드시 사용해라.
                    
                    답변형식:
                    [핵심 요약]
                    - 내용
                    ===DETAIL_START===
                    ### 상세 내용 제목
                    내용...
                    (빈 줄)
                    ### 다음 제목
                    내용...
                    ===DOCS: 문서번호===
                    """
                    
                    if st.session_state.llm:
                        response = st.session_state.llm.generate_content(prompt)
                        final_answer = response.text.strip()
                        
                        # (5) 화면 출력
                        if "===DETAIL_START===" in final_answer:
                            parts = final_answer.split("===DETAIL_START===")
                            st.write(parts[0].strip())
                            with st.expander("상세 내용 보기"):
                                st.markdown(parts[1].split("===DOCS:")[0].strip())
                        else:
                            st.write(final_answer)
                            
                        # (6) 참고 문서 표시
                        with st.expander("참고 문서 확인"):
                            for i, info in enumerate([x[1] for x in combined][:5], 1):
                                st.text(f"{i}. {info['filename']} (유사도: {info['score']:.2f})")

                        curr_session['messages'].append((query, final_answer))
                    else:
                        st.error("AI 모델 연결 실패")
                        
            except Exception as e:
                st.error(f"답변 생성 중 오류 발생: {e}")