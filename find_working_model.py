"""
LangChain에서 작동하는 Gemini 모델 찾기
"""

import os
from dotenv import load_dotenv
from pathlib import Path
from langchain_google_genai import ChatGoogleGenerativeAI

# 환경 변수 로드
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

api_key = os.getenv("GOOGLE_API_KEY")

print("=" * 60)
print("LangChain에서 작동하는 Gemini 모델 찾기")
print("=" * 60)
print()

# 시도할 모델명 리스트
model_names = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro",
    "gemini-1.5-pro-latest",
    "gemini-pro",
    "gemini-pro-vision",
    "models/gemini-1.5-flash",
    "models/gemini-1.5-flash-latest",
    "models/gemini-1.5-pro",
    "models/gemini-pro",
]

working_models = []

for model_name in model_names:
    try:
        print(f"[TEST] {model_name}...", end=" ")
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.7
        )

        response = llm.invoke("Hi")
        print(f"[SUCCESS]")
        print(f"  응답: {response.content[:50]}...")
        working_models.append(model_name)
        print()

    except Exception as e:
        error_msg = str(e)
        if "NOT_FOUND" in error_msg:
            print(f"[404] 모델을 찾을 수 없음")
        elif "PERMISSION_DENIED" in error_msg:
            print(f"[403] 권한 없음")
        else:
            print(f"[ERROR] {error_msg[:60]}...")
        print()

print("=" * 60)
print("테스트 결과")
print("=" * 60)
print()

if working_models:
    print(f"[SUCCESS] 작동하는 모델 {len(working_models)}개 발견:")
    for model in working_models:
        print(f"  - {model}")
    print()
    print(f"[SOLUTION] app.py에서 다음 모델을 사용하세요:")
    print(f"  model=\"{working_models[0]}\"")
else:
    print("[ERROR] 작동하는 모델을 찾을 수 없습니다.")
    print()
    print("[해결 방법]")
    print("1. Google Cloud Console에서 Generative Language API 활성화 확인")
    print("2. API 키에 Generative Language API 권한 확인")
    print("3. 필요시 새 API 키 발급")

print()
print("=" * 60)
