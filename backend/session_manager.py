import asyncio
import uuid
import json
import os
import logging
from typing import Dict, Any, List
import asyncpg
from pydantic import BaseModel
import aioboto3

logger = logging.getLogger(__name__)

class Session(BaseModel):
    id: str
    workspace: Dict[str, Any]
    queue: asyncio.Queue = None

    class Config:
        arbitrary_types_allowed = True

class SessionManager:
    def __init__(self):
        self.pool = None
        self.db_url = os.getenv("DATABASE_URL", "postgresql://boardroom:boardroom_password@postgres:5432/boardroom")
        
        # Active streaming queues (transient)
        self.queues: Dict[str, asyncio.Queue] = {}
        
        # R2 config
        self.r2_endpoint = os.getenv("R2_ENDPOINT_URL")
        self.r2_access_key = os.getenv("R2_ACCESS_KEY_ID")
        self.r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.r2_bucket = os.getenv("R2_BUCKET_NAME", "boardroom-logs")
        self.session_factory = aioboto3.Session()

    async def init_db(self):
        logger.info("Initializing Postgres connection pool...")
        try:
            self.pool = await asyncpg.create_pool(self.db_url, statement_cache_size=0)
            
            async with self.pool.acquire() as conn:
                # Sessions table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        workspace JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                """)
                
                # Audit Events table (from Conti)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_events (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        agent TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                        payload JSONB NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS audit_events_session_idx ON audit_events (session_id);
                    CREATE INDEX IF NOT EXISTS audit_events_ts_idx ON audit_events (ts DESC);
                """)
                
                # Document artifacts table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS artifacts (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        storage_key TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                """)
            logger.info("Database initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    async def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        initial_workspace = {
            "inputs": {"documents": [], "images": [], "urls": [], "raw_text": ""},
            "facts": [],
            "research_findings": [],
            "analysis": "",
            "red_team_critique": "",
            "synthesis": {},
            "events": []
        }
        
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sessions (id, workspace) VALUES ($1, $2)",
                session_id, json.dumps(initial_workspace)
            )
        
        self.queues[session_id] = asyncio.Queue()
        return session_id

    async def get_session(self, session_id: str) -> Session:
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow("SELECT workspace FROM sessions WHERE id = $1", session_id)
            if record:
                workspace = json.loads(record['workspace'])
                # Re-attach the queue if it's active
                queue = self.queues.get(session_id)
                if not queue:
                    queue = asyncio.Queue()
                    self.queues[session_id] = queue
                return Session(id=session_id, workspace=workspace, queue=queue)
        return None

    async def save_session(self, session: Session):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET workspace = $1, updated_at = now() WHERE id = $2",
                json.dumps(session.workspace), session.id
            )

    async def emit_event(self, session_id: str, agent: str, event_type: str, content: str):
        session = await self.get_session(session_id)
        if session:
            event = {"agent": agent, "type": event_type, "content": content}
            session.workspace["events"].append(event)
            await self.save_session(session)
            
            # Log to audit_events
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO audit_events (session_id, agent, event_type, payload) VALUES ($1, $2, $3, $4)",
                    session_id, agent, event_type, json.dumps(event)
                )
            
            if session.queue:
                await session.queue.put(event)

    async def upload_artifact_to_r2(self, session_id: str, filename: str, content: bytes) -> str:
        if not all([self.r2_endpoint, self.r2_access_key, self.r2_secret_key]):
            logger.warning("R2 not configured. Skipping upload.")
            return "local_or_unconfigured"

        key = f"{session_id}/{uuid.uuid4()}_{filename}"
        try:
            async with self.session_factory.client(
                "s3",
                endpoint_url=self.r2_endpoint,
                aws_access_key_id=self.r2_access_key,
                aws_secret_access_key=self.r2_secret_key,
                region_name="auto"
            ) as s3:
                await s3.put_object(
                    Bucket=self.r2_bucket,
                    Key=key,
                    Body=content
                )
            logger.info(f"Uploaded {filename} to R2 bucket {self.r2_bucket} as {key}")
            
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO artifacts (id, session_id, filename, storage_key) VALUES ($1, $2, $3, $4)",
                    str(uuid.uuid4()), session_id, filename, key
                )
                
            return key
        except Exception as e:
            logger.error(f"Failed to upload to R2: {e}")
            return "error"
            
    async def download_artifact_from_r2(self, storage_key: str) -> bytes:
        if not all([self.r2_endpoint, self.r2_access_key, self.r2_secret_key]):
            logger.warning("R2 not configured. Cannot download artifact.")
            return None

        try:
            async with self.session_factory.client(
                "s3",
                endpoint_url=self.r2_endpoint,
                aws_access_key_id=self.r2_access_key,
                aws_secret_access_key=self.r2_secret_key,
                region_name="auto"
            ) as s3:
                response = await s3.get_object(
                    Bucket=self.r2_bucket,
                    Key=storage_key
                )
                return await response['Body'].read()
        except Exception as e:
            logger.error(f"Failed to download from R2: {e}")
            return None

    async def get_trace(self, session_id: str) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            records = await conn.fetch(
                "SELECT id, agent, event_type, ts, payload FROM audit_events WHERE session_id = $1 ORDER BY ts ASC",
                session_id
            )
            return [
                {
                    "id": r["id"],
                    "agent": r["agent"],
                    "event_type": r["event_type"],
                    "timestamp": r["ts"].isoformat(),
                    "payload": json.loads(r["payload"])
                }
                for r in records
            ]

manager = SessionManager()
