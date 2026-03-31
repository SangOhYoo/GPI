import sys
import os
import json
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.getcwd())

from gpi.core.config import HISTORY_IMAGES_DIR, BASE_DIR
from gpi.core.prompt import delete_history_item_files

def verify():
    print("--- 히스토리 이미지 삭제 기능 검증 시작 ---")
    
    # 1. 테스트용 더미 이미지 생성
    test_image_name = "test_del_image.png"
    test_image_path = HISTORY_IMAGES_DIR / test_image_name
    test_image_path.write_text("dummy image data")
    print(f"테스트용 이미지 생성됨: {test_image_path}")
    
    # 2. 더미 내역 생성
    rel_path = test_image_path.relative_to(BASE_DIR)
    entry = {
        "en": "Test prompt",
        "ko": "테스트 프롬프트",
        "image_path": str(rel_path)
    }
    print(f"테스트용 항목 데이터: {entry}")
    
    # 3. 삭제 함수 호출
    print("delete_history_item_files 호출 중...")
    result = delete_history_item_files(entry)
    
    # 4. 결과 확인
    if result:
        print("결과: True 반환됨")
    else:
        print("결과: False 반환됨")
        
    if not test_image_path.exists():
        print("성공: 이미지 파일이 정상적으로 삭제되었습니다.")
    else:
        print("실패: 이미지 파일이 아직 존재합니다.")
        
    print("--- 검증 종료 ---")

if __name__ == "__main__":
    try:
        verify()
    except Exception as e:
        print(f"검증 중 오류 발생: {e}")
