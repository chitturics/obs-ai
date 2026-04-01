CREATE TABLE IF NOT EXISTS users (
    "id" UUID PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" JSONB NOT NULL,
    "createdAt" TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id" UUID PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" UUID,
    "userIdentifier" TEXT,
    "tags" TEXT[],
    "metadata" JSONB,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    "id" UUID PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" UUID NOT NULL,
    "parentId" UUID,
    "streaming" BOOLEAN NOT NULL,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" JSONB,
    "tags" TEXT[],
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "command" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" JSONB,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INT,
    "defaultOpen" BOOLEAN,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elements (
    "id" UUID PRIMARY KEY,
    "threadId" UUID,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INT,
    "language" TEXT,
    "forId" UUID,
    "mime" TEXT,
    "props" JSONB,
    "content" BYTEA,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

-- Blob storage table for Chainlit file attachments
CREATE TABLE IF NOT EXISTS blobs (
    "id" UUID PRIMARY KEY,
    "key" TEXT NOT NULL UNIQUE,
    "data" BYTEA NOT NULL,
    "mime" TEXT,
    "size" INT,
    "createdAt" TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_blobs_key ON blobs("key");

CREATE TABLE IF NOT EXISTS feedbacks (
    "id" UUID PRIMARY KEY,
    "forId" UUID NOT NULL,
    "threadId" UUID NOT NULL,
    "value" INT NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

-- Custom tables for assistant persistence
CREATE TABLE IF NOT EXISTS assistant_interactions (
    "id" UUID PRIMARY KEY,
    "username" TEXT NOT NULL,
    "thread_id" TEXT,
    "question" TEXT,
    "answer" TEXT,
    "context" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assistant_feedback (
    "id" UUID PRIMARY KEY,
    "message_id" TEXT,
    "value" INT,
    "comment" TEXT,
    "username" TEXT,
    "thread_id" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assistant_notes (
    "id" UUID PRIMARY KEY,
    "title" TEXT,
    "body" TEXT,
    "created_by" TEXT,
    "thread_id" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assistant_doc_ingests (
    "id" UUID PRIMARY KEY,
    "username" TEXT,
    "thread_id" TEXT,
    "source" TEXT,
    "kind" TEXT,
    "fingerprint" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assistant_liked_queries (
    "id" UUID PRIMARY KEY,
    "username" TEXT,
    "thread_id" TEXT,
    "question" TEXT,
    "answer" TEXT,
    "context" TEXT,
    "source_message_id" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assistant_disliked_queries (
    "id" UUID PRIMARY KEY,
    "username" TEXT,
    "thread_id" TEXT,
    "question" TEXT,
    "answer" TEXT,
    "context" TEXT,
    "source_message_id" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assistant_mcp_tokens (
    "id" UUID PRIMARY KEY,
    "user_id" TEXT NOT NULL,
    "server_name" TEXT NOT NULL,
    "auth_scheme" TEXT DEFAULT 'none',
    "access_token" TEXT NOT NULL,
    "refresh_token" TEXT,
    "expires_at" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ DEFAULT NOW(),
    "updated_at" TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE("user_id", "server_name")
);

-- Episodic memory: structured record of each interaction episode
CREATE TABLE IF NOT EXISTS assistant_episodes (
    "id" UUID PRIMARY KEY,
    "username" TEXT NOT NULL,
    "query_hash" VARCHAR(64) NOT NULL,
    "query" TEXT NOT NULL,
    "intent" VARCHAR(50),
    "profile" VARCHAR(50),
    "strategy_used" VARCHAR(100),
    "collections_searched" TEXT,
    "chunks_found" INTEGER DEFAULT 0,
    "response_length" INTEGER DEFAULT 0,
    "confidence" FLOAT DEFAULT 0.0,
    "success" INTEGER DEFAULT -1,
    "failure_reason" TEXT,
    "duration_ms" INTEGER DEFAULT 0,
    "metadata" JSONB,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episodes_query_hash ON assistant_episodes("query_hash");
CREATE INDEX IF NOT EXISTS idx_episodes_username ON assistant_episodes("username");
CREATE INDEX IF NOT EXISTS idx_episodes_intent ON assistant_episodes("intent");

-- Semantic facts: learned rules distilled from episode patterns
CREATE TABLE IF NOT EXISTS assistant_semantic_facts (
    "id" UUID PRIMARY KEY,
    "pattern_hash" VARCHAR(64) UNIQUE,
    "rule" TEXT NOT NULL,
    "category" VARCHAR(50),
    "confidence" FLOAT DEFAULT 0.5,
    "times_applied" INTEGER DEFAULT 0,
    "times_succeeded" INTEGER DEFAULT 0,
    "source_episodes" INTEGER DEFAULT 0,
    "created_at" TIMESTAMPTZ DEFAULT NOW(),
    "updated_at" TIMESTAMPTZ DEFAULT NOW()
);
