"""Seed demo artifacts (transcript, MOM, extraction) for the most recent meeting.

Lets you see the UI fully populated without running the ML pipeline or spending
OpenAI credits. Reuses the app's own Mongo connection + repository so the stored
document shapes exactly match what the API/UI expect.

Run from the backend dir (so .env is picked up):
    python seed_demo.py
"""
from __future__ import annotations

import asyncio

from app.db.mongo import connect_to_mongo, close_mongo_connection, get_database
from app.models.enums import MeetingStatus
from app.repositories.meeting_repo import MeetingRepository


SEGMENTS = [
    {"start": 0.0, "end": 6.2, "speaker": "SPEAKER_00",
     "text": "Alright, thanks everyone for joining the project kickoff. Let's keep this to thirty minutes."},
    {"start": 6.2, "end": 14.8, "speaker": "SPEAKER_01",
     "text": "Sounds good. From the client side, the top priority is getting the new onboarding flow live before the end of Q3."},
    {"start": 14.8, "end": 23.5, "speaker": "SPEAKER_00",
     "text": "Understood. We'll need the design assets by next Friday to hit that. Priya, can your team own the Figma handoff?"},
    {"start": 23.5, "end": 29.1, "speaker": "SPEAKER_02",
     "text": "Yes, we can have the final designs ready by Friday the 26th."},
    {"start": 29.1, "end": 38.4, "speaker": "SPEAKER_01",
     "text": "One concern: the payment provider integration is still unconfirmed. If Stripe approval slips, the launch date is at risk."},
    {"start": 38.4, "end": 47.0, "speaker": "SPEAKER_00",
     "text": "Noted. We've decided to go with Stripe over PayPal for v1 since it covers all the regions we need. I'll start the approval process today."},
    {"start": 47.0, "end": 55.3, "speaker": "SPEAKER_02",
     "text": "Should the onboarding support multiple languages at launch, or is English-only acceptable for v1?"},
    {"start": 55.3, "end": 61.9, "speaker": "SPEAKER_01",
     "text": "English-only is fine for v1. We'll add localization in a later phase."},
]

FULL_TEXT = "\n".join(f"[{s['speaker']}] {s['text']}" for s in SEGMENTS)


async def main() -> None:
    await connect_to_mongo()
    db = get_database()
    repo = MeetingRepository(db)

    meetings = await repo.list(limit=50)
    # Prefer a meeting that already has a real recording in S3 so the Recording
    # tab (video with voice + screenshare) works too, not just Transcript/MOM.
    target = next((m for m in meetings if m.get("recording_s3_key")), None)
    if target is None and meetings:
        target = meetings[0]

    if target is None:
        # No meeting exists yet -- create a demo one (Recording tab stays empty).
        m = await repo.create({
            "title": "Demo Project Kickoff",
            "meeting_url": "https://meet.google.com/demo-kickoff",
            "bot_name": "Meeting Bot",
        })
        await repo.update(m["id"], {"recall_bot_id": "demo-bot-0001"})
        meeting_id = m["id"]
        print(f"Created demo meeting {meeting_id}")
    else:
        meeting_id = target["id"]
        has_rec = "with recording" if target.get("recording_s3_key") else "NO recording"
        print(f"Seeding existing meeting '{target.get('title')}' ({meeting_id}) [{has_rec}]")

    # ---- transcript ----
    await repo.save_transcript(meeting_id, {
        "language": "en",
        "segments": SEGMENTS,
        "full_text": FULL_TEXT,
    })

    # ---- MOM (Recording -> Transcript -> MOM is the only pipeline now) ----
    await repo.save_mom(meeting_id, {
        "summary": (
            "Project kickoff for the new customer onboarding flow. The team aligned on a "
            "Q3 launch target, agreed to use Stripe for payments in v1, and assigned design "
            "handoff to Priya's team. Localization is deferred to a later phase."
        ),
        "key_points": [
            "Top priority is shipping the new onboarding flow before end of Q3.",
            "Final Figma designs due Friday the 26th.",
            "Stripe chosen over PayPal for v1 due to regional coverage.",
            "v1 will be English-only; localization comes later.",
        ],
        "action_items": [
            "Priya: deliver final onboarding designs by Friday the 26th.",
            "Alex: start the Stripe approval process today.",
            "Schedule integration planning once Stripe is confirmed.",
        ],
        "next_steps": [
            "Kick off Stripe approval process (today).",
            "Deliver final designs by the 26th.",
            "Schedule integration planning once Stripe is confirmed.",
        ],
        "attendees": ["Alex (Eng Lead)", "Jordan (Client)", "Priya (Design)"],
    })

    # Mark the meeting as fully processed so the UI shows it as completed.
    await repo.set_status(meeting_id, MeetingStatus.COMPLETED)

    print("Seeded transcript, MOM, and extraction. Status -> completed.")
    await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
