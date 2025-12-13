"""
Google Gemini API에서 사용 가능한 모델 목록 확인
"""

import os
from dotenv import load_dotenv
import google.generativeai as genai

# 환경 변수 로드
load_dotenv()

# API 키 설정
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("ERROR: GOOGLE_API_KEY가 설정되지 않았습니다.")
    exit(1)

genai.configure(api_key=api_key)

print("="*60)
print("사용 가능한 Google Gemini 모델 목록")
print("="*60 + "\n")

# 모든 모델 조회
models = genai.list_models()

print("전체 모델 목록:\n")
for model in models:
    print(f"모델 이름: {model.name}")
    print(f"  - Display Name: {model.display_name}")
    print(f"  - Supported Methods: {model.supported_generation_methods}")
    print()

print("\n" + "="*60)
print("텍스트 생성(generateContent) 지원 모델만 필터링")
print("="*60 + "\n")

text_models = []
for model in models:
    if 'generateContent' in model.supported_generation_methods:
        text_models.append(model.name)
        print(f"✓ {model.name}")
        print(f"  Display: {model.display_name}")
        print()

print("\n" + "="*60)
print("추천 모델")
print("="*60 + "\n")

# Flash 모델 찾기
flash_models = [m for m in text_models if 'flash' in m.lower()]
if flash_models:
    print("Flash 모델 (빠른 응답):")
    for m in flash_models:
        print(f"  - {m}")
    print()

# Pro 모델 찾기
pro_models = [m for m in text_models if 'pro' in m.lower() and 'vision' not in m.lower()]
if pro_models:
    print("Pro 모델 (균형잡힌 성능):")
    for m in pro_models:
        print(f"  - {m}")
    print()

# 최신 Flash 모델 추천
if flash_models:
    # latest가 있으면 우선, 없으면 숫자가 큰 것
    latest_flash = None
    for m in flash_models:
        if 'latest' in m.lower():
            latest_flash = m
            break

    if not latest_flash:
        # 버전 번호가 있는 것 중 선택
        flash_with_version = [m for m in flash_models if any(char.isdigit() for char in m)]
        if flash_with_version:
            latest_flash = sorted(flash_with_version)[-1]
        else:
            latest_flash = flash_models[0]

    print(f"\n추천 모델: {latest_flash}")
    print(f"  (가장 최신 Flash 모델)")
else:
    print(f"\n추천 모델: {pro_models[0] if pro_models else text_models[0]}")
    print(f"  (Flash 모델이 없어서 대체)")

print("\n" + "="*60)
