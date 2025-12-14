"""
DB 샘플 데이터 확인 스크립트 - 임베딩 품질 진단용

사용법:
    python debug_db_sample.py

출력:
    - DB 총 문서 수
    - 샘플 청크 5개 (page_content, metadata, 임베딩 벡터 norm)
    - 섹션 태그 포함 여부 확인
"""

import os
import sys
from supabase import create_client
from dotenv import load_dotenv

# Windows 인코딩 문제 해결
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()

def check_db_samples():
    """DB 샘플 데이터 확인"""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ SUPABASE_URL 또는 SUPABASE_KEY가 설정되지 않았습니다.")
        return

    client = create_client(url, key)

    # 1. 총 문서 수
    try:
        count_result = client.table("documents").select("id", count="exact").execute()
        total = count_result.count if hasattr(count_result, 'count') else len(count_result.data)
        print(f"\n📊 DB 총 문서 수: {total}개\n")
    except Exception as e:
        print(f"❌ 문서 수 확인 실패: {e}")
        return

    # 2. 샘플 데이터 5개 조회
    try:
        result = client.table("documents").select("content, metadata, embedding").limit(5).execute()

        print("=" * 80)
        print("📝 DB 샘플 데이터 (최근 5개)")
        print("=" * 80)

        for i, doc in enumerate(result.data, 1):
            content = doc.get('content', '')
            metadata = doc.get('metadata', {})
            embedding = doc.get('embedding', [])

            print(f"\n[샘플 {i}]")
            print(f"📄 출처: {metadata.get('source', 'N/A')}")
            print(f"📑 섹션: {metadata.get('section', 'N/A')}")
            print(f"📦 파일타입: {metadata.get('file_type', 'N/A')}")
            print(f"🕐 수정일: {metadata.get('last_modified', 'N/A')[:10] if metadata.get('last_modified') else 'N/A'}")
            print(f"📏 청크 길이: {len(content)}자")
            print(f"🧮 임베딩 차원: {len(embedding)}차원" if embedding else "❌ 임베딩 없음")

            # 섹션 태그 포함 여부 확인
            has_section_tag = content.startswith('[') and ']' in content[:50]
            print(f"🏷️  섹션 태그 포함: {'✅ YES' if has_section_tag else '❌ NO'}")

            # 내용 미리보기 (첫 200자)
            preview = content[:200] + "..." if len(content) > 200 else content
            print(f"\n💬 내용 미리보기:\n{preview}")
            print("-" * 80)

        # 3. 섹션 태그 포함 비율 확인
        print("\n" + "=" * 80)
        print("📊 섹션 태그 포함 통계")
        print("=" * 80)

        # 전체 문서 중 100개 샘플링하여 통계
        sample_result = client.table("documents").select("content").limit(100).execute()
        tagged_count = sum(1 for doc in sample_result.data
                          if doc.get('content', '').startswith('[') and ']' in doc.get('content', '')[:50])
        sample_total = len(sample_result.data)

        print(f"샘플 수: {sample_total}개")
        print(f"섹션 태그 포함: {tagged_count}개 ({tagged_count/sample_total*100:.1f}%)")
        print(f"섹션 태그 없음: {sample_total - tagged_count}개 ({(sample_total-tagged_count)/sample_total*100:.1f}%)")

        if tagged_count == 0:
            print("\n⚠️  경고: 섹션 태그가 하나도 없습니다!")
            print("→ 코드 수정 후 재색인하지 않은 것으로 보입니다.")
            print("→ 해결: DB 전체 삭제 → 전체 재색인 실행")
        elif tagged_count < sample_total * 0.5:
            print("\n⚠️  경고: 섹션 태그가 50% 미만입니다!")
            print("→ 일부만 재색인된 상태입니다.")
            print("→ 해결: DB 전체 삭제 → 전체 재색인 실행")
        else:
            print("\n✅ 섹션 태그 비율 정상")

    except Exception as e:
        print(f"❌ 샘플 조회 실패: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_db_samples()
