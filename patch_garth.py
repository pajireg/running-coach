import os
# 가민 라이브러리(garth)의 파이썬 3.14 호환성 문제를 해결하기 위한 패치 스크립트

# 수정이 필요한 파일 경로 (HRV 관련 데이터 모델)
file_path = "venv/lib/python3.14/site-packages/garth/data/hrv.py"

# 파일 내용 읽기
with open(file_path, "r") as f:
    content = f.read()

# 임포트 수정 (List 추가)
if "from typing import List" not in content:
    content = content.replace("from datetime import date, datetime", "from datetime import date, datetime\nfrom typing import List")

# 에러가 발생하는 라인 수정 (소문자 list를 대문자 List로 변경)
old_line = "hrv_readings: list[HRVReading]"
new_line = "hrv_readings: List[HRVReading]"

if old_line in content:
    content = content.replace(old_line, new_line)
    print("패치 성공: 'list[HRVReading]'을 'List[HRVReading]'으로 변경함.")
else:
    print("수정할 라인을 찾지 못함 (이미 패치되었을 수 있음).")

with open(file_path, "w") as f:
    f.write(content)

print("패치가 성공적으로 적용되었습니다.")
