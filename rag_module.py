"""
RAG Module for Document Processing and Vector Store Management
"""

import os
import io
import json
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# LangChain
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Supabase
from supabase.client import Client, create_client

# Google Drive API
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Document loaders
from pypdf import PdfReader
from docx import Document as DocxDocument
import openpyxl

# Numpy for similarity calculation
import numpy as np

# 현재 스크립트의 디렉토리에서 .env 파일 로드
env_path = Path(__file__).parent / ".env"
print(f"DEBUG: .env 파일 경로: {env_path}")
print(f"DEBUG: .env 파일 존재 여부: {env_path.exists()}")
load_dotenv(dotenv_path=env_path, override=True)

def init_vector_store():
    """
    Supabase 클라이언트와 Gemini Embedding 초기화

    Returns:
        dict: {'supabase_client': Client, 'embeddings': GoogleGenerativeAIEmbeddings}
    """
    # 환경 변수 가져오기
    google_api_key = os.getenv("GOOGLE_API_KEY")
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    # 환경 변수 검증
    if not google_api_key:
        raise ValueError("GOOGLE_API_KEY가 설정되지 않았습니다.")
    if not supabase_url:
        raise ValueError("SUPABASE_URL이 설정되지 않았습니다.")
    if not supabase_key:
        raise ValueError("SUPABASE_KEY가 설정되지 않았습니다.")

    print(f"[OK] 환경 변수 로드 완료")
    print(f"  - Supabase URL: {supabase_url}")
    print(f"  - Google API Key: {google_api_key[:10]}...")

    # Supabase 클라이언트 생성
    supabase_client: Client = create_client(supabase_url, supabase_key)
    print(f"[OK] Supabase 클라이언트 생성 완료")

    # Gemini Embedding 모델 초기화 (text-embedding-004)
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/text-embedding-004",
        google_api_key=google_api_key
    )
    print(f"[OK] Gemini Embedding 모델 초기화 완료 (models/text-embedding-004)")

    return {
        'supabase_client': supabase_client,
        'embeddings': embeddings
    }


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """
    두 벡터 간의 코사인 유사도 계산

    Args:
        vec1: 첫 번째 벡터
        vec2: 두 번째 벡터

    Returns:
        코사인 유사도 (0~1, 1에 가까울수록 유사)
    """
    dot_product = np.dot(vec1, vec2)
    norm_vec1 = np.linalg.norm(vec1)
    norm_vec2 = np.linalg.norm(vec2)

    if norm_vec1 == 0 or norm_vec2 == 0:
        return 0.0

    return dot_product / (norm_vec1 * norm_vec2)


def extract_keywords(query: str):
    """
    쿼리에서 핵심 키워드 추출 (간단한 방식)
    - 2글자 이상의 단어만 추출
    - 불용어 제거 (조사, 어미 등)
    """
    # 한글/영문/숫자만 추출
    import re
    words = re.findall(r'[가-힣a-zA-Z0-9]+', query)

    # 불용어 목록 (한글 조사/어미 등)
    stopwords = {'은', '는', '이', '가', '을', '를', '의', '에', '에서', '로', '으로',
                 '와', '과', '도', '만', '께서', '부터', '까지', '에게', '한테',
                 '이다', '있다', '없다', '하다', '되다', '않다', '못하다',
                 '어떻게', '무엇', '언제', '어디', '누가', '왜', '어느'}

    # 2글자 이상이고 불용어가 아닌 단어만 추출
    keywords = [w for w in words if len(w) >= 2 and w not in stopwords]

    return keywords


def rewrite_query_with_context(query: str, chat_history: List[tuple] = None, google_api_key: str = None):
    """
    Query Rewriting: 대화 맥락을 고려하여 독립적인 검색 질문으로 변환

    Args:
        query: 현재 사용자 질문
        chat_history: [(질문, 답변), ...] 형태의 대화 기록
        google_api_key: Google API Key (없으면 환경변수에서 가져옴)

    Returns:
        str: 맥락이 반영된 독립적인 검색 질문
    """
    try:
        if not google_api_key:
            google_api_key = os.getenv("GOOGLE_API_KEY")

        # 대화 기록이 없으면 원본 질문 반환
        if not chat_history or len(chat_history) == 0:
            print(f"[Query Rewriting] 대화 기록 없음 - 원본 질문 사용\n")
            return query

        import google.generativeai as genai
        genai.configure(api_key=google_api_key)

        # Gemini Flash 모델 사용
        model = genai.GenerativeModel('models/gemini-2.0-flash-exp')

        # 최근 3개 대화만 사용
        recent_history = chat_history[-3:] if len(chat_history) > 3 else chat_history

        # 대화 기록 포맷팅
        history_text = ""
        for i, (q, a) in enumerate(recent_history, 1):
            # 답변이 너무 길면 첫 200자만
            answer_preview = a[:200] + "..." if len(a) > 200 else a
            history_text += f"사용자: {q}\nAI: {answer_preview}\n\n"

        # Query Rewriting 프롬프트
        prompt = f"""당신은 검색 질의 재작성 전문가입니다.
이전 대화 내용을 참고하여, 현재 질문을 "독립적인 검색 질문"으로 변환하세요.

이전 대화:
{history_text}

현재 질문: {query}

규칙:
1. 현재 질문이 이전 대화를 참조한다면 ("그것", "이거", "위에서" 등) 명확한 명사로 대체
2. 현재 질문이 이미 독립적이면 그대로 반환
3. 핵심만 남기고 불필요한 말 제거
4. 한 문장으로 작성

독립적인 검색 질문:"""

        # Gemini 호출
        response = model.generate_content(prompt)
        rewritten_query = response.text.strip()

        print(f"[Query Rewriting] 원본: '{query}'")
        print(f"[Query Rewriting] 재작성: '{rewritten_query}'\n")

        return rewritten_query

    except Exception as e:
        print(f"[WARNING] Query Rewriting 실패: {str(e)}")
        print(f"[WARNING] 원본 쿼리로 검색 진행\n")
        return query


def search_similar_documents(query: str, supabase_client: Client, embeddings: GoogleGenerativeAIEmbeddings, top_k: int = 10, min_keyword_count: int = 2, chat_history: List[tuple] = None):
    """
    Hybrid 검색: Query Rewriting + 벡터 유사도 + 키워드 필터링 조합

    [대화 맥락 기반 검색]
    - Query Rewriting: 대화 맥락을 고려하여 독립적인 검색 질문으로 변환
    - 벡터 검색으로 k=10개 가져오기
    - 키워드 필터링(보정): 질문의 명사/키워드가 문서에 2회 이상 등장하면 강제 포함
    - 강화된 중복 제거: 파일명(source) + 내용(content) 기준으로 중복 제거

    Args:
        query: 검색 쿼리
        supabase_client: Supabase 클라이언트
        embeddings: Gemini Embeddings 객체
        top_k: 벡터 검색에서 가져올 문서 개수 (기본값: 10)
        min_keyword_count: 키워드 최소 출현 횟수 (기본값: 2)
        chat_history: [(질문, 답변), ...] 형태의 대화 기록

    Returns:
        tuple: (List[Document], List[dict]) - 문서 리스트와 유사도 정보 리스트
    """
    print("\n" + "="*70)
    print("[Hybrid 검색] Query Rewriting + 벡터 유사도 + 키워드 필터링")
    print("="*70)

    print(f"[검색] 원본 쿼리: '{query}'")

    # Query Rewriting: 대화 맥락 반영
    rewritten_query = rewrite_query_with_context(query, chat_history)

    # 재작성된 쿼리에서 키워드 추출
    keywords = extract_keywords(rewritten_query)
    print(f"[1] 추출된 키워드 ({len(keywords)}개): {keywords}")

    # 1. 재작성된 쿼리를 임베딩으로 변환
    query_embedding = embeddings.embed_query(rewritten_query)
    query_vec = np.array(query_embedding, dtype=float)
    print(f"[OK] 쿼리 임베딩 생성 완료 (차원: {len(query_vec)})")

    # 2. Supabase에서 모든 문서 가져오기
    try:
        response = supabase_client.table("documents").select("*").execute()
        all_docs = response.data
        print(f"[OK] 총 {len(all_docs)}개 문서 로드 완료")
    except Exception as e:
        print(f"[ERROR] 문서 로드 실패: {str(e)}")
        return [], []

    if not all_docs:
        print(f"[WARNING] 저장된 문서가 없습니다.")
        return [], []

    # 3. 각 문서와 쿼리 간의 코사인 유사도 계산
    results = []
    for doc in all_docs:
        if not doc.get('embedding'):
            continue

        # embedding 파싱
        embedding = doc['embedding']
        if isinstance(embedding, str):
            embedding = json.loads(embedding)

        doc_vec = np.array(embedding, dtype=float)

        # 코사인 유사도 계산
        similarity = cosine_similarity(query_vec, doc_vec)

        results.append({
            'id': doc['id'],
            'content': doc['content'],
            'metadata': doc.get('metadata', {}),
            'similarity': float(similarity)
        })

    # 4. 유사도 기준 내림차순 정렬
    results.sort(key=lambda x: x['similarity'], reverse=True)

    # 5. 벡터 검색: 상위 k개 선택
    vector_results = results[:top_k]
    print(f"\n[2] 벡터 검색 완료 - 상위 {len(vector_results)}개 선택")

    # 6. 키워드 필터링 (보정) - 유사도가 낮아도 키워드가 2회 이상 등장하면 포함
    print(f"\n[3] 키워드 필터링 시작 (최소 {min_keyword_count}회 출현)...")

    keyword_boosted = []
    for doc in results[top_k:]:  # 벡터 검색에서 누락된 문서들 검사
        content_lower = doc['content'].lower()

        # 각 키워드의 출현 횟수 계산
        total_keyword_count = 0
        for keyword in keywords:
            count = content_lower.count(keyword.lower())
            total_keyword_count += count

        # 키워드가 min_keyword_count회 이상 등장하면 추가
        if total_keyword_count >= min_keyword_count:
            doc['keyword_count'] = total_keyword_count
            keyword_boosted.append(doc)
            filename = doc['metadata'].get('source', 'Unknown')
            print(f"[Boosting] 키워드 {total_keyword_count}회 발견 - 강제 포함 (유사도: {doc['similarity']:.4f}, 파일: {filename})")

    print(f"[OK] 키워드 필터링 완료 - {len(keyword_boosted)}개 문서 추가")

    # 7. 벡터 결과 + 키워드 부스팅 결과 합치기
    combined_results = vector_results + keyword_boosted
    print(f"\n[4] 결과 합치기: {len(vector_results)}(벡터) + {len(keyword_boosted)}(키워드) = {len(combined_results)}개")

    # 8. 강화된 중복 제거 (De-duplication)
    # - 파일명(source) + 내용(content) 기준으로 중복 제거
    # - 동일 파일에서 동일 내용이 여러 번 나오는 경우 제거
    seen_items = set()
    deduplicated_results = []

    for result in combined_results:
        content = result['content'].strip()
        filename = result['metadata'].get('source', 'Unknown')

        # 파일명 + 내용 조합으로 고유 키 생성
        unique_key = f"{filename}||{content}"

        if unique_key in seen_items:
            continue

        seen_items.add(unique_key)
        deduplicated_results.append(result)

    duplicate_count = len(combined_results) - len(deduplicated_results)
    if duplicate_count > 0:
        print(f"[5] 중복 제거: {duplicate_count}개 중복 청크 제거 (파일명 + 내용 기준)")

    print(f"\n[최종] 검색된 청크 개수: {len(deduplicated_results)}개")
    print("="*70)
    print(f"{'순위':<6} {'유사도':<10} {'파일명'}")
    print("="*70)
    for i, result in enumerate(deduplicated_results[:15], 1):  # 상위 15개만 출력
        filename = result['metadata'].get('source', 'Unknown')
        score = result['similarity']
        keyword_mark = " [키워드]" if result.get('keyword_count') else ""
        print(f"{i:<6} {score:.4f}      {filename}{keyword_mark}")
    print("="*70 + "\n")

    # LangChain Document 형식으로 변환
    documents = [
        Document(
            page_content=result['content'],
            metadata=result['metadata']
        )
        for result in deduplicated_results
    ]

    # 유사도 정보를 별도 리스트로 반환
    similarity_info = [
        {
            'filename': result['metadata'].get('source', 'Unknown'),
            'score': result['similarity']
        }
        for result in deduplicated_results
    ]

    return documents, similarity_info


def test_vector_store():
    """
    Vector Store 테스트: 간단한 텍스트를 벡터화하여 DB에 저장
    """
    print("\n" + "="*60)
    print("Vector Store 테스트 시작")
    print("="*60 + "\n")

    try:
        # Vector Store 초기화
        vector_store = init_vector_store()

        print("\n" + "-"*60)
        print("테스트 데이터 저장 중...")
        print("-"*60 + "\n")

        # 테스트 데이터
        test_texts = [
            "테스트 데이터 1: 중소기업 업무 자동화 RAG 솔루션입니다.",
            "테스트 데이터 2: Google Gemini와 Supabase를 사용합니다.",
            "테스트 데이터 3: LangChain으로 RAG 시스템을 구축합니다."
        ]

        test_metadatas = [
            {"source": "test", "id": 1},
            {"source": "test", "id": 2},
            {"source": "test", "id": 3}
        ]

        # 벡터 DB에 저장
        ids = vector_store.add_texts(
            texts=test_texts,
            metadatas=test_metadatas
        )

        print(f"[OK] 테스트 데이터 저장 완료!")
        print(f"  - 저장된 문서 수: {len(ids)}")
        print(f"  - 문서 ID: {ids}")

        print("\n" + "-"*60)
        print("유사도 검색 테스트 중...")
        print("-"*60 + "\n")

        # 저장된 데이터 확인
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        supabase_client = create_client(supabase_url, supabase_key)

        print("\n[DEBUG] 저장된 모든 문서 조회:")
        all_docs = supabase_client.table("documents").select("id, content, metadata").execute()
        for doc in all_docs.data:
            print(f"  ID: {doc['id']}")
            print(f"  Content: {doc['content']}")
            print(f"  Metadata: {doc['metadata']}\n")

        # 유사도 검색 테스트
        query = "RAG 시스템"

        # 쿼리 텍스트를 벡터로 변환
        embeddings = GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004",
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
        query_vector = embeddings.embed_query(query)

        print(f"[DEBUG] 쿼리 벡터 차원: {len(query_vector)}")
        print(f"[DEBUG] 쿼리 벡터 샘플: {query_vector[:5]}")

        # Supabase RPC 함수를 직접 호출 (여러 방법 시도)
        print("\n[DEBUG] RPC 함수 호출 시도...")

        try:
            # 방법 1: 기본 호출
            results = supabase_client.rpc(
                "match_documents",
                {
                    "query_embedding": query_vector,
                    "match_threshold": 0.0,
                    "match_count": 5
                }
            ).execute()

            print(f"[DEBUG] RPC 응답: count={results.count}, data_length={len(results.data)}")

            # RPC가 성공했지만 결과가 없으면 대안 방법 사용
            if len(results.data) == 0:
                raise Exception("RPC returned empty results")

        except Exception as e:
            print(f"[DEBUG] RPC 결과 없음 또는 실패: {str(e)}")

            # 방법 2: postgrest를 사용한 직접 쿼리
            print("\n[DEBUG] 대안 방법: 모든 문서 가져와서 Python으로 유사도 계산...")

            # 모든 문서와 임베딩 가져오기
            all_docs_with_embedding = supabase_client.table("documents").select("*").limit(5).execute()

            if len(all_docs_with_embedding.data) > 0:
                print(f"[DEBUG] 가져온 문서 수: {len(all_docs_with_embedding.data)}")

                # 간단한 유사도 계산 (코사인 유사도)
                import numpy as np

                query_vec = np.array(query_vector)
                results_list = []

                for doc in all_docs_with_embedding.data:
                    if doc.get('embedding'):
                        # embedding이 문자열이면 파싱
                        embedding = doc['embedding']
                        if isinstance(embedding, str):
                            import json
                            embedding = json.loads(embedding)

                        doc_vec = np.array(embedding, dtype=float)
                        # 코사인 유사도 계산
                        similarity = 1 - np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec))
                        results_list.append({
                            'content': doc['content'],
                            'metadata': doc['metadata'],
                            'similarity': float(similarity)
                        })

                # 유사도 기준으로 정렬
                results_list.sort(key=lambda x: x['similarity'])
                results_data = results_list[:5]
            else:
                results_data = []
        else:
            results_data = results.data

        print(f"\n[OK] 검색 쿼리: '{query}'")
        print(f"[OK] 검색 결과 ({len(results_data)}개):\n")

        if len(results_data) > 0:
            for i, doc in enumerate(results_data, 1):
                print(f"  [{i}] {doc['content']}")
                print(f"      유사도: {doc['similarity']:.4f}")
                print(f"      메타데이터: {doc['metadata']}\n")
        else:
            print("  검색 결과가 없습니다.")

        print("="*60)
        print("[SUCCESS] 모든 테스트 통과!")
        print("="*60)

        return True

    except Exception as e:
        print(f"\n[ERROR] 테스트 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def authenticate_google_drive(credentials_path: str = "credentials.json"):
    """
    Google Drive API 인증
    Streamlit Cloud와 로컬 환경을 모두 지원

    Args:
        credentials_path: Service Account JSON 파일 경로

    Returns:
        Google Drive API service 객체
    """
    try:
        credentials = None

        # Streamlit Cloud에서는 st.secrets 사용
        try:
            import streamlit as st

            # secrets.toml이 없을 때 발생하는 예외 처리
            try:
                if "google_credentials" in st.secrets:
                    # Secrets에서 credentials 가져오기
                    credentials_dict = dict(st.secrets["google_credentials"])
                    credentials = service_account.Credentials.from_service_account_info(
                        credentials_dict,
                        scopes=['https://www.googleapis.com/auth/drive.readonly']
                    )
                    print(f"[OK] Google Drive 인증 완료 (Streamlit Secrets)")
            except Exception as secrets_error:
                # secrets.toml이 없거나 접근 불가 -> 로컬 파일로 fallback
                if "secrets" in str(secrets_error).lower():
                    print(f"[INFO] Streamlit Secrets 사용 불가, 로컬 파일 사용")
                else:
                    print(f"[WARNING] Secrets 접근 오류: {str(secrets_error)}")
                pass

        except ImportError:
            # Streamlit이 없으면 로컬 파일 사용
            print(f"[INFO] Streamlit 미설치, 로컬 파일 사용")
            pass

        # secrets 실패 또는 사용 불가시 로컬 파일 사용
        if credentials is None:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=['https://www.googleapis.com/auth/drive.readonly']
            )
            print(f"[OK] Google Drive 인증 완료 (로컬 파일: {credentials_path})")

        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        print(f"[ERROR] Google Drive 인증 실패: {str(e)}")
        raise


def list_drive_files(service, folder_id: str):
    """
    Google Drive 폴더의 파일 목록 가져오기

    Args:
        service: Google Drive API service 객체
        folder_id: Google Drive 폴더 ID

    Returns:
        파일 목록 (list of dict)
    """
    try:
        # 모든 파일을 가져옴 (MIME Type 필터 없음)
        query = f"'{folder_id}' in parents and trashed=false"

        print(f"[DEBUG] Google Drive 쿼리: {query}")

        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, size)",
            pageSize=1000  # 더 많은 파일 지원
        ).execute()

        all_files = results.get('files', [])
        print(f"\n[DEBUG] Google Drive에서 가져온 전체 파일: {len(all_files)}개")

        # 지원하는 파일 형식
        supported_extensions = ['.pdf', '.docx', '.xlsx', '.txt']
        supported_mime_types = [
            'application/pdf',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/plain'
        ]

        # 전체 파일 목록 출력 (디버깅용)
        print("\n[DEBUG] 감지된 모든 파일 (필터링 전):")
        for idx, file in enumerate(all_files, 1):
            file_name = file['name']
            mime_type = file['mimeType']
            file_size = file.get('size', 'N/A')

            # 확장자 확인
            has_supported_ext = any(file_name.lower().endswith(ext) for ext in supported_extensions)
            has_supported_mime = mime_type in supported_mime_types

            status = "[O] 지원됨" if (has_supported_ext or has_supported_mime) else "[X] 미지원"

            print(f"  [{idx}] {file_name}")
            print(f"      MIME Type: {mime_type}")
            print(f"      크기: {file_size} bytes")
            print(f"      상태: {status}")

        # 지원하는 파일만 필터링 (확장자 또는 MIME Type 기준)
        filtered_files = []
        for file in all_files:
            file_name = file['name']
            mime_type = file['mimeType']

            # 확장자 또는 MIME Type으로 필터링
            if any(file_name.lower().endswith(ext) for ext in supported_extensions) or \
               mime_type in supported_mime_types:
                filtered_files.append(file)

        print(f"\n[OK] 필터링 후 지원되는 파일: {len(filtered_files)}개")
        print(f"[OK] 필터링된 파일 목록:")
        for file in filtered_files:
            print(f"  [+] {file['name']} ({file['mimeType']})")

        return filtered_files

    except Exception as e:
        print(f"[ERROR] 파일 목록 가져오기 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        raise


def download_file_content(service, file_id: str, file_name: str, mime_type: str) -> str:
    """
    Google Drive 파일 다운로드 및 텍스트 추출

    Args:
        service: Google Drive API service 객체
        file_id: 파일 ID
        file_name: 파일 이름
        mime_type: 파일 MIME 타입

    Returns:
        추출된 텍스트
    """
    try:
        print(f"  [DEBUG] 파일 다운로드 시작: {file_name}")

        # 파일 다운로드
        request = service.files().get_media(fileId=file_id)
        file_buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(file_buffer, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        file_buffer.seek(0)
        file_size = file_buffer.getbuffer().nbytes
        print(f"  [DEBUG] 다운로드 완료: {file_size} bytes")

        # 파일 형식별 텍스트 추출
        text = ""

        # PDF 파일
        if mime_type == 'application/pdf' or file_name.lower().endswith('.pdf'):
            print(f"  [DEBUG] PDF 파일 처리 중...")
            pdf_reader = PdfReader(file_buffer)
            print(f"  [DEBUG] PDF 페이지 수: {len(pdf_reader.pages)}")

            for page_num, page in enumerate(pdf_reader.pages, 1):
                page_text = page.extract_text()
                text += page_text + "\n"
                print(f"  [DEBUG] 페이지 {page_num}: {len(page_text)}자 추출")

            if not text.strip():
                print(f"  [경고] PDF에서 텍스트를 추출하지 못했습니다 (OCR 필요 가능성)")
                print(f"  [경고] 스캔된 이미지 PDF이거나 텍스트 레이어가 없는 PDF일 수 있습니다")

        # DOCX 파일
        elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' or file_name.lower().endswith('.docx'):
            doc = DocxDocument(file_buffer)
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"

        # XLSX 파일
        elif mime_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or file_name.lower().endswith('.xlsx'):
            workbook = openpyxl.load_workbook(file_buffer)
            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                text += f"\n=== {sheet_name} ===\n"
                for row in sheet.iter_rows(values_only=True):
                    row_text = "\t".join([str(cell) if cell is not None else "" for cell in row])
                    text += row_text + "\n"

        # 일반 텍스트 파일
        elif mime_type.startswith('text/') or file_name.lower().endswith('.txt'):
            text = file_buffer.read().decode('utf-8', errors='ignore')

        else:
            print(f"  [WARNING] 지원하지 않는 파일 형식: {mime_type}")
            return ""

        print(f"  [OK] 텍스트 추출 완료: {len(text)} 글자")
        return text

    except Exception as e:
        print(f"  [ERROR] 파일 다운로드/추출 실패: {str(e)}")
        return ""


def sync_drive_to_db(folder_id: str = None, credentials_path: str = "credentials.json"):
    """
    Google Drive 폴더의 파일들을 Supabase Vector Store에 동기화

    Args:
        folder_id: Google Drive 폴더 ID (None이면 .env에서 가져옴)
        credentials_path: Service Account JSON 파일 경로

    Returns:
        동기화된 문서 수
    """
    print("\n" + "="*60)
    print("Google Drive -> Supabase 동기화 시작")
    print("="*60 + "\n")

    try:
        # 폴더 ID 설정
        if folder_id is None:
            folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
            if not folder_id:
                raise ValueError("GOOGLE_DRIVE_FOLDER_ID가 설정되지 않았습니다.")

        print(f"[INFO] 폴더 ID: {folder_id}")

        # Google Drive 인증
        service = authenticate_google_drive(credentials_path)

        # Supabase 및 Embeddings 초기화 (파일 목록 가져오기 전에 초기화)
        vector_store = init_vector_store()
        supabase_client = vector_store['supabase_client']
        embeddings = vector_store['embeddings']

        # 파일 목록 가져오기
        files = list_drive_files(service, folder_id)

        print(f"\n[증분 동기화] 총 감지된 파일: {len(files)}개")

        if not files:
            print("\n[INFO] 동기화할 파일이 없습니다.")
            return 0

        # 기존 파일 확인 - DB에 이미 저장된 파일명 목록 가져오기
        print(f"\n[증분 동기화] DB에서 기존 파일 목록 확인 중...")
        try:
            response = supabase_client.table("documents").select("metadata").execute()
            existing_files = set()

            for doc in response.data:
                metadata = doc.get('metadata', {})
                source = metadata.get('source', '')
                if source:
                    existing_files.add(source)

            print(f"[증분 동기화] 이미 DB에 있음 (건너뜀): {len(existing_files)}개")
            if existing_files:
                print(f"[DEBUG] 기존 파일 목록:")
                for idx, filename in enumerate(sorted(existing_files), 1):
                    print(f"  [{idx}] {filename}")

        except Exception as e:
            print(f"[WARNING] 기존 파일 목록 조회 실패: {str(e)}")
            print(f"[WARNING] 모든 파일을 새로 처리합니다.")
            existing_files = set()

        # 비교 (Filtering) - 새로운 파일만 필터링
        new_files = []
        skipped_files = []

        for file in files:
            file_name = file['name']
            if file_name in existing_files:
                skipped_files.append(file_name)
            else:
                new_files.append(file)

        print(f"\n[증분 동기화] 새로 추가 작업: {len(new_files)}개")
        if new_files:
            print(f"[DEBUG] 새로운 파일 목록:")
            for idx, file in enumerate(new_files, 1):
                print(f"  [{idx}] {file['name']}")

        if skipped_files:
            print(f"\n[DEBUG] 건너뛴 파일 ({len(skipped_files)}개):")
            for idx, filename in enumerate(skipped_files, 1):
                print(f"  [{idx}] {filename}")

        if not new_files:
            print("\n[INFO] 새로 추가할 파일이 없습니다. 모든 파일이 이미 동기화되어 있습니다.")
            return 0

        # files 변수를 new_files로 대체 (이후 로직은 동일)
        files = new_files

        # 텍스트 스플리터 설정
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len
        )
        print(f"[OK] 텍스트 스플리터 초기화 (chunk_size=1000, overlap=200)")

        total_chunks = 0
        processed_files = 0
        pdf_count = 0
        docx_count = 0
        xlsx_count = 0
        txt_count = 0

        # 각 파일 처리
        print(f"\n{'='*60}")
        print("파일 처리 시작")
        print(f"{'='*60}\n")

        for idx, file in enumerate(files, 1):
            file_name = file['name']
            mime_type = file['mimeType']

            print(f"\n[{idx}/{len(files)}] 처리 중: {file_name}")
            print(f"  - MIME Type: {mime_type}")

            # 파일 타입 카운트
            if mime_type == 'application/pdf' or file_name.lower().endswith('.pdf'):
                pdf_count += 1
                print(f"  [INFO] PDF 파일 감지!")
            elif mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' or file_name.lower().endswith('.docx'):
                docx_count += 1
            elif mime_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or file_name.lower().endswith('.xlsx'):
                xlsx_count += 1
            elif 'text/' in mime_type or file_name.lower().endswith('.txt'):
                txt_count += 1

            # 텍스트 추출
            text = download_file_content(service, file['id'], file_name, mime_type)

            # 텍스트 검증
            if not text:
                print(f"  [SKIP] 텍스트 추출 실패 - 빈 문자열 반환")
                print(f"  [경고] 이유: download_file_content()가 빈 문자열을 반환했습니다")
                continue

            if not text.strip():
                print(f"  [SKIP] 텍스트 없음")
                print(f"  [경고] 텍스트 없음 (OCR 필요 가능성) - 파일이 스캔된 이미지이거나 보호된 PDF일 수 있습니다")
                print(f"  [경고] 추출된 텍스트 길이: {len(text)}자 (공백 제거 후: {len(text.strip())}자)")
                continue

            print(f"  [OK] 텍스트 추출 성공: {len(text)}자")
            print(f"  [DEBUG] 텍스트 미리보기: {text[:100]}...")

            # 청크로 분할
            chunks = text_splitter.split_text(text)
            print(f"  [OK] {len(chunks)}개 청크로 분할")

            # 각 청크를 벡터화하여 Supabase에 직접 저장
            for i, chunk in enumerate(chunks):
                try:
                    # 청크를 임베딩으로 변환
                    chunk_embedding = embeddings.embed_query(chunk)

                    # Supabase에 직접 삽입
                    supabase_client.table("documents").insert({
                        "content": chunk,
                        "metadata": {
                            "source": file['name'],
                            "file_id": file['id'],
                            "mime_type": file['mimeType'],
                            "chunk_index": i
                        },
                        "embedding": chunk_embedding
                    }).execute()

                except Exception as e:
                    print(f"  [ERROR] 청크 {i} 저장 실패: {str(e)}")
                    continue

            print(f"  [OK] {len(chunks)}개 청크 저장 완료")
            total_chunks += len(chunks)
            processed_files += 1

        print("\n" + "="*60)
        print(f"[SUCCESS] 동기화 완료!")
        print(f"  - 처리된 파일: {processed_files}개")
        print(f"    • PDF: {pdf_count}개")
        print(f"    • DOCX: {docx_count}개")
        print(f"    • XLSX: {xlsx_count}개")
        print(f"    • TXT: {txt_count}개")
        print(f"  - 저장된 청크: {total_chunks}개")
        print("="*60)

        # PDF 파일 처리 결과 강조
        if pdf_count > 0:
            print(f"\n[SUCCESS] PDF 파일 {pdf_count}개가 추가되었습니다!")

        return total_chunks

    except Exception as e:
        print(f"\n[ERROR] 동기화 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0


def get_indexed_documents(supabase_client: Client):
    """
    Supabase에 저장된 문서 목록 가져오기

    Args:
        supabase_client: Supabase 클라이언트

    Returns:
        dict: {
            'total_chunks': int,  # 총 청크 수
            'unique_files': list,  # 유니크한 파일명 리스트
            'file_count': int  # 유니크 파일 개수
        }
    """
    try:
        # 모든 documents 조회
        response = supabase_client.table("documents").select("metadata").execute()

        if not response.data:
            return {
                'total_chunks': 0,
                'unique_files': [],
                'file_count': 0
            }

        # metadata에서 source 추출
        file_names = []
        for doc in response.data:
            metadata = doc.get('metadata', {})
            if isinstance(metadata, dict):
                source = metadata.get('source', 'Unknown')
            else:
                source = 'Unknown'
            file_names.append(source)

        # 중복 제거 (set 사용)
        unique_files = sorted(list(set(file_names)))

        return {
            'total_chunks': len(response.data),
            'unique_files': unique_files,
            'file_count': len(unique_files)
        }

    except Exception as e:
        print(f"[ERROR] 문서 목록 조회 실패: {str(e)}")
        return {
            'total_chunks': 0,
            'unique_files': [],
            'file_count': 0
        }


def reset_database(supabase_client: Client):
    """
    documents 테이블 완전 초기화 (모든 데이터 삭제)

    Args:
        supabase_client: Supabase 클라이언트

    Returns:
        bool: 성공 여부
    """
    try:
        print("\n" + "="*60)
        print("[WARNING] 데이터베이스 초기화 시작...")
        print("="*60)

        # 기존 데이터 개수 확인
        response = supabase_client.table("documents").select("id", count="exact").execute()
        existing_count = response.count if response.count else 0

        print(f"[INFO] 삭제할 문서: {existing_count}개")

        if existing_count == 0:
            print("[INFO] 삭제할 데이터가 없습니다.")
            print("="*60 + "\n")
            return True

        # 모든 문서 삭제 (Supabase에는 TRUNCATE가 없으므로 조건 없이 DELETE)
        # 주의: 대량 삭제는 시간이 걸릴 수 있음
        print(f"[INFO] 삭제 중... (시간이 걸릴 수 있습니다)")

        # 모든 레코드 삭제 (neq 조건으로 모든 행 선택)
        supabase_client.table("documents").delete().neq("id", 0).execute()

        # 삭제 후 확인
        response_after = supabase_client.table("documents").select("id", count="exact").execute()
        remaining_count = response_after.count if response_after.count else 0

        print(f"[SUCCESS] 데이터베이스 초기화 완료!")
        print(f"  - 삭제된 문서: {existing_count}개")
        print(f"  - 남은 문서: {remaining_count}개")
        print("="*60 + "\n")

        return True

    except Exception as e:
        print(f"[ERROR] 데이터베이스 초기화 실패: {str(e)}")
        import traceback
        traceback.print_exc()
        print("="*60 + "\n")
        return False


if __name__ == "__main__":
    # 테스트 실행
    # test_vector_store()

    # Google Drive 동기화 테스트
    sync_drive_to_db()
