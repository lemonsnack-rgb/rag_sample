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

# ==================== [텍스트 전처리] ====================
def preprocess_text_with_section_headers(text):
    if text: text = text.replace('\x00', '') # Null 문자 제거
    lines = text.split('\n')
    processed_lines = []
    current_section = "일반"
    header_pattern = re.compile(r'^\s*제\s*\d+\s*(조|장)')

    for line in lines:
        stripped_line = line.strip()
        if not stripped_line: continue
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
                if parts: text += f"[{fname}-{sname}] " + ", ".join(parts) + "\n"
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
            if stext: text += f"[슬라이드 {i+1}] " + "\n".join(stext) + "\n"
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
            if parts: text += f"[{fname}] " + ", ".join(parts) + "\n"
    except Exception as e: print(f"CSV Error: {e}")
    return text

def extract_text_from_image(fh):
    text = ""
    try:
        img = Image.open(fh)
        text = pytesseract.image_to_string(img, lang='kor+eng')
    except Exception as e: print(f"OCR Error: {e}")
    return text

# ==================== [핵심 로직: Supabase 연결] ====================

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
    
    res = service.files().list(q=f"'{folder_id}' in parents and trashed=false", fields="files(id, name)").execute()
    files = res.get('files', [])
    
    st.write(f"🔍 폴더 내 파일 {len(files)}개 감지됨")
    
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    # 업로드는 LangChain 사용 (문제 없음)
    vector_store = SupabaseVectorStore(client=supabase_client, embedding=embeddings, table_name="documents", query_name="match_documents")
    
    cnt = 0
    progress = st.progress(0)
    
    for i, f in enumerate(files):
        fid, fname = f['id'], f['name']
        ext = fname.split('.')[-1].lower() if '.' in fname else ""
        progress.progress((i+1)/len(files))
        
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

# ==================== [핵심 수정: 검색 함수 (Native RPC 호출)] ====================
def search_similar_documents(query, client, embeddings, top_k=5):
    """
    LangChain wrapper를 사용하지 않고 Supabase Client를 직접 사용하여 검색합니다.
    (SyncRPCFilterRequestBuilder 에러 방지용)
    """
    try:
        # 1. 쿼리를 벡터로 변환
        query_vector = embeddings.embed_query(query)

        # 2. Supabase RPC 직접 호출
        params = {
            "query_embedding": query_vector,
            "match_threshold": 0.3, # 유사도 임계값
            "match_count": top_k
        }
        
        # .execute()를 사용하여 쿼리 실행
        response = client.rpc("match_documents", params).execute()
        
        # 3. 결과 데이터를 Document 객체로 변환
        docs = []
        infos = []
        
        # response.data는 리스트[딕셔너리] 형태
        for item in response.data:
            content = item.get("content", "")
            metadata = item.get("metadata", {})
            score = item.get("similarity", 0.0)
            
            # Document 객체 생성
            doc = Document(page_content=content, metadata=metadata)
            docs.append(doc)
            
            # 정보 딕셔너리 생성
            infos.append({
                "content": content,
                "filename": metadata.get("source", "Unknown"),
                "score": score
            })
            
        return docs, infos

    except Exception as e:
        print(f"Search Error: {e}")
        # 에러 발생 시 빈 리스트 반환하여 앱이 멈추지 않게 함
        return [], []

def get_indexed_documents(client):
    return []

def reset_database(client):
    try: 
        client.table("documents").delete().neq("id", 0).execute()
        return True
    except: 
        return False