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

# ==================== [라이브러리 로드 체크] ====================
try:
    import pypdf
    import docx
    import openpyxl
    from pptx import Presentation
    from PIL import Image
    import pytesseract
except ImportError as e:
    raise ImportError(f"필수 라이브러리 부족: {e}")

# ==================== [텍스트 전처리 및 섹션 인식] ====================
def preprocess_text_with_section_headers(text):
    lines = text.split('\n')
    processed_lines = []
    current_section = "일반"
    header_pattern = re.compile(r'^\s*제\s*\d+\s*(조|장)')

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line: continue
        
        # 이미 태그가 있으면(엑셀/PPT 등) 유지
        if stripped_line.startswith('[') and ']' in stripped_line:
            processed_lines.append(stripped_line)
            continue

        if header_pattern.match(stripped_line):
            current_section = stripped_line
            processed_lines.append(line)
        else:
            enriched_line = f"[{current_section}] {stripped_line}"
            processed_lines.append(enriched_line)
    return "\n".join(processed_lines)

# ==================== [파일 포맷별 텍스트 추출] ====================
def extract_text_from_pdf(fh):
    text = ""
    try:
        reader = pypdf.PdfReader(fh)
        for page in reader.pages:
            t = page.extract_text()
            if t: text += t + "\n"
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
                if parts:
                    text += f"[{fname}-{sname}] " + ", ".join(parts) + "\n"
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
            if stext:
                text += f"[슬라이드 {i+1}] " + "\n".join(stext) + "\n"
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
            if parts:
                text += f"[{fname}] " + ", ".join(parts) + "\n"
    except Exception as e: print(f"CSV Error: {e}")
    return text

def extract_text_from_image(fh):
    text = ""
    try:
        img = Image.open(fh)
        text = pytesseract.image_to_string(img, lang='kor+eng')
    except Exception as e: print(f"OCR Error: {e}")
    return text

# ==================== [핵심 로직: Supabase 연결 및 동기화] ====================

def init_vector_store():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return {
        'supabase_client': create_client(url, key),
        'embeddings': GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    }

def sync_drive_to_db(folder_id, supabase_client):
    import google.auth
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    
    creds, _ = google.auth.default()
    service = build('drive', 'v3', credentials=creds)
    
    # 파일 목록 조회
    res = service.files().list(q=f"'{folder_id}' in parents and trashed=false", fields="files(id, name)").execute()
    files = res.get('files', [])
    
    st.write(f"🔍 폴더 내 파일 {len(files)}개 감지됨")
    
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vector_store = SupabaseVectorStore(client=supabase_client, embedding=embeddings, table_name="documents", query_name="match_documents")
    
    cnt = 0
    progress = st.progress(0)
    
    for i, f in enumerate(files):
        fid, fname = f['id'], f['name']
        ext = fname.split('.')[-1].lower() if '.' in fname else ""
        progress.progress((i+1)/len(files))
        
        # 지원 확장자 체크
        if ext not in ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'csv', 'md', 'jpg', 'jpeg', 'png']:
            st.warning(f"⏩ [Skip] {fname}")
            continue
            
        try:
            req = service.files().get_media(fileId=fid)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done: _, done = downloader.next_chunk()
            fh.seek(0)
            
            content = ""
            if ext == 'pdf': content = extract_text_from_pdf(fh)
            elif ext == 'docx': content = extract_text_from_docx(fh)
            elif ext == 'xlsx': content = extract_text_from_xlsx(fh, fname)
            elif ext == 'pptx': content = extract_text_from_pptx(fh)
            elif ext in ['txt', 'md']: content = extract_text_from_txt(fh)
            elif ext == 'csv': content = extract_text_from_csv(fh, fname)
            elif ext in ['jpg', 'png', 'jpeg']: content = extract_text_from_image(fh)
            
            if not content.strip():
                st.error(f"⚠️ {fname} 내용 없음")
                continue
                
            processed = preprocess_text_with_section_headers(content)
            splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            chunks = splitter.split_text(processed)
            
            docs = [Document(page_content=c, metadata={"source": fname, "created_at": datetime.now().isoformat()}) for c in chunks]
            vector_store.add_documents(docs)
            st.success(f"✅ {fname} 완료")
            cnt += 1
        except Exception as e:
            st.error(f"❌ {fname} 실패: {e}")
            
    progress.empty()
    return cnt

def search_similar_documents(query, client, embeddings, top_k=5):
    vs = SupabaseVectorStore(client=client, embedding=embeddings, table_name="documents", query_name="match_documents")
    res = vs.similarity_search_with_relevance_scores(query, k=top_k)
    docs, infos = [], []
    for d, s in res:
        if s < 0.3: continue
        docs.append(d)
        infos.append({"content": d.page_content, "filename": d.metadata.get("source"), "score": s})
    return docs, infos

# ==================== [🚨 누락되었던 함수 추가됨] ====================
def get_indexed_documents(client):
    """현재 인덱싱된 문서 목록 조회 (Placeholder)"""
    return []

def reset_database(client):
    """DB 초기화 함수"""
    try: 
        client.table("documents").delete().neq("id", 0).execute()
        return True
    except: 
        return False