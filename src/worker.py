import os
import threading
import time

import redis
import uvicorn
from fastapi import FastAPI
from rq import Queue
from rq.worker import SimpleWorker
from src.config.settings import settings

REDIS_HOST = settings.REDIS_HOST
REDIS_PORT = settings.REDIS_PORT
PORT = settings.PORT

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok", "worker": "running"}


def start_fastapi_forever():
    while True:
        try:
            uvicorn.run(
                app,
                host="0.0.0.0",  
                port=PORT,
                log_level="warning",
            )
        except Exception as e:
            print(f"FastAPI crashed: {e} — restarting in 2s...")
        time.sleep(2)


def main():
    t = threading.Thread(target=start_fastapi_forever, daemon=True)
    t.start()

    time.sleep(3)

    conn = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        socket_connect_timeout=10,
        socket_timeout=30,
    )
    conn.ping()

    q = Queue("default", connection=conn)

    worker = SimpleWorker([q], connection=conn)

    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
