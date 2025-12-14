import os
import re
import io
import csv
import hashlib
import time
from datetime import datetime
import streamlit as st

# Google Drive API import
import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Supabase Imports
from supabase import create_client, Client

# LangChain and Embedding Imports
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# File Parsing Libraries Imports
import pypdf
import docx
import openpyxl
from pptx import Presentation
from PIL import Image
import pytesseract

# ==================== [텍스트 전처리 - 메타데이터 분리 개선] ====================
def preprocess_text_with_section_headers(text):
    """
    섹션 태그를 메타데이터로 분리하여 임베딩 품질 향상
    """
    if text:
        text = text.replace('\x00', '')

    lines = text.split('\n')
    chunks = []
    current_section = "일반"
    header_pattern = re.compile(r'^\s*제\s*\d+\s*(조|장)')

    current_chunk_lines = []

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue

        # 이미 태그가 있는 경우 (Excel, PPT 등)
        if stripped_line.startswith('[') and ']' in stripped_line:
            if current_chunk_lines:
                chunks.append({
                    "content": "\n".join(current_chunk_lines),
                    "section": current_section
                })
                current_chunk_lines = []
            # 태그 제거하고 순수 내용만 저장
            content_only = re.sub(r'^\[.*?\]\s*', '', stripped_line)
            current_chunk_lines.append(content_only)
            continue

        if header_pattern.match(stripped_line):
            # 새로운 섹션 시작
            if current_chunk_lines:
                chunks.append({
                    "content": "\n".join(current_chunk_lines),
                    "section": current_section
                })
                current_chunk_lines = []
            current_section = stripped_line
            current_chunk_lines.append(stripped_line)
        else:
            # 순수 내용만 저장 (태그 없이)
            current_chunk_lines.append(stripped_line)

    # 마지막 청크 추가
    if current_chunk_lines:
        chunks.append({
            "content": "\n".join(current_chunk_lines),
            "section": current_section
        })

    return chunks

# ==================== [파일 포맷별 텍스트 추출 (OCR 강화)] ====================
def extract_text_from_pdf(fh):
    text = ""
    try:
        reader = pypdf.PdfReader(fh)
        for page in reader.pages:
            t = page.extract_text()
            if t: text += t + "\n"
            else:
                try:
                    for image_file in page.images:
                        img = Image.open(io.BytesIO(image_file.data))
                        text += pytesseract.image_to_string(img, lang='kor+eng') + "\n"
                except: pass
    except Exception as e: print(f"PDF Error: {e}")
    return text

def extract_text_from_docx(fh):
    text = ""
    try:
        doc = docx.Document(fh)
        for para in doc.paragraphs: text += para.text + "\n"
        for table in doc.tables:
            for row in table.rows:
                row_text = [c.text.strip() for c in row.cells]
                text += " | ".join(row_text) + "\n"
            text += "\n"
    except Exception as e: print(f"DOCX Error: {e}")
    return text

def extract_text_from_xlsx(fh, fname):
    text = ""
    try:
        wb = openpyxl.load_workbook(fh, data_only=True)
        for sname in wb.sheetnames:
            sheet = wb[sname]
            rows = list(sheet.rows)
            if not rows: continue
            headers = [str(c.value).strip() if c.value else f"열{i}" for i,c in enumerate(rows[0])]
            for row in rows[1:]:
                parts = []
                for i, c in enumerate(row):
                    if i < len(headers) and c.value is not None:
                        val = str(c.value).strip()
                        if val: parts.append(f"{headers[i]}: {val}")
                if parts: text += f"{fname}-{sname} " + ", ".join(parts) + "\n"
    except Exception as e: print(f"XLSX Error: {e}")
    return text

def extract_text_from_pptx(fh):
    text = ""
    try:
        prs = Presentation(fh)
        for i, slide in enumerate(prs.slides):
            stext = []
            for shape in slide.shapes:
                if hasattr(shape, "text"): stext.append(shape.text)
            if stext: text += f"슬라이드 {i+1} " + "\n".join(stext) + "\n"
    except Exception as e: print(f"PPTX Error: {e}")
    return text

def extract_text_from_txt(fh):
    try:
        c = fh.read()
        try: return c.decode('utf-8')
        except: return c.decode('cp949')
    except: return ""

def extract_text_from_csv(fh, fname):
    text = ""
    try:
        c = fh.read()
        try: dec = c.decode('utf-8')
        except: dec = c.decode('cp949')
        rows = list(csv.reader(io.StringIO(dec)))
        if not rows: return ""
        headers = rows[0]
        for row in rows[1:]:
            parts = []
            for i, v in enumerate(row):
                if i < len(headers) and v.strip():
                    parts.append(f"{headers[i]}: {v.strip()}")
            if parts: text += f"{fname} " + ", ".join(parts) + "\n"
    except Exception as e: print(f"CSV Error: {e}")
    return text

def extract_text_from_image(fh):
    text = ""
    try:
        img = Image.open(fh)
        text = pytesseract.image_to_string(img, lang='kor+eng')
    except Exception as e: print(f"OCR Error: {e}")
    return text

# ==================== [파일 포맷별 최적 청크 크기] ====================
def get_optimal_splitter(file_type):
    """파일 타입에 따라 최적화된 청크 크기 반환"""
    if file_type == 'xlsx':
        return RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    elif file_type == 'pptx':
        return RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=100)
    elif file_type == 'csv':
        return RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    else:
        return RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

# ==================== [핵심 로직: Supabase 연결 및 동기화] ====================

def init_vector_store():
    """
    Supabase 클라이언트를 생성하고 임베딩 모델을 초기화합니다.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        raise ValueError("SUPABASE_URL 또는 SUPABASE_KEY 환경 변수가 설정되지 않았습니다.")

    try:
        supabase_client: Client = create_client(url, key)
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

        return {
            'supabase_client': supabase_client,
            'embeddings': embeddings
        }
    except Exception as e:
        print(f"Supabase 클라이언트 초기화 실패: {e}")
        raise

def get_file_hash(content):
    """파일 내용의 해시값 생성 (중복 체크용)"""
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def delete_document_by_source(client, source_name):
    """
    특정 파일명의 모든 문서를 DB에서 삭제
    중복 방지 및 업데이트를 위한 함수
    """
    try:
        result = client.table("documents").delete().eq("metadata->>source", source_name).execute()
        print(f"✅ {source_name} 기존 데이터 삭제 완료")
        return True
    except Exception as e:
        print(f"❌ {source_name} 삭제 실패: {e}")
        return False

def sync_drive_to_db(folder_id, supabase_client, force_update=False):
    """
    [개선된 핵심 함수] Google Drive에서 파일을 가져와 텍스트를 추출하고 벡터 DB에 동기화합니다.

    개선사항:
    - 중복 방지: 파일별로 기존 데이터 삭제 후 재삽입
    - 파일 타입별 최적 청크 크기
    - 섹션 태그를 메타데이터로 분리
    - 진행상황 상세 로그

    Args:
        folder_id: Google Drive 폴더 ID
        supabase_client: Supabase 클라이언트
        force_update: True일 경우 기존 문서 삭제 후 재색인
    """
    creds, _ = google.auth.default()
    service = build('drive', 'v3', credentials=creds)

    res = service.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id, name, modifiedTime)"
    ).execute()
    files = res.get('files', [])

    st.write(f"🔍 폴더 내 파일 {len(files)}개 감지됨")

    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vector_store = SupabaseVectorStore(
        client=supabase_client,
        embedding=embeddings,
        table_name="documents",
        query_name="match_documents"
    )

    cnt = 0
    skipped = 0
    failed = 0
    progress = st.progress(0)

    for i, f in enumerate(files):
        fid, fname = f['id'], f['name']
        ext = fname.split('.')[-1].lower() if '.' in fname else ""
        progress.progress((i+1)/len(files), text=f"처리 중: {fname}")

        if ext not in ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'csv', 'md', 'jpg', 'jpeg', 'png']:
            st.caption(f"⏩ [Skip] {fname} - 지원하지 않는 형식")
            skipped += 1
            continue

        try:
            # 기존 문서 삭제 (중복 방지)
            if force_update:
                delete_document_by_source(supabase_client, fname)

            # 파일 다운로드
            req = service.files().get_media(fileId=fid)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)

            # 텍스트 추출
            content = ""
            if ext == 'pdf':
                content = extract_text_from_pdf(fh)
            elif ext == 'docx':
                content = extract_text_from_docx(fh)
            elif ext == 'xlsx':
                content = extract_text_from_xlsx(fh, fname)
            elif ext == 'pptx':
                content = extract_text_from_pptx(fh)
            elif ext in ['txt', 'md']:
                content = extract_text_from_txt(fh)
            elif ext == 'csv':
                content = extract_text_from_csv(fh, fname)
            elif ext in ['jpg', 'png', 'jpeg']:
                content = extract_text_from_image(fh)

            if not content.strip():
                st.warning(f"⚠️ {fname} - 내용 없음")
                skipped += 1
                continue

            # 섹션 인식 전처리 (메타데이터 분리)
            processed_chunks = preprocess_text_with_section_headers(content)

            # 파일 타입별 최적 청크 크기
            splitter = get_optimal_splitter(ext)

            # 문서 생성 (섹션 정보를 메타데이터로)
            docs = []
            for chunk_data in processed_chunks:
                # 추가 청크 분할
                sub_chunks = splitter.split_text(chunk_data["content"])
                for sub_chunk in sub_chunks:
                    if sub_chunk.strip():
                        docs.append(Document(
                            page_content=sub_chunk,  # 순수 내용만
                            metadata={
                                "source": fname,
                                "section": chunk_data["section"],  # 섹션은 메타데이터에
                                "file_type": ext,
                                "created_at": datetime.now().isoformat()
                            }
                        ))

            if docs:
                vector_store.add_documents(docs)
                st.success(f"✅ {fname} 완료 ({len(docs)}개 청크)")
                cnt += 1
            else:
                st.warning(f"⚠️ {fname} - 유효한 청크 없음")
                skipped += 1

        except Exception as e:
            st.error(f"❌ {fname} 실패: {str(e)[:100]}")
            print(f"상세 에러 - {fname}: {e}")
            failed += 1

    progress.empty()

    # 결과 요약
    st.info(f"""
    📊 동기화 완료
    - ✅ 성공: {cnt}개
    - ⏩ 건너뜀: {skipped}개
    - ❌ 실패: {failed}개
    - 📁 전체: {len(files)}개
    """)

    return cnt

def search_similar_documents_with_retry(query, client, embeddings, top_k=5, threshold=0.5, max_retries=3):
    """
    재시도 로직이 추가된 검색 함수
    """
    for attempt in range(max_retries):
        try:
            query_vector = embeddings.embed_query(query)

            params = {
                "query_embedding": query_vector,
                "match_threshold": threshold,
                "match_count": top_k
            }

            response = client.rpc("match_documents", params).execute()

            docs = []
            infos = []

            for item in response.data:
                content = item.get("content", "")
                metadata = item.get("metadata", {})
                score = item.get("similarity", 0.0)

                doc = Document(page_content=content, metadata=metadata)
                docs.append(doc)

                infos.append({
                    "content": content,
                    "filename": metadata.get("source", "Unknown"),
                    "section": metadata.get("section", "일반"),
                    "score": score
                })

            return docs, infos

        except Exception as e:
            if attempt == max_retries - 1:
                print(f"검색 실패 ({max_retries}회 시도): {e}")
                return [], []
            print(f"검색 재시도 {attempt + 1}/{max_retries}...")
            time.sleep(1 * (attempt + 1))

def search_similar_documents(query, client, embeddings, top_k=5, dynamic_threshold=True):
    """
    동적 임계값을 사용하는 개선된 검색 함수

    Args:
        query: 검색 쿼리
        client: Supabase 클라이언트
        embeddings: 임베딩 모델
        top_k: 반환할 문서 개수
        dynamic_threshold: True일 경우 동적 임계값 사용
    """
    if dynamic_threshold:
        # 먼저 높은 임계값으로 검색
        docs_high, infos_high = search_similar_documents_with_retry(
            query, client, embeddings, top_k=top_k, threshold=0.5
        )

        # 결과가 충분하면 반환
        if len(docs_high) >= 3:
            return docs_high, infos_high

        # 결과 부족 시 낮은 임계값으로 재검색
        docs_low, infos_low = search_similar_documents_with_retry(
            query, client, embeddings, top_k=top_k, threshold=0.15
        )
        return docs_low, infos_low
    else:
        # 고정 임계값 사용
        return search_similar_documents_with_retry(
            query, client, embeddings, top_k=top_k, threshold=0.15
        )

def get_indexed_documents(client):
    """DB에 색인된 문서 목록 조회"""
    try:
        result = client.table("documents").select("metadata").execute()
        sources = set()
        for item in result.data:
            metadata = item.get("metadata", {})
            source = metadata.get("source", "Unknown")
            sources.add(source)
        return list(sources)
    except Exception as e:
        print(f"문서 목록 조회 실패: {e}")
        return []

def reset_database(client):
    """
    Supabase DB의 documents 테이블 전체를 삭제합니다. (강제 초기화)
    """
    if client is None:
        print("Error: Supabase 클라이언트가 유효하지 않습니다.")
        return False

    try:
        result = client.table("documents").delete().neq("id", 0).execute()

        if result.data == []:
             print("DB 삭제 성공")
             return True
        else:
             print(f"DB 삭제 시도 응답에 데이터가 남아있음: {result.data}")
             return False
    except Exception as e:
        print(f"DB Reset Error: {e}")
        return False
