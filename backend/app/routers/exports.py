"""Export MOM + extracted items as PDF or DOCX, and presign recordings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.deps import get_meeting_repo
from app.repositories.meeting_repo import MeetingRepository
from app.services.export_service import build_docx, build_pdf
from app.services.s3_service import S3Service

router = APIRouter(prefix="/api/meetings", tags=["exports"])

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _gather(meeting_id: str, repo: MeetingRepository):
    meeting = await repo.get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    mom = await repo.get_mom(meeting_id) or {}
    return meeting, mom


@router.get("/{meeting_id}/export.pdf")
async def export_pdf(meeting_id: str, repo: MeetingRepository = Depends(get_meeting_repo)):
    meeting, mom = await _gather(meeting_id, repo)
    data = build_pdf(meeting["title"], mom)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="meeting_{meeting_id}.pdf"'},
    )


@router.get("/{meeting_id}/export.docx")
async def export_docx(meeting_id: str, repo: MeetingRepository = Depends(get_meeting_repo)):
    meeting, mom = await _gather(meeting_id, repo)
    data = build_docx(meeting["title"], mom)
    return Response(
        content=data,
        media_type=_DOCX_MIME,
        headers={"Content-Disposition": f'attachment; filename="meeting_{meeting_id}.docx"'},
    )


@router.get("/{meeting_id}/recording-url")
async def recording_url(meeting_id: str, repo: MeetingRepository = Depends(get_meeting_repo)):
    meeting = await repo.get(meeting_id)
    if not meeting or not meeting.get("recording_s3_key"):
        raise HTTPException(status_code=404, detail="Recording not available")
    url = await S3Service().presigned_url(meeting["recording_s3_key"])
    return {"url": url}
