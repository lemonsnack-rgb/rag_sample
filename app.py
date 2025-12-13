"""
중소기업 업무 자동화 RAG 솔루션 - WorkAnswer
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

# ==================== [시스템 인증 강제 적용] ====================
if "gcp_service_account" in st.secrets:
    try:
        service_account_info = dict(st.secrets["gcp_service_account"])
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as temp:
            json.dump(service_account_info, temp)
            temp_path = temp.name
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
    except Exception as e: st.error(f"인증 파일 에러: {e}")

# ==================== 라이브러리 임포트 ====================
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
    import google.auth
except ImportError: st.stop()

try:
    from rag_module import init_vector_store, sync_drive_to_db, search_similar_documents, get_indexed_documents, reset_database
except ImportError: st.error("rag_module.py 없음"); st.stop()

DEFAULT_SYNONYMS = {"심사료": ["게재료", "투고료", "논문 게재", "학회비"]}

# ==================== 설정 및 초기화 ====================
try:
    secrets_dict = dict(st.secrets)
    if "GOOGLE_API_KEY" in secrets_dict:
        os.environ["GOOGLE_API_KEY"] = secrets_dict["GOOGLE_API_KEY"]
        os.environ["SUPABASE_URL"] = secrets_dict["SUPABASE_URL"]
        os.environ["SUPABASE_KEY"] = secrets_dict["SUPABASE_KEY"]
        os.environ["GOOGLE_DRIVE_FOLDER_ID"] = secrets_dict.get("GOOGLE_DRIVE_FOLDER_ID", "")
except: pass

st.set_page_config(page_title="WorkAnswer", layout="wide", initial_sidebar_state="expanded")

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

# ==================== 스타일링 ====================
st.markdown("""<style>@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');html,body,[class*="css"]{font-family:'Pretendard',sans-serif;}</style>""", unsafe_allow_html=True)

# ==================== 유틸리티 ====================
def format_docs(docs): return "\n\n".join([f"[문서 {i}] (출처: {doc.metadata.get('source', 'Unknown')})\n{doc.page_content}" for i, doc in enumerate(docs, 1)])
def get_session_title(messages): return messages[0][0][:30] + "..." if messages else "새로운 대화"
def get_date_group(created_at): return "오늘" if (datetime.now()-created_at).days==0 else "어제" if (datetime.now()-created_at).days==1 else "이전"
def parse_used_docs(docs_str): return [int(n) for n in re.findall(r'\d+', docs_str)]

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
            if len(row)>=2: new_synonyms[row[0].strip()] = [v.strip() for v in row[1].replace('|',',').split(',') if v.strip()]
        return new_synonyms, f"{len(new_synonyms)}개 로드 성공"
    except Exception as e: return None, str(e)

def expand_query(original_query, llm):
    final = [original_query]
    for k, v in st.session_state.dynamic_synonyms.items():
        if k in original_query: final.extend(v)
    try:
        res = llm.generate_content(f"질문 '{original_query}'의 검색 키워드 2개 추천 (단어만, 콤마구분)")
        final.extend([k.strip() for k in res.text.split(',')])
    except: pass
    return list(set(final))

# ==================== 사이드바 ====================
with st.sidebar:
    if st.button("+ 새 채팅", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.chat_sessions[new_id] = {'messages': [], 'created_at': datetime.now(), 'title': '새로운 대화'}
        st.session_state.current_session_id = new_id
        st.rerun()
    st.divider()
    
    with st.expander("설정 (관리자)"):
        if st.text_input("비밀번호", type="password") == st.secrets.get("ADMIN_PASSWORD", "admin"):
            st.session_state.admin_mode = True
        
        if st.session_state.admin_mode:
            st.success("관리자 모드")
            fid = st.text_input("폴더 ID", value=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""))
            
            if st.button("파일 목록 확인"):
                try:
                    creds, _ = google.auth.default()
                    svc = build('drive', 'v3', credentials=creds)
                    fs = svc.files().list(q=f"'{fid}' in parents and trashed=false").execute().get('files',[])
                    st.info(f"{len(fs)}개 파일 감지")
                except Exception as e: st.error(f"실패: {e}")

            c1, c2 = st.columns(2)
            if c1.button("문서 동기화"):
                try: 
                    # [중요] 여기 인자가 정확해야 합니다 (ID, Client)
                    cnt = sync_drive_to_db(fid, st.session_state.supabase_client)
                    st.success(f"{cnt}개 완료")
                except Exception as e: st.error(f"오류: {e}")
            if c2.button("사전 동기화"):
                d, m = load_synonyms_from_drive(fid)
                if d: st.session_state.dynamic_synonyms = d; st.success(m)
                else: st.warning(m)
            
            if st.button("DB 삭제"):
                if reset_database(st.session_state.supabase_client): st.success("삭제 완료")

# ==================== 메인 화면 ====================
curr = st.session_state.chat_sessions[st.session_state.current_session_id]

if not curr['messages']:
    st.markdown("<h1 style='text-align:center;'>WorkAnswer</h1>", unsafe_allow_html=True)
else:
    for q, a in curr['messages']:
        st.chat_message("user").write(q)
        with st.chat_message("assistant"):
            if "===DETAIL_START===" in a:
                head, tail = a.split("===DETAIL_START===")
                st.write(head)
                with st.expander("상세 보기"): st.markdown(tail.split("===DOCS:")[0])
            else: st.write(a)

q = st.chat_input("질문 입력...")
if q:
    st.chat_message("user").write(q)
    with st.chat_message("assistant"):
        with st.spinner("검색 중..."):
            qs = expand_query(q, st.session_state.llm)
            st.info(f"확장 검색어: {', '.join(qs)}")
            
            all_d, all_i, seen = [], [], set()
            for query in qs:
                ds, is_ = search_similar_documents(query, st.session_state.supabase_client, st.session_state.embeddings)
                for d, i in zip(ds, is_):
                    if d.page_content not in seen:
                        seen.add(d.page_content); all_d.append(d); all_i.append(i)
            
            final = sorted(zip(all_d, all_i), key=lambda x: x[1]['score'], reverse=True)[:15]
            if not final:
                msg = "문서 없음"; st.write(msg)
                curr['messages'].append((q, msg))
            else:
                docs = [x[0] for x in final]
                ctx = format_docs(docs)
                prompt = f"질문: {q}\n\n문맥:\n{ctx}\n\n지침:\n1. 없으면 [NO_CONTENT]\n2. 상세내용은 ### 소제목과 빈줄을 사용해 가독성 있게 작성.\n3. 핵심요약은 불릿포인트.\n\n답변형식:\n[핵심 요약]\n...\n===DETAIL_START===\n### 소제목\n내용...\n===DOCS: ...==="
                res = st.session_state.llm.generate_content(prompt).text
                
                if "DETAIL_START" in res:
                    head, tail = res.split("===DETAIL_START===")
                    st.write(head)
                    with st.expander("상세 보기"): st.markdown(tail.split("===DOCS:")[0])
                else: st.write(res)
                
                curr['messages'].append((q, res))