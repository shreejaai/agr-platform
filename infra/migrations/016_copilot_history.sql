-- Migration 016: copilot conversation history
-- Stores chat sessions (copilot_conversations) and individual messages (copilot_messages).
-- Conversations are scoped per org. Messages reference conversations with CASCADE delete.

CREATE TABLE copilot_conversations (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title       TEXT        NOT NULL DEFAULT 'New conversation',
    message_count INT       NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_copilot_convs_org
    ON copilot_conversations(org_id, updated_at DESC);

CREATE TABLE copilot_messages (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID        NOT NULL REFERENCES copilot_conversations(id) ON DELETE CASCADE,
    org_id          UUID        NOT NULL,
    role            TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT        NOT NULL,
    action_type     TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_copilot_msgs_conv
    ON copilot_messages(conversation_id, created_at ASC);
