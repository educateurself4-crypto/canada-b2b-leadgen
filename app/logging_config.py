import logging
import os
from app.config import config

os.makedirs(config.LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(config.LOG_DIR, "pipeline.log")),
    ],
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
