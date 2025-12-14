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
from supabase import create_client, Client # Client 임포트 추가

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

# ... (다른 함수 생략) ...

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
        # 클라이언트 생성 시 안정성 확보
        supabase_client: Client = create_client(url, key)
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        
        return {
            'supabase_client': supabase_client,
            'embeddings': embeddings
        }
    except Exception as e:
        print(f"Supabase 클라이언트 초기화 실패: {e}")
        raise

# ... (sync_drive_to_db 함수 생략) ...

# ... (search_similar_documents 함수 생략) ...

def reset_database(client):
    """
    Supabase DB의 documents 테이블 전체를 삭제합니다. (강제 초기화)
    """
    if client is None:
        print("Error: Supabase 클라이언트가 유효하지 않습니다.")
        return False
        
    try: 
        # delete().neq("id", 0)는 WHERE id != 0 구문으로, Supabase에서 전체 행을 삭제하는 가장 확실한 방법입니다.
        result = client.table("documents").delete().neq("id", 0).execute()
        # Supabase API 응답이 성공적인지 확인 (result.data가 []인지 확인)
        if result.data == []:
             print("DB 삭제 성공")
             return True
        else:
             print(f"DB 삭제 시도 응답에 데이터가 남아있음: {result.data}")
             return False
    except Exception as e: 
        print(f"DB Reset Error: {e}")
        return False