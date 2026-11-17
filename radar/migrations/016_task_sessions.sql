-- Which chat sessions a task has to do with, and why: it was born there, a notice about it was delivered to that
-- chat, or the owner answered it there. On 2026-11-16 the owner answered a notice about an expense sheet and went on
-- working on it with the agent in the same chat; the conversation was judged as a new matter, because only tasks
-- born in a session were compared with it, and it asked again for what had already been sent.
CREATE TABLE IF NOT EXISTS task_sessions (
 profile_key TEXT NOT NULL, owner_id TEXT NOT NULL, task_id TEXT NOT NULL, session_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('born', 'noticed', 'answered')),
 created_at TEXT NOT NULL,
 PRIMARY KEY (profile_key, owner_id, task_id, session_id, role)
);
CREATE INDEX IF NOT EXISTS idx_task_sessions_session ON task_sessions(profile_key, owner_id, session_id);
