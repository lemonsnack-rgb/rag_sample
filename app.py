"""
중소기업 업무 자동화 RAG 솔루션 - WorkAnswer
(최종 완결: 상세 답변의 완결성(Professionalism) 강화 + 가독성 + 구글 인증 + PDF 디버깅 통합)
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

# ==================== [긴급 처방] 시스템 전체 인증 강제 적용 ====================
if "gcp_service_account" in st.secrets:
    try:
        service_account_info = dict(st.secrets["gcp_service_account"])
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as temp:
            json.dump(service_account_info, temp)
            temp_path = temp.name
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_path
    except Exception as e:
        st.error(f"인증 파일 생성 중 오류 발생: {e}")
# ==============================================================================

# 라이브러리 임포트
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
    import google.auth
except ImportError:
    st.error("Google API 라이브러리가 필요합니다. requirements.txt를 확인하세요.")
    st.stop()

try:
    from rag_module import init_vector_store, sync_drive_to_db, search_similar_documents, get_indexed_documents, reset_database
except ImportError:
    st.error("rag_module.py 파일을 찾을 수 없습니다.")
    st.stop()

# ==================== [기본] 백업용 사전 ====================
DEFAULT_SYNONYMS = {
    "심사료": ["게재료", "투고료", "논문 게재", "학회비"],
}

# ==================== 환경 변수 및 설정 ====================
try:
    secrets_dict = dict(st.secrets)
    if "GOOGLE_API_KEY" in secrets_dict:
        os.environ["GOOGLE_API_KEY"] = secrets_dict["GOOGLE_API_KEY"]
        os.environ["SUPABASE_URL"] = secrets_dict["SUPABASE_URL"]
        os.environ["SUPABASE_KEY"] = secrets_dict["SUPABASE_KEY"]
        os.environ["GOOGLE_DRIVE_FOLDER_ID"] = secrets_dict.get("GOOGLE_DRIVE_FOLDER_ID", "")
    else:
        raise KeyError("No secrets available")
except Exception:
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

# 페이지 설정
st.set_page_config(
    page_title="WorkAnswer",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 세션 초기화 ====================
if 'supabase_client' not in st.session_state:
    st.session_state.supabase_client = None
if 'embeddings' not in st.session_state:
    st.session_state.embeddings = None
if 'llm' not in st.session_state:
    st.session_state.llm = None
if 'admin_mode' not in st.session_state:
    st.session_state.admin_mode = False
if 'system_initialized' not in st.session_state:
    st.session_state.system_initialized = False

# [동적 사전 변수]
if 'dynamic_synonyms' not in st.session_state:
    st.session_state.dynamic_synonyms = DEFAULT_SYNONYMS.copy()

if 'last_unanswered_query' not in st.session_state:
    st.session_state.last_unanswered_query = None

# 대화 세션 구조
if 'chat_sessions' not in st.session_state:
    st.session_state.chat_sessions = {}
if 'current_session_id' not in st.session_state:
    first_session_id = str(uuid.uuid4())
    st.session_state.chat_sessions[first_session_id] = {
        'messages': [],
        'created_at': datetime.now(),
        'title': '새로운 대화'
    }
    st.session_state.current_session_id = first_session_id

# 시스템 자동 초기화
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
            st.session_state.llm.generate_content("Hi")
        except:
            st.session_state.llm = None

        st.session_state.system_initialized = True
    except Exception as e:
        st.session_state.system_initialized = False


# ==================== CSS 스타일링 ====================
st.markdown("""
<style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; }

    header[data-testid="stHeader"] { background: transparent; z-index: 1; }
    .stAppDeployButton { display: none; }
    footer { visibility: hidden; }
    #MainMenu { visibility: visible; }

    [data-testid="stSidebar"] { background-color: #f8f9fa; border-right: 1px solid #e9ecef; }

    .block-container {
        max-width: 900px !important;
        padding-top: 3rem;
        padding-bottom: 20rem;
        margin: 0 auto;
    }

    [data-testid="stBottom"] {
        background: transparent; box-shadow: none; padding-bottom: 40px; z-index: 99;
    }
    [data-testid="stBottom"] > div {
        max-width: 900px !important; margin: 0 auto; width: 100%; box-shadow: none;
    }
    [data-testid="stChatInput"] {
        max-width: 900px !important; margin: 0 auto !important;
        border-radius: 20px; border: 1px solid #dfe1e5; background-color: white;
        position: relative !important;
    }

    [data-testid="stChatMessage"] {
        padding: 1rem; border-radius: 15px; margin-bottom: 1rem;
        display: flex; gap: 1rem; border: none; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    [data-testid="stChatMessage"]:has([data-testid="user-avatar-icon"]),
    [data-testid="stChatMessage"][data-testid-user-avatar="true"] {
        background-color: #E3F2FD; flex-direction: row-reverse; text-align: right;
    }
    [data-testid="stChatMessage"]:has([data-testid="user-avatar-icon"]) div[data-testid="stMarkdownContainer"] > p {
        text-align: right;
    }
    [data-testid="stChatMessage"]:has([data-testid="assistant-avatar-icon"]),
    [data-testid="stChatMessage"][data-testid-user-avatar="false"] {
        background-color: #FFFFFF; border: 1px solid #e0e0e0; flex-direction: row; text-align: left;
    }

    [data-testid="stChatInput"]::after {
        content: '⚠️ AI 답변은 부정확할 수 있으며, 이에 대한 책임을 지지 않습니다. 반드시 원문 출처를 확인하시기 바랍니다.';
        position: absolute; top: 110%; left: 0; width: 100%;
        text-align: center; font-size: 0.75rem; color: #888;
        pointer-events: none; display: block;
    }

    .stButton > button[kind="primary"] { background-color: #2c3e50; color: white; border: none; }
    .stButton > button[kind="secondary"] { background-color: #ffffff; color: #333333; border: 1px solid #e2e8f0; }
</style>
""", unsafe_allow_html=True)


# ==================== 유틸리티 함수 ====================
def format_docs(docs):
    formatted_parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get('source', 'Unknown')
        formatted_parts.append(f"[문서 {i}] (출처: {source})\n{doc.page_content}")
    return "\n\n".join(formatted_parts)

def get_session_title(messages):
    if messages and len(messages) > 0:
        first = messages[0][0]
        return first[:30] + "..." if len(first) > 30 else first
    return "새로운 대화"

def get_date_group(created_at):
    now = datetime.now()
    diff = now - created_at
    if diff.days == 0: return "오늘"
    elif diff.days == 1: return "어제"
    elif diff.days <= 7: return "지난 7일"
    else: return "이전"

def parse_used_docs(docs_str):
    try:
        nums = re.findall(r'\d+', docs_str)
        return [int(n) for n in nums]
    except:
        return []

# ==================== CSV 파일 읽기 함수 ====================
def load_synonyms_from_drive(folder_id):
    print("드라이브 사전 동기화 시도 (CSV)...")
    try:
        creds, _ = google.auth.default()
        service = build('drive', 'v3', credentials=creds)

        query = f"name = 'dictionary.csv' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])

        if not files:
            return None, "사전 파일(dictionary.csv)을 찾을 수 없습니다."

        file_id = files[0]['id']
        request = service.files().get_media(fileId=file_id)
        file_io = io.BytesIO()
        downloader = MediaIoBaseDownload(file_io, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        content_bytes = file_io.getvalue()
        try:
            content_str = content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                content_str = content_bytes.decode('cp949')
            except UnicodeDecodeError:
                return None, "CSV 파일 인코딩 오류 (UTF-8/CP949)"

        new_synonyms = {}
        f = io.StringIO(content_str)
        reader = csv.reader(f)
        
        for row in reader:
            if len(row) < 2: continue
            key = row[0].strip()
            synonym_str = row[1].strip().replace('|', ',')
            val_list = [v.strip() for v in synonym_str.split(',') if v.strip()]
            if key and val_list:
                new_synonyms[key] = val_list
            
        return new_synonyms, f"성공! {len(new_synonyms)}개의 키워드를 로드했습니다."

    except Exception as e:
        return None, f"오류 발생: {str(e)}"

# ==================== 질문 확장 함수 ====================
def expand_query(original_query, llm):
    final_keywords = [original_query]
    current_dict = st.session_state.dynamic_synonyms
    for key, values in current_dict.items():
        if key in original_query:
            final_keywords.extend(values)
            
    try:
        prompt = f"""사용자의 질문을 바탕으로 사내 문서 검색에 사용할 '핵심 키워드' 2개를 추천해라.
        질문: {original_query}
        [출력 형식] 키워드1, 키워드2 (단어만)"""
        response = llm.generate_content(prompt)
        ai_keywords = [k.strip() for k in response.text.strip().split(',')]
        final_keywords.extend(ai_keywords)
    except:
        pass
        
    return list(set(final_keywords))

# ==================== 사이드바 ====================
with st.sidebar:
    if st.button("+ 새 채팅", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.chat_sessions[new_id] = {
            'messages': [], 'created_at': datetime.now(), 'title': '새로운 대화'
        }
        st.session_state.current_session_id = new_id
        st.session_state.last_unanswered_query = None
        st.rerun()

    st.divider()

    sessions_by_date = {"오늘": [], "어제": [], "지난 7일": [], "이전": []}
    for sid, sdata in st.session_state.chat_sessions.items():
        dg = get_date_group(sdata['created_at'])
        sessions_by_date[dg].append((sid, sdata))

    for g in sessions_by_date:
        sessions_by_date[g].sort(key=lambda x: x[1]['created_at'], reverse=True)

    for gname in ["오늘", "어제", "지난 7일", "이전"]:
        sess_list = sessions_by_date[gname]
        if sess_list:
            st.caption(gname)
            for sid, sdata in sess_list:
                title = get_session_title(sdata['messages'])
                is_active = (sid == st.session_state.current_session_id)
                if st.button(title, key=f"s_{sid}", use_container_width=True, type="primary" if is_active else "secondary"):
                    st.session_state.current_session_id = sid
                    st.session_state.last_unanswered_query = None
                    st.rerun()
    
    st.divider()
    
    # [관리자 패널]
    with st.expander("설정 (관리자)"):
        st.markdown("**관리자 접근**")
        apw = st.text_input("비밀번호", type="password", key="admin_password")
        correct_pw = st.secrets.get("ADMIN_PASSWORD", "admin")
        
        if apw:
            if apw == correct_pw: st.session_state.admin_mode = True
            else: 
                st.session_state.admin_mode = False
                st.error("불일치")

        if st.session_state.admin_mode:
            st.success("관리자 모드 ON")
            fid = st.text_input("Google Drive 폴더 ID", value=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""))
            
            # [디버깅] 파일 목록 조회
            if st.button("📁 폴더 내 파일 확인 (디버깅)", use_container_width=True):
                if fid:
                    with st.spinner("파일 목록 조회 중..."):
                        try:
                            creds, _ = google.auth.default()
                            service = build('drive', 'v3', credentials=creds)
                            results = service.files().list(
                                q=f"'{fid}' in parents and trashed = false",
                                fields="files(id, name, mimeType)"
                            ).execute()
                            files = results.get('files', [])
                            st.info(f"총 {len(files)}개의 파일이 감지됨")
                            for f in files:
                                st.text(f"- {f['name']} ({f['mimeType']})")
                        except Exception as e:
                            st.error(f"조회 실패: {e}")

            col_db, col_dic = st.columns(2)
            with col_db:
                if st.button("문서 동기화", use_container_width=True):
                    if fid:
                        with st.spinner("문서 동기화 중..."):
                            try:
                                cnt = sync_drive_to_db(fid, st.session_state.supabase_client)
                                st.success(f"{cnt}개 완료")
                            except Exception as e: st.error(f"오류: {e}")
            
            with col_dic:
                if st.button("동의어(CSV) 동기화", use_container_width=True):
                    if fid:
                        with st.spinner("dictionary.csv 읽는 중..."):
                            new_dict, msg = load_synonyms_from_drive(fid)
                            if new_dict:
                                st.session_state.dynamic_synonyms = new_dict
                                st.success(msg)
                            else:
                                st.warning(msg)

            if st.checkbox("DB 초기화 확인"):
                if st.button("DB 삭제", type="primary", use_container_width=True):
                    with st.spinner("삭제 중..."):
                        if reset_database(st.session_state.supabase_client): st.success("완료")
                        else: st.error("실패")
            
            with st.expander("현재 적용된 유의어 확인"):
                st.json(st.session_state.dynamic_synonyms)

# ==================== 메인 화면 ====================
curr_session = st.session_state.chat_sessions[st.session_state.current_session_id]
curr_messages = curr_session['messages']

if len(curr_messages) == 0:
    st.markdown("<div style='height: 15vh'></div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("""
        <div style='text-align: center;'>
            <h1 style='color: #2c3e50; margin-bottom: 0.5rem;'>WorkAnswer</h1>
            <p style='color: #718096;'>무엇을 도와드릴까요?</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='height: 2rem'></div>", unsafe_allow_html=True)
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button("규정 검색", use_container_width=True):
                st.session_state.pending_question = "회사 규정에 대해 알려주세요."
                st.rerun()
        with b2:
            if st.button("메일 작성", use_container_width=True):
                st.session_state.pending_question = "공식 이메일 작성 가이드를 알려주세요."
                st.rerun()
        with b3:
            if st.button("보고서", use_container_width=True):
                st.session_state.pending_question = "주요 보고서 양식을 알려주세요."
                st.rerun()
else:
    for q, a in curr_messages:
        with st.chat_message("user", avatar="user"): st.write(q)
        with st.chat_message("assistant", avatar="assistant"):
            display_text = a
            if "===DOCS:" in a:
                main_part, docs_part = a.split("===DOCS:", 1)
                display_text = main_part.strip()
            
            if "===DETAIL_START===" in display_text:
                parts = display_text.split("===DETAIL_START===", 1)
                st.write(parts[0].strip())
                with st.expander("상세 보기"): st.markdown(parts[1].strip())
            else: st.write(display_text)

if st.session_state.last_unanswered_query:
    st.markdown("---")
    st.warning(f"'{st.session_state.last_unanswered_query}'에 대한 답변이 사내 문서에 없습니다.")
    if st.button("🌐 일반 지식으로 검색", use_container_width=True, type="primary"):
        with st.spinner("Gemini 일반 지식 검색 중..."):
            try:
                query = st.session_state.last_unanswered_query
                prompt = f"질문: {query}\n\n너는 유능한 AI 비서다. 위 질문에 대해 너의 일반적인 지식을 바탕으로 정중하게 답변해라."
                
                if st.session_state.llm:
                    res = st.session_state.llm.generate_content(prompt)
                    ans = f"[일반 지식 답변]\n\n{res.text}"
                else: ans = "AI 모델 연결 실패"
                
                curr_messages.append((query, ans))
                st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                st.session_state.last_unanswered_query = None
                st.rerun()
            except Exception as e: st.error(f"오류: {e}")

user_question = st.chat_input("메시지를 입력하세요...")
if 'pending_question' in st.session_state and st.session_state.pending_question:
    user_question = st.session_state.pending_question
    st.session_state.pending_question = None

if user_question:
    if not st.session_state.supabase_client:
        st.error("시스템 초기화 오류")
        st.stop()

    st.session_state.last_unanswered_query = None
    with st.chat_message("user", avatar="user"): st.write(user_question)

    with st.chat_message("assistant", avatar="assistant"):
        with st.spinner("관련 키워드 확장 및 문서 검색 중..."):
            try:
                # 1. 질문 확장
                search_queries = expand_query(user_question, st.session_state.llm)
                st.info(f"💡 확장된 검색어: {', '.join(search_queries)}")
                
                # 2. 검색 수행
                all_docs = []
                all_infos = []
                seen_contents = set()
                
                for q in search_queries:
                    docs, infos = search_similar_documents(
                        query=q,
                        supabase_client=st.session_state.supabase_client,
                        embeddings=st.session_state.embeddings,
                        top_k=7
                    )
                    for doc, info in zip(docs, infos):
                        if doc.page_content not in seen_contents:
                            seen_contents.add(doc.page_content)
                            all_docs.append(doc)
                            info['content'] = doc.page_content
                            all_infos.append(info)
                
                combined = list(zip(all_docs, all_infos))
                combined.sort(key=lambda x: x[1]['score'], reverse=True)
                
                source_docs = [x[0] for x in combined][:15]
                similarity_info = [x[1] for x in combined][:15]

                if not source_docs:
                    msg = "관련된 사내 문서를 찾을 수 없습니다."
                    st.write(msg)
                    curr_messages.append((user_question, msg))
                    st.session_state.last_unanswered_query = user_question
                    st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                    st.session_state.chat_sessions[st.session_state.current_session_id]['title'] = get_session_title(curr_messages)
                    st.rerun()

                else:
                    context = format_docs(source_docs)
                    if st.session_state.llm:
                        # ============================================
                        # [핵심] 프롬프트 수정: 내용 완결성을 최우선으로 지시
                        # ============================================
                        prompt = f"""너는 사내 규정 전문가다. 아래 [Context]를 읽고 질문에 답해라.

[Context]:
{context}

질문: {user_question}

[지침]
1. [Context]에 답이 없으면 `[NO_CONTENT]` 라고만 출력해라.
2. [핵심 요약]은 **반드시 불릿포인트(- )를 사용하여 명사형 종결(개조식)로 요약**해라.
3. [상세 내용] 작성 시 다음 **대원칙**을 반드시 준수해라:
   - **제 1원칙 (내용의 완결성):** 문서의 내용을 **절대 생략하지 말고**, 전문적이고 구체적으로 빠짐없이 작성해라. 단순 요약이 아니라, 실무자가 보고 바로 업무에 적용할 수 있을 정도로 상세해야 한다.
   - **제 2원칙 (가독성):** 위 내용을 작성할 때, 읽기 편하도록 **### 소제목**과 **문단 간 빈 줄**을 사용하여 구조화해라.
4. 마지막에 참고한 문서 번호를 적어라.

답변형식:
[핵심 요약]
- 핵심 내용 1
- 핵심 내용 2
===DETAIL_START===
### 소제목 (예: 적용 범위)
(빈 줄)
내용 상세 기술...
(빈 줄)
### 소제목 (예: 지급 기준)
내용 상세 기술...
===DOCS: 번호, 번호===
또는
[NO_CONTENT]
"""
                        response = st.session_state.llm.generate_content(prompt)
                        answer_text = response.text.strip()
                    else: answer_text = "AI 모델 연결 실패"

                    if "[NO_CONTENT]" in answer_text:
                        msg = "사내 문서에서 정확한 답변을 찾을 수 없습니다."
                        st.write(msg)
                        curr_messages.append((user_question, msg))
                        st.session_state.last_unanswered_query = user_question
                        st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                        st.session_state.chat_sessions[st.session_state.current_session_id]['title'] = get_session_title(curr_messages)
                        st.rerun()
                        
                    else:
                        used_indices = []
                        clean_answer = answer_text
                        
                        if "===DOCS:" in answer_text:
                            clean_answer, docs_part = answer_text.split("===DOCS:", 1)
                            used_indices = parse_used_docs(docs_part)
                            clean_answer = clean_answer.strip()
                        
                        if "===DETAIL_START===" in clean_answer:
                            p = clean_answer.split("===DETAIL_START===", 1)
                            st.write(p[0].strip())
                            with st.expander("상세 보기"): st.markdown(p[1].strip())
                        else: st.write(clean_answer)

                        valid_docs = []
                        for idx in used_indices:
                            if 0 <= idx-1 < len(similarity_info):
                                valid_docs.append(similarity_info[idx-1])
                        
                        final_docs_to_show = valid_docs if valid_docs else similarity_info[:3]
                        label = "AI가 참고한 문서 (클릭하여 원본 보기)" if valid_docs else "유사 문서 (자동 추천)"

                        st.markdown(f"**📂 {label} ({len(final_docs_to_show)}개)**")
                        for i, info in enumerate(final_docs_to_show, 1):
                            with st.expander(f"{i}. {info['filename']} (유사도: {info['score']:.2f})"):
                                st.info("아래는 색인된 원본 데이터입니다.")
                                st.text(info.get('content', '내용 없음'))

                        curr_messages.append((user_question, answer_text))
                        st.session_state.chat_sessions[st.session_state.current_session_id]['messages'] = curr_messages
                        st.session_state.chat_sessions[st.session_state.current_session_id]['title'] = get_session_title(curr_messages)

            except Exception as e: st.error(f"에러: {e}")