"""Google Calendar 클라이언트"""
import os
from typing import Optional
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from ...config.constants import GOOGLE_SCOPES, GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE
from ...utils.logger import get_logger
from ...exceptions import CalendarAuthError, CalendarError
from .sync import CalendarSyncService

logger = get_logger(__name__)


class GoogleCalendarClient:
    """Google Calendar 클라이언트"""

    def __init__(
        self,
        credentials_path: Optional[Path] = None,
        token_path: Optional[Path] = None
    ):
        """
        Args:
            credentials_path: credentials.json 파일 경로
            token_path: token_google.json 파일 경로
        """
        self.credentials_path = credentials_path or GOOGLE_CREDENTIALS_FILE
        self.token_path = token_path or GOOGLE_TOKEN_FILE
        self._service = None
        self.sync_service: Optional[CalendarSyncService] = None

    def authenticate(self) -> Optional[any]:
        """OAuth 인증 및 서비스 객체 생성

        Returns:
            Google Calendar API 서비스 객체 또는 None
        """
        creds = None

        # 저장된 토큰이 있으면 로드
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), GOOGLE_SCOPES)
                logger.info("기존 토큰 로드 완료")
            except Exception as e:
                logger.warning(f"토큰 로드 실패: {e}")

        # 토큰이 없거나 유효하지 않으면 재인증
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info("토큰 갱신 완료")
                except Exception as e:
                    logger.warning(f"토큰 갱신 실패: {e}")
                    creds = None

            if not creds:
                # 새로 인증
                if not self.credentials_path.exists():
                    logger.warning(f"구글 인증 파일 '{self.credentials_path}'가 없음. 구글 캘린더 동기화를 건너뜁니다.")
                    return None

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), GOOGLE_SCOPES)
                    creds = flow.run_local_server(port=8080, open_browser=False)
                    logger.info("새로운 인증 완료")
                except Exception as e:
                    logger.error(f"인증 실패: {e}")
                    raise CalendarAuthError(f"Failed to authenticate: {e}") from e

            # 토큰 저장
            try:
                with open(self.token_path, "w") as token:
                    token.write(creds.to_json())
                logger.info(f"토큰 저장 완료: {self.token_path}")
            except Exception as e:
                logger.warning(f"토큰 저장 실패: {e}")

        # 서비스 객체 생성
        try:
            self._service = build("calendar", "v3", credentials=creds)
            self.sync_service = CalendarSyncService(self._service)
            logger.info("Google Calendar 서비스 생성 완료")
            return self._service

        except Exception as e:
            logger.error(f"구글 캘린더 서비스 생성 에러: {e}")
            raise CalendarError(f"Failed to create service: {e}") from e

    @property
    def service(self):
        """서비스 객체 반환 (없으면 인증)"""
        if not self._service:
            self.authenticate()
        return self._service

    @property
    def is_authenticated(self) -> bool:
        """인증 상태 확인"""
        return self._service is not None
