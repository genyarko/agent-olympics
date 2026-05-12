import asyncio
import uuid
import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import asyncpg
from pydantic import BaseModel
import aioboto3

logger = logging.getLogger(__name__)

# Keep at most this many recent events per session in the in-process buffer.
MAX_EVENT_BUFFER = 5000


class Session(BaseModel):
    id: str
    workspace: Dict[str, Any]
    queue: asyncio.Queue = None

    class Config:
        arbitrary_types_allowed = True


def _initial_workspace() -> Dict[str, Any]:
    return {
        "inputs": {"documents": [], "images": [], "urls": [], "raw_text": ""},
        "facts": "",
        "research_findings": [],
        "analysis": "",
        "red_team_critique": "",
        "conflict_matrix": "",
        "synthesis": {},
        "verification_report": {},
        # Kept for backward compatibility; the live event stream is the SSE
        # queue and the durable copy lives in `audit_events` / get_trace().
        "events": [],
    }


class SessionManager:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.db_url = os.getenv("DATABASE_URL", "postgresql://boardroom:boardroom_password@postgres:5432/boardroom")

        # Falls back to in-process storage when Postgres is unavailable so the
        # app still runs (e.g. a deployment without a database attached).
        self._use_memory = False
        self._mem_sessions: Dict[str, Dict[str, Any]] = {}
        self._mem_audit: Dict[str, List[Dict[str, Any]]] = {}
        self._mem_artifacts: List[Dict[str, Any]] = []

        # Active streaming queues + a bounded recent-event buffer (transient).
        self.queues: Dict[str, asyncio.Queue] = {}
        self.event_buffers: Dict[str, List[Dict[str, Any]]] = {}

        # R2 config
        self.r2_endpoint = os.getenv("R2_ENDPOINT_URL")
        self.r2_access_key = os.getenv("R2_ACCESS_KEY_ID")
        self.r2_secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.r2_bucket = os.getenv("R2_BUCKET_NAME", "boardroom-logs")
        self.session_factory = aioboto3.Session()

    # --- lifecycle ---------------------------------------------------------

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

                # Audit Events table (durable chain-of-thought trace, append-only)
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
            logger.warning(
                "Postgres unavailable (%s). Falling back to in-memory session storage; "
                "sessions and the audit trail will not survive a restart. Set a working "
                "DATABASE_URL to enable durable storage.", e
            )
            self._use_memory = True
            if self.pool is not None:
                try:
                    await self.pool.close()
                except Exception:
                    pass
            self.pool = None

    async def close(self):
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    @property
    def _db_ready(self) -> bool:
        return self.pool is not None and not self._use_memory

    # --- queues ------------------------------------------------------------

    def _get_queue(self, session_id: str) -> asyncio.Queue:
        queue = self.queues.get(session_id)
        if queue is None:
            queue = asyncio.Queue()
            self.queues[session_id] = queue
        return queue

    # --- sessions ----------------------------------------------------------

    async def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        workspace = _initial_workspace()

        if self._db_ready:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO sessions (id, workspace) VALUES ($1, $2)",
                    session_id, json.dumps(workspace)
                )
        else:
            self._mem_sessions[session_id] = workspace

        self._get_queue(session_id)
        self.event_buffers.setdefault(session_id, [])
        return session_id

    async def get_session(self, session_id: str) -> Optional[Session]:
        if self._db_ready:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow("SELECT workspace FROM sessions WHERE id = $1", session_id)
            if not record:
                return None
            workspace = json.loads(record["workspace"])
        else:
            workspace = self._mem_sessions.get(session_id)
            if workspace is None:
                return None

        return Session(id=session_id, workspace=workspace, queue=self._get_queue(session_id))

    async def save_session(self, session: Session):
        if self._db_ready:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE sessions SET workspace = $1, updated_at = now() WHERE id = $2",
                    json.dumps(session.workspace), session.id
                )
        else:
            self._mem_sessions[session.id] = session.workspace

    # --- events / audit ----------------------------------------------------

    async def emit_event(self, session_id: str, agent: str, event_type: str, content: str):
        event = {"agent": agent, "type": event_type, "content": content}

        # 1. Live SSE stream.
        queue = self.queues.get(session_id)
        if queue is not None:
            await queue.put(event)

        # 2. Bounded in-process buffer (debugging / potential replay).
        buf = self.event_buffers.setdefault(session_id, [])
        buf.append(event)
        if len(buf) > MAX_EVENT_BUFFER:
            del buf[: len(buf) - MAX_EVENT_BUFFER]

        # 3. Durable, append-only audit row. This is the *only* persistence on
        #    the hot path — we deliberately do NOT reload and rewrite the whole
        #    session workspace per event (that was O(n^2) on workspace size).
        if self._db_ready:
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO audit_events (session_id, agent, event_type, payload) VALUES ($1, $2, $3, $4)",
                        session_id, agent, event_type, json.dumps(event)
                    )
            except Exception as e:
                logger.warning("Failed to persist audit event for %s: %s", session_id, e)
        else:
            self._mem_audit.setdefault(session_id, []).append({
                "id": len(self._mem_audit.get(session_id, [])) + 1,
                "agent": agent,
                "event_type": event_type,
                "ts": datetime.now(timezone.utc),
                "payload": event,
            })

    # --- artifacts / R2 ----------------------------------------------------

    async def upload_artifact_to_r2(self, session_id: str, filename: str, content: bytes) -> str:
        if not all([self.r2_endpoint, self.r2_access_key, self.r2_secret_key]):
            logger.info("R2 not configured. Skipping artifact upload for %s.", filename)
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
                await s3.put_object(Bucket=self.r2_bucket, Key=key, Body=content)
            logger.info("Uploaded %s to R2 bucket %s as %s", filename, self.r2_bucket, key)

            if self._db_ready:
                try:
                    async with self.pool.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO artifacts (id, session_id, filename, storage_key) VALUES ($1, $2, $3, $4)",
                            str(uuid.uuid4()), session_id, filename, key
                        )
                except Exception as e:
                    logger.warning("Failed to record artifact metadata: %s", e)
            else:
                self._mem_artifacts.append({
                    "id": str(uuid.uuid4()), "session_id": session_id,
                    "filename": filename, "storage_key": key,
                })

            return key
        except Exception as e:
            logger.error("Failed to upload to R2: %s", e)
            return "error"

    async def download_artifact_from_r2(self, storage_key: str) -> Optional[bytes]:
        if not all([self.r2_endpoint, self.r2_access_key, self.r2_secret_key]):
            return None
        if not storage_key or storage_key in ("local_or_unconfigured", "error"):
            return None
        try:
            async with self.session_factory.client(
                "s3",
                endpoint_url=self.r2_endpoint,
                aws_access_key_id=self.r2_access_key,
                aws_secret_access_key=self.r2_secret_key,
                region_name="auto"
            ) as s3:
                response = await s3.get_object(Bucket=self.r2_bucket, Key=storage_key)
                return await response["Body"].read()
        except Exception as e:
            logger.error("Failed to download from R2: %s", e)
            return None

    # --- trace -------------------------------------------------------------

    async def get_trace(self, session_id: str) -> List[Dict[str, Any]]:
        if self._db_ready:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(
                    "SELECT id, agent, event_type, ts, payload FROM audit_events WHERE session_id = $1 ORDER BY ts ASC, id ASC",
                    session_id
                )
            return [
                {
                    "id": r["id"],
                    "agent": r["agent"],
                    "event_type": r["event_type"],
                    "timestamp": r["ts"].isoformat(),
                    "payload": json.loads(r["payload"]),
                }
                for r in records
            ]
        return [
            {
                "id": row["id"],
                "agent": row["agent"],
                "event_type": row["event_type"],
                "timestamp": row["ts"].isoformat(),
                "payload": row["payload"],
            }
            for row in self._mem_audit.get(session_id, [])
        ]


manager = SessionManager()
