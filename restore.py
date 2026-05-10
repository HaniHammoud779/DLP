import os
import shutil
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WATCHED_FOLDER = os.path.join(BASE_DIR, "watched_folder")
QUARANTINE_FOLDER = os.path.join(BASE_DIR, "quarantine")

def restore_file(filename):
    quarantine_path = os.path.join(QUARANTINE_FOLDER, filename)
    restore_path = os.path.join(WATCHED_FOLDER, filename)

    if not os.path.exists(quarantine_path):
        return False

    try:
        shutil.move(quarantine_path, restore_path)

        # 🔥 CREATE IGNORE MARKER FILE
        marker_path = restore_path + ".ignore"
        with open(marker_path, "w") as f:
            f.write(str(time.time()))

        return True

    except Exception as e:
        print(f"[ERROR] restore failed: {e}")
        return False
