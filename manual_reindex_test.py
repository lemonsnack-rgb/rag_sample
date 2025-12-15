"""
수동 재색인 테스트 - 1개 파일만 테스트

사용법:
    python manual_reindex_test.py
"""

import os
import sys
from supabase import create_client
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from dotenv import load_dotenv

# Windows 인코딩
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

def test_manual_insert():
    """수동 삽입 테스트"""
    print("=" * 80)
    print("🧪 수동 재색인 테스트")
    print("=" * 80)

    # Supabase 연결
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ SUPABASE_URL 또는 SUPABASE_KEY 없음")
        return

    client = create_client(url, key)
    print("✅ Supabase 연결 성공\n")

    # 임베딩 모델 초기화
    try:
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
        print("✅ 임베딩 모델 초기화 성공\n")
    except Exception as e:
        print(f"❌ 임베딩 모델 초기화 실패: {e}")
        return

    # 테스트 텍스트
    test_content = "제5조(휴가) 휴가는 연 15일이다."

    print(f"📝 테스트 텍스트: {test_content}")
    print(f"📏 텍스트 길이: {len(test_content)}자\n")

    # 임베딩 생성
    try:
        print("⏳ 임베딩 생성 중...")
        embedding_vector = embeddings.embed_query(test_content)
        print(f"✅ 임베딩 생성 완료: {len(embedding_vector)}차원\n")

        # PostgreSQL VECTOR 형식으로 변환
        vector_str = "[" + ",".join(map(str, embedding_vector)) + "]"
        print(f"📊 VECTOR 문자열 길이: {len(vector_str)}자")
        print(f"🔤 VECTOR 문자열 미리보기: {vector_str[:100]}...\n")

        # Supabase 삽입
        print("⏳ Supabase 삽입 중...")
        result = client.table("documents").insert({
            "content": test_content,
            "metadata": {
                "source": "test.txt",
                "section": "테스트",
                "file_type": "txt"
            },
            "embedding": vector_str
        }).execute()

        print("✅ 삽입 성공!")
        print(f"📦 삽입된 ID: {result.data[0]['id'] if result.data else 'N/A'}\n")

        # 삽입된 데이터 확인
        print("=" * 80)
        print("🔍 삽입 확인")
        print("=" * 80)

        check_result = client.table("documents").select("*").eq("content", test_content).execute()

        if check_result.data:
            doc = check_result.data[0]
            embedding_stored = doc.get('embedding', [])

            print(f"✅ 데이터 확인 성공")
            print(f"📄 내용: {doc['content']}")
            print(f"🧮 임베딩 차원: {len(embedding_stored)}차원")
            print(f"📊 임베딩 타입: {type(embedding_stored)}")

            if len(embedding_stored) == 768:
                print("\n✅✅✅ 성공! 768차원으로 정상 저장됨!")
            else:
                print(f"\n❌ 실패: {len(embedding_stored)}차원으로 저장됨")
        else:
            print("❌ 삽입 확인 실패")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_manual_insert()
