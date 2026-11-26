import asyncio
import logging

from app import worker_loop

logging.basicConfig(level=logging.INFO)
asyncio.run(worker_loop())
