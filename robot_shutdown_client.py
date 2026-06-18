import os
import subprocess
import sys
import time
import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ropo-shutdown-client")

API_URL = os.environ.get("SHUTDOWN_API_URL")
TOKEN = os.environ.get("SHUTDOWN_TOKEN")
POLL_INTERVAL = int(os.environ.get("SHUTDOWN_POLL_INTERVAL", "15"))

if not API_URL or not TOKEN:
    logger.error("SHUTDOWN_API_URL and SHUTDOWN_TOKEN must be set")
    sys.exit(1)

API_URL = API_URL.rstrip("/")

STATUS_URL = f"{API_URL}/shutdown-status"
RESET_URL = f"{API_URL}/shutdown-reset"

SESSION = requests.Session()
SESSION.timeout = 10


def poll_forever():
    logger.info("Starting shutdown poller — checking %s every %ds", API_URL, POLL_INTERVAL)
    while True:
        try:
            resp = SESSION.get(STATUS_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("shutdown"):
                logger.info("Shutdown signal received — executing shutdown")
                try:
                    reset_resp = SESSION.post(
                        RESET_URL,
                        json={"token": TOKEN},
                        timeout=10,
                    )
                    if reset_resp.ok:
                        logger.info("Shutdown flag reset on server")
                    else:
                        logger.warning("Failed to reset shutdown flag: %s", reset_resp.status_code)
                except requests.RequestException as e:
                    logger.warning("Failed to reset shutdown flag: %s", e)
                try:
                    subprocess.run(
                        ["sudo", "shutdown", "-h", "now"],
                        check=True,
                        timeout=30,
                    )
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                    logger.error("Shutdown command failed: %s", e)
        except requests.Timeout:
            logger.warning("Request timed out")
        except requests.ConnectionError:
            logger.warning("Connection error — is the server reachable?")
        except requests.RequestException as e:
            logger.warning("Request failed: %s", e)
        except Exception as e:
            logger.error("Unexpected error: %s", e)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    poll_forever()
