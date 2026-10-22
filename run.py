"""Start CITY HUNT. Uses one worker and a persistent SQLite database."""
import os
import uvicorn
from app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
                access_log=False, limit_concurrency=160, timeout_keep_alive=5)
