

def get_indexed_documents(supabase_client):
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
