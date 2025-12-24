import os
import glob

import glob

# 가민 라이브러리(garth)의 모든 데이터 모델 파일을 검사하여 파이썬 3.14 호환성 문제를 일괄 해결하는 스크립트
# 패키지 내 데이터 모델 디렉토리 경로
base_path = "venv/lib/python3.14/site-packages/garth/data/"
files = glob.glob(os.path.join(base_path, "*.py"))

print(f"검사할 파일 {len(files)}개를 찾았습니다: {base_path}")

for file_path in files:
    with open(file_path, "r") as f:
        content = f.read()

    original_content = content
    
    # 패치가 필요한지 확인 (소문자 list[ 형태가 있는지)
    if "list[" in content:
        print(f"패치 중: {os.path.basename(file_path)}...")
        
        # 임포트가 누락된 경우 추가
        if "from typing import List" not in content:
            # 임포트 구문 다음에 삽입 시도
            if "from datetime" in content:
                 content = content.replace("from datetime", "from typing import List\nfrom datetime")
            else:
                 content = "from typing import List\n" + content
        
        # list[...]를 List[...]로 교체
        # 대부분의 경우 단순 교체로 해결됨
        content = content.replace("list[", "List[")
        
        if content != original_content:
            with open(file_path, "w") as f:
                f.write(content)
            print(f"  -> 패치 완료.")
    else:
        print(f"건너뜀: {os.path.basename(file_path)} ('list[' 없음)")

print("모든 파일 처리가 완료되었습니다.")
