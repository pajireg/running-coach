# 3.14 호환성 이슈를 피하기 위해 안정적인 파이썬 버전 사용
FROM python:3.12-slim

WORKDIR /app

# 의존성 설치
RUN apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 파일 복사
COPY . .

# .garmin_tokens 디렉토리가 있는지 확인
RUN mkdir -p .garmin_tokens

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Seoul
ENV GARMINTOKENS=/app/.garmin_tokens

# 기본적으로 서비스 모드로 실행 (매일 오전 6시 체크)
# 환경 변수에 따라 명령어를 구성하기 위해 쉘 형태로 실행
CMD python garmin_coach.py --service --hour 6 $( [ "$INCLUDE_STRENGTH" = "true" ] && echo "--include-strength" )
