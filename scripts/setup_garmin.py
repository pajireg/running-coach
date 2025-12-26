import os
import getpass
from dotenv import load_dotenv
import garth

# 환경 변수 로드
load_dotenv()

def main():
    print("--- 가민 인증 설정 ---")
    print("이 스크립트는 로그인 에러를 방지하기 위해 세션 토큰을 로컬에 저장함")
    
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    
    if not email or not password:
        print(".env 파일에서 인증 정보를 확인해야 함")
        email = input("가민 이메일 입력: ")
        password = getpass.getpass("가민 비밀번호 입력: ")
    else:
        print(f"사용 중인 이메일: {email}")

    print("로그인 시도 중...")
    try:
        # garth.login은 콘솔 사용 시 자동으로 MFA(2단계 인증)를 처리함
        garth.login(email, password)
        
        token_dir = ".garmin_tokens"
        garth.save(token_dir)
        print(f"성공! 토큰이 '{token_dir}'에 저장됨")
        print("이제 'python garmin_coach.py'를 실행할 수 있음")
        
    except Exception as e:
        print(f"로그인 실패: {e}")
        # 401 에러인 경우 힌트 제공
        if "401" in str(e):
            print("이메일과 비밀번호를 다시 확인해봐")

if __name__ == "__main__":
    main()
