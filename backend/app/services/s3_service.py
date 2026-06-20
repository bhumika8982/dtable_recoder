"""AWS S3 storage for recordings, audio, transcripts, MOM docs, and exports.

Uses boto3. All blocking S3 calls are wrapped with ``run_in_executor`` so they
don't block the FastAPI event loop. Supports a custom endpoint URL for MinIO /
LocalStack during local development.
"""
from __future__ import annotations

import asyncio
import io
from functools import partial
from typing import Optional

import boto3
from botocore.config import Config

from app.config import settings


class S3Service:
    def __init__(self, bucket: Optional[str] = None):
        self.bucket = bucket or settings.s3_bucket
        self._client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            endpoint_url=settings.s3_endpoint_url or None,
            config=Config(
                signature_version="s3v4",
                # Retry transient network drops (e.g. TLS EOF mid multipart upload)
                # that are common on unstable connections.
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=30,
                read_timeout=120,
            ),
        )

    async def _run(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def upload_file(self, local_path: str, key: str, content_type: str | None = None) -> str:
        extra = {"ContentType": content_type} if content_type else None
        await self._run(self._client.upload_file, local_path, self.bucket, key, ExtraArgs=extra)
        return key

    async def upload_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        await self._run(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=io.BytesIO(data),
            ContentType=content_type,
        )
        return key

    async def download_file(self, key: str, local_path: str) -> str:
        await self._run(self._client.download_file, self.bucket, key, local_path)
        return local_path

    async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return await self._run(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist (useful for local MinIO)."""
        try:
            await self._run(self._client.head_bucket, Bucket=self.bucket)
        except Exception:
            await self._run(self._client.create_bucket, Bucket=self.bucket)
