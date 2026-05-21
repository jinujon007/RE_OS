"""
RE_OS RQ Worker
Runs in a separate container to process queued market intelligence jobs.
"""

import os
import sys
import time
from rq import Worker, Queue, Connection
import redis

# Redis connection
redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
redis_conn = redis.from_url(redis_url)

# Queue name used by agents
QUEUE_NAME = "market_intel_crew"

# Create queue
queue = Queue(QUEUE_NAME, connection=redis_conn)

# Start worker
if __name__ == "__main__":
    with Connection(redis_conn):
        worker = Worker([queue])
        print(f"Starting RQ worker for queue '{QUEUE_NAME}'")
        worker.work()
        # The worker will automatically pick up jobs that push run_market_intelligence_job
        # via the queue defined in this module.
