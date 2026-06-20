"""Tests for the S3 service with a stubbed boto3 client."""
import pytest

from app.services.s3_service import S3Service


class FakeBotoClient:
    def __init__(self):
        self.uploaded = {}
        self.objects = {}

    def upload_file(self, local_path, bucket, key, ExtraArgs=None):
        self.uploaded[key] = {"path": local_path, "extra": ExtraArgs}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = {"content_type": ContentType}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://s3.local/{Params['Key']}?exp={ExpiresIn}"


@pytest.fixture
def s3(monkeypatch):
    svc = S3Service.__new__(S3Service)
    svc.bucket = "test-bucket"
    svc._client = FakeBotoClient()
    return svc


@pytest.mark.asyncio
async def test_upload_file(s3):
    key = await s3.upload_file("/tmp/x.mp4", "meetings/1/rec.mp4", content_type="video/mp4")
    assert key == "meetings/1/rec.mp4"
    assert s3._client.uploaded[key]["extra"] == {"ContentType": "video/mp4"}


@pytest.mark.asyncio
async def test_upload_bytes(s3):
    key = await s3.upload_bytes(b"hello", "meetings/1/t.txt", "text/plain")
    assert s3._client.objects[key]["content_type"] == "text/plain"


@pytest.mark.asyncio
async def test_presigned_url(s3):
    url = await s3.presigned_url("meetings/1/rec.mp4", expires_in=60)
    assert "meetings/1/rec.mp4" in url and "exp=60" in url
