import asyncio
import uuid
from typing import Dict, Any
from pydantic import BaseModel

class Session(BaseModel):
    id: str
    workspace: Dict[str, Any]
    queue: asyncio.Queue = None

    class Config:
        arbitrary_types_allowed = True

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Session] = {}

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = Session(
            id=session_id,
            workspace={
                "inputs": {"documents": [], "images": [], "urls": [], "raw_text": ""},
                "facts": [],
                "research_findings": [],
                "analysis": "",
                "red_team_critique": "",
                "synthesis": {},
                "events": []
            },
            queue=asyncio.Queue()
        )
        return session_id

    def get_session(self, session_id: str) -> Session:
        return self.sessions.get(session_id)

    async def emit_event(self, session_id: str, agent: str, event_type: str, content: str):
        session = self.get_session(session_id)
        if session:
            event = {"agent": agent, "type": event_type, "content": content}
            session.workspace["events"].append(event)
            await session.queue.put(event)

manager = SessionManager()
