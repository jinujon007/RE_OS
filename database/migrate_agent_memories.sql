CREATE TABLE IF NOT EXISTS agent_memories (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL,
    market TEXT,
    fact TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.6 CHECK (confidence BETWEEN 0.0 AND 1.0),
    source_count INT DEFAULT 1,
    last_confirmed DATE DEFAULT CURRENT_DATE,
    superseded_by UUID REFERENCES agent_memories(memory_id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_agent ON agent_memories(agent_id, market);
CREATE INDEX IF NOT EXISTS idx_agent_memories_confidence ON agent_memories(confidence DESC);