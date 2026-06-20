"""S3 helper for the meeting-bot flow.

Thin wrapper over the existing, retry-enabled ``app.services.s3_service.S3Service``
that enforces the meeting-bot key layout and returns presigned URLs (so private
buckets are never exposed directly).
"""
from __future__ import annotations

import logging

from app.meeting_bot import models as M
from app.services.s3_service import S3Service as BaseS3

logger = logging.getLogger(__name__)


class MeetingBotS3:
    def __init__(self) -> None:
        self._s3 = BaseS3()

    async def upload_file(self, local_path: str, kind: str, meeting_id: str, content_type: str) -> str:
        key = M.s3_key(kind, meeting_id)
        await self._s3.upload_file(local_path, key, content_type=content_type)
        logger.info("S3 upload OK: %s", key)
        return key

    async def upload_bytes(self, data: bytes, kind: str, meeting_id: str, content_type: str) -> str:
        key = M.s3_key(kind, meeting_id)
        await self._s3.upload_bytes(data, key, content_type)
        logger.info("S3 upload OK: %s", key)
        return key

    async def download_to(self, kind: str, meeting_id: str, local_path: str) -> str:
        key = M.s3_key(kind, meeting_id)
        await self._s3.download_file(key, local_path)
        return local_path

    async def presigned_url(self, kind: str, meeting_id: str, expires_in: int = 3600) -> str:
        return await self._s3.presigned_url(M.s3_key(kind, meeting_id), expires_in=expires_in)
