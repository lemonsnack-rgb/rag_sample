import os
import re
import io
import csv
from datetime import datetime
import streamlit as st
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from supabase import create_client

# ==================== 라이브러리 로드 및 에러 처리 ====================
try:
    import pypdf
    import docx
    import openpyxl
    from pptx import Presentation  # PPT 처리용
    from PIL import Image          # 이미지 처리용
    import pytesseract             # OCR용
except ImportError as e:
    st.error(f"필수 라이브러리가 설치되지 않았습니다: {e}")
    st.stop()

# ==================== 섹션/조항 인식 및 문맥 주입 함수 ====================
def preprocess_text_with_section_headers(text):
    """
    문서 내용을 줄 단위로 읽으면서 헤더(제N조, 제N장)를 감지하여
    일반 텍스트에도 해당 섹션 정보(Context)를 강제로 주입합니다.
    """
    lines = text.split('\n')
    processed_lines = []
    
    current_section = "일반"
    # 정규표현식: 제1조, 제 1 조, 제1장, 1. 가. 등 (조/장 위주로 감지)
    header_pattern = re.compile(r'^\s*제\s*\d+\s*(조|장)')

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue
            
        # 1. 이미 문맥 태그([...])가 붙어있는 경우 (엑셀/CSV 등)는 그대로 유지
        if stripped_line.startswith('[') and ']' in stripped_line:
            processed_lines.append(stripped_line)
            continue

        # 2. 규정집 헤더 감지
        if header_pattern.match(stripped_line):
            current_section = stripped_line
            processed_lines.append(line)
        else:
            # 일반 텍스트에 섹션명 주입
            enriched_line = f"[{current_section}] {stripped_line}"
            processed_lines.append(enriched_line)
            
    return "\n".join(processed_lines)

# ==================== 파일 포맷별 텍스트 추출 함수들 ====================

def extract_text_from_pdf(file_stream):
    """PDF 텍스트 추출"""
    text = ""
    try:
        pdf_reader = pypdf.PdfReader(file_stream)
        for page in pdf_reader.pages:
            extracted = page.extract_text()
            if extracted: text += extracted + "\n"
    except Exception as e: print(f"PDF Error: {e}")
    return text

def extract_text_from_docx(file_stream):
    """Word 텍스트 및 표 추출"""
    text = ""
    try:
        doc = docx.Document(file_stream)
        for para in doc.paragraphs: text += para.text + "\n"
        for table in doc.tables:
            for row in table.rows:
                row_text = [cell.text.strip() for cell in row.cells]
                text += " | ".join(row_text) + "\n"
            text += "\n"
    except Exception as e: print(f"DOCX Error: {e}")
    return text

def extract_text_from_xlsx(file_stream, filename):
    """Excel 행 단위 문맥화 추출"""
    text = ""
    try:
        wb = openpyxl.load_workbook(file_stream, data_only=True)
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            rows = list(sheet.rows)
            if not rows: continue
            
            # 헤더 추출 (첫 줄)
            headers = [str(cell.value).strip() if cell.value else f"열{i}" for i, cell in enumerate(rows[0])]
            
            # 데이터 추출
            for row in rows[1:]:
                row_parts = []
                for i, cell in enumerate(row):
                    if i < len(headers) and cell.value is not None:
                        val = str(cell.value).strip()
                        if val: row_parts.append(f"{headers[i]}: {val}")
                if row_parts:
                    text += f"[{filename}-{sheet_name}] " + ", ".join(row_parts) + "\n"
    except Exception as e: print(f"XLSX Error: {e}")
    return text

def extract_text_from_pptx(file_stream):
    """[신규] PowerPoint 슬라이드 텍스트 추출"""
    text = ""
    try:
        prs = Presentation(file_stream)
        for i, slide in enumerate(prs.slides):
            slide_text = []
            # 슬라이드 내 모든 텍스트 상자(Shape) 순회
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    slide_text.append(shape.text)
            
            if slide_text:
                # 슬라이드 번호를 문맥으로 포함
                page_content = "\n".join(slide_text)
                text += f"[슬라이드 {i+1}페이지] {page_content}\n"
    except Exception as e: print(f"PPTX Error: {e}")
    return text

def extract_text_from_txt(file_stream):
    """[신규] 일반 텍스트 및 마크다운 파일 추출"""
    try:
        # UTF-8 시도 후 실패하면 CP949(한글 윈도우) 시도
        content = file_stream.read()
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            return content.decode('cp949')
    except Exception as e:
        print(f"TXT Error: {e}")
        return ""

def extract_text_from_csv(file_stream, filename):
    """[신규] CSV 파일 문맥화 추출"""
    text = ""
    try:
        content = file_stream.read()
        try:
            decoded = content.decode('utf-8')
        except UnicodeDecodeError:
            decoded = content.decode('cp949')
            
        f = io.StringIO(decoded)
        reader = csv.reader(f)
        rows = list(reader)
        
        if not rows: return ""
        
        headers = rows[0]
        for row in rows[1:]:
            row_parts = []
            for i, val in enumerate(row):
                if i < len(headers) and val.strip():
                    row_parts.append(f"{headers[i]}: {val.strip()}")
            if row_parts:
                text += f"[{filename}] " + ", ".join(row_parts) + "\n"
    except Exception as e: print(f"CSV Error: {e}")
    return text

def extract_text_from_image(file_stream):
    """이미지 OCR 추출 (한글+영어)"""
    text = ""
    try:
        image = Image.open(file_stream)
        text = pytesseract.image_to_string(image, lang='kor+eng')
    except Exception as e: print(f"OCR Error: {e}")
    return text

# ==================== 메인 로직 ====================

def init_vector_store():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    supabase_client = create_client(supabase_url, supabase_key)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    return {'supabase_client': supabase_client, 'embeddings': embeddings}

def sync_drive_to_db(folder_id, supabase_client):
    import google.auth
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    # 1. 구글 인증 및 파일 목록 조회
    creds, _ = google.auth.default()
    service = build('drive', 'v3', credentials=creds)

    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, mimeType)"
    ).execute()
    files = results.get('files', [])

    st.write(f"🔍 총 {len(files)}개의 파일 감지됨. 처리 시작...")

    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vector_store = SupabaseVectorStore(
        client=supabase_client,
        embedding=embeddings,
        table_name="documents",
        query_name="match_documents"
    )

    success_count = 0
    progress_bar = st.progress(0)
    
    # 지원 확장자 목록
    SUPPORTED_EXTENSIONS = [
        'pdf', 'docx', 'xlsx', 'pptx', 'txt', 'csv', 'md', 
        'jpg', 'jpeg', 'png'
    ]
    
    for i, file in enumerate(files):
        file_id = file['id']
        file_name = file['name']
        ext = file_name.split('.')[-1].lower() if '.' in file_name else ""
        
        progress_bar.progress((i + 1) / len(files))
        
        if ext not in SUPPORTED_EXTENSIONS:
            st.warning(f"⏩ [Skip] 미지원 파일: {file_name}")
            continue

        try:
            # 다운로드
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            fh.seek(0)
            
            text_content = ""
            
            # [확장자별 분기 처리]
            if ext == 'pdf':
                text_content = extract_text_from_pdf(fh)
            elif ext == 'docx':
                text_content = extract_text_from_docx(fh)
            elif ext == 'xlsx':
                text_content = extract_text_from_xlsx(fh, file_name)
            elif ext == 'pptx':
                text_content = extract_text_from_pptx(fh)
            elif ext in ['txt', 'md']:
                text_content = extract_text_from_txt(fh)
            elif ext == 'csv':
                text_content = extract_text_from_csv(fh, file_name)
            elif ext in ['jpg', 'jpeg', 'png']:
                text_content = extract_text_from_image(fh)

            # 내용 검증
            if not text_content or not text_content.strip():
                st.error(f"⚠️ [내용 없음] {file_name} (텍스트 추출 실패)")
                continue

            # 전처리 (헤더/문맥 주입)
            enriched_text = preprocess_text_with_section_headers(text_content)
            
            # 청크 분할 및 저장
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            chunks = text_splitter.split_text(enriched_text)
            
            docs = []
            for chunk in chunks:
                docs.append(Document(
                    page_content=chunk,
                    metadata={"source": file_name, "created_at": datetime.now().isoformat()}
                ))

            vector_store.add_documents(docs)
            st.success(f"✅ [완료] {file_name}")
            success_count += 1
            
        except Exception as e:
            st.error(f"❌ [에러] {file_name}: {e}")

    progress_bar.empty()
    return success_count

# ==================== 검색 및 유틸리티 함수 ====================

def search_similar_documents(query, supabase_client, embeddings, top_k=5):
    vector_store = SupabaseVectorStore(
        client=supabase_client,
        embedding=embeddings,
        table_name="documents",
        query_name="match_documents"
    )
    
    docs_with_score = vector_store.similarity_search_with_relevance_scores(query, k=top_k)
    
    filtered_docs = []
    filtered_infos = []
    
    for doc, score in docs_with_score:
        if score < 0.3: continue
        
        filtered_docs.append(doc)
        filtered_infos.append({
            "content": doc.page_content,
            "filename": doc.metadata.get("source", "Unknown"),
            "score": score
        })
        
    return filtered_docs, filtered_infos

def reset_database(supabase_client):
    try:
        supabase_client.table("documents").delete().neq("id", 0).execute()
        return True
    except:
        return False