import logging
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

from usd_studio.renderer import StudioRenderer

SCENE = Path(__file__).parent.parent / "data" / "simple_scene.usda"
OUT = Path(__file__).parent.parent / "outputs" / "test_load.png"
LOG = Path("ovrtx-studio.log")
TIMEOUT_SECONDS = 180

# Make ovrtx's internal logs visible on the console.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def log(msg: str) -> None:
    print(msg, flush=True)


def heartbeat() -> None:
    while True:
        time.sleep(10)
        log("...still working (shader/asset compile may be in progress)...")


def timeout_handler(signum, frame):
    raise TimeoutError(f"test_load.py did not complete within {TIMEOUT_SECONDS} seconds")


if sys.platform == "win32":
    # signal.SIGALRM is Unix-only; use a thread-based watchdog on Windows.
    class Watchdog:
        def __init__(self, seconds: int):
            self.seconds = seconds
            self._timer = threading.Timer(seconds, self._fire)

        def start(self):
            self._timer.start()

        def cancel(self):
            self._timer.cancel()

        def _fire(self):
            log(f"TIMEOUT after {self.seconds}s")
            try:
                if LOG.exists():
                    log("--- ovrtx-studio.log tail ---")
                    log(LOG.read_text()[-4000:])
                    log("--- end log ---")
            except Exception as e:
                log(f"Could not read log: {e}")
            sys.exit(1)

    watchdog = Watchdog(TIMEOUT_SECONDS)
    watchdog.start()
else:
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(TIMEOUT_SECONDS)


def main() -> int:
    t = threading.Thread(target=heartbeat, daemon=True)
    t.start()

    try:
        log("Creating renderer (640x480 test mode)...")
        r = StudioRenderer(width=640, height=480)

        log(f"Loading {SCENE.resolve()}...")
        info = r.load_scene(SCENE)
        log(f"Load info: {info}")

        log("Rendering still...")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        r.save_still(OUT)
        log(f"Saved {OUT.resolve()}")

        log("Closing renderer...")
        r.close()
        log("Done.")
        return 0
    except Exception as e:
        log(f"ERROR: {e}")
        if LOG.exists():
            try:
                log("--- ovrtx-studio.log tail ---")
                log(LOG.read_text()[-4000:])
                log("--- end log ---")
            except Exception as log_err:
                log(f"Could not read log: {log_err}")
        raise
    finally:
        if sys.platform == "win32":
            watchdog.cancel()
        else:
            signal.alarm(0)


if __name__ == "__main__":
    sys.exit(main())
