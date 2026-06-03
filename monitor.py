import os
import re
import time
import shutil
import smtplib
import subprocess

from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from database.db import init_db, SessionLocal, FileEvent

from content_classifier import predict_file
from policy_engine import decide_action


EMAIL_FROM = "hanihammoud312@gmail.com"
EMAIL_TO = "hanihammoud312@gmail.com"
EMAIL_PASSWORD = "cfpjdapicsmskrvz"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WATCHED_FOLDER = os.path.join(BASE_DIR, "watched_folder")
QUARANTINE_FOLDER = os.path.join(BASE_DIR, "quarantine")

FTP_FOLDER = "/home/ftpuser/uploads"

SMB_FOLDER = "/srv/smb_dlp_share"

USB_FOLDER = os.path.join(BASE_DIR, "usb_folder")

NEXTCLOUD_DATA_FOLDER = "/var/www/nextcloud/data"


os.makedirs(WATCHED_FOLDER, exist_ok=True)
os.makedirs(QUARANTINE_FOLDER, exist_ok=True)
os.makedirs(USB_FOLDER, exist_ok=True)

try:
    os.chmod(QUARANTINE_FOLDER, 0o700)
except Exception as e:
    print(f"[QUARANTINE WARNING] Could not secure quarantine folder: {e}")

init_db()


def send_email(subject, body):

    try:

        msg = MIMEMultipart()

        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:

            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)

        print("[EMAIL] Alert sent successfully")

    except Exception as e:

        print(f"[EMAIL ERROR] {e}")


def rescan_nextcloud():

    try:

        subprocess.run(
            [
                "sudo",
                "-u",
                "www-data",
                "php",
                "/var/www/nextcloud/occ",
                "files:scan",
                "--all"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        print("[NEXTCLOUD] Platform cache synchronized.")

    except Exception as e:

        print(f"[NEXTCLOUD RESCAN ERROR] {e}")


def sanitize_filename(filename):

    safe_name = re.sub(
        r"[^A-Za-z0-9_.-]",
        "_",
        filename
    )

    if not safe_name:
        safe_name = "quarantined_file"

    return safe_name


def secure_quarantine_file(file_path, original_filename):

    os.makedirs(QUARANTINE_FOLDER, exist_ok=True)

    try:
        os.chmod(QUARANTINE_FOLDER, 0o700)
    except Exception as e:
        print(f"[QUARANTINE WARNING] Could not set folder permission: {e}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    safe_original_name = sanitize_filename(original_filename)

    quarantine_filename = (
        f"QUARANTINED_{timestamp}_{safe_original_name}"
    )

    quarantine_path = os.path.join(
        QUARANTINE_FOLDER,
        quarantine_filename
    )

    counter = 1

    while os.path.exists(quarantine_path):

        quarantine_filename = (
            f"QUARANTINED_{timestamp}_{counter}_{safe_original_name}"
        )

        quarantine_path = os.path.join(
            QUARANTINE_FOLDER,
            quarantine_filename
        )

        counter += 1

    shutil.move(file_path, quarantine_path)

    try:
        os.chmod(quarantine_path, 0o600)
    except Exception as e:
        print(f"[QUARANTINE WARNING] Could not set file permission: {e}")

    return quarantine_path, quarantine_filename


def is_nextcloud_internal_file(file_path):

    normalized_path = file_path.replace("\\", "/")

    filename = os.path.basename(normalized_path)

    filename_lower = filename.lower()

    path_lower = normalized_path.lower()

    if "/files_trashbin/" in path_lower:
        return True

    if "/files_versions/" in path_lower:
        return True

    if "/uploads/" in path_lower:
        return True

    if "/cache/" in path_lower:
        return True

    if "/appdata_" in path_lower:
        return True

    if filename_lower in ["nextcloud.log", "index.html"]:
        return True

    if filename.startswith("."):
        return True

    if filename_lower.endswith(".part"):
        return True

    if filename_lower.endswith(".tmp"):
        return True

    if "octransferid" in filename_lower:
        return True

    if re.search(r"\.d\d+$", filename_lower):
        return True

    if re.search(r"\.v\d+$", filename_lower):
        return True

    return False


def should_ignore_file(file_path):

    filename = os.path.basename(file_path)

    if file_path.startswith(NEXTCLOUD_DATA_FOLDER):

        if is_nextcloud_internal_file(file_path):
            return True

    if filename.endswith(".ignore"):
        return True

    if filename.startswith(".goutputstream"):
        return True

    if filename.startswith("."):
        return True

    if filename.endswith(".swp") or filename.endswith(".tmp"):
        return True

    if filename.endswith(".part"):
        return True

    if "appdata_" in file_path:
        return True

    if filename in ["nextcloud.log", "index.html"]:
        return True

    return False


def detect_channel(file_path):

    if file_path.startswith(FTP_FOLDER):
        return "FTP"

    if file_path.startswith(SMB_FOLDER):
        return "SMB"

    if file_path.startswith(USB_FOLDER):
        return "USB"

    if file_path.startswith(NEXTCLOUD_DATA_FOLDER):
        return "NEXTCLOUD"

    return "LOCAL_FOLDER"


class UnifiedDLPHandler(FileSystemEventHandler):

    def __init__(self):

        super().__init__()

        self.last_processed_content = {}
        self.recent_events = {}
        self.confirmed_files = set()
        self.system_deleted_files = set()

    def log_deletion_event(self, file_path):

        if should_ignore_file(file_path):
            return

        if file_path in self.system_deleted_files:

            self.system_deleted_files.discard(file_path)

            return

        filename = os.path.basename(file_path)

        channel = detect_channel(file_path)

        print(f"\n[{channel}] DELETED -> {filename}")
        print("Classification: INFO")
        print("Policy Action: DELETION_LOGGED")

        session = SessionLocal()

        event = FileEvent(
            filename=filename,
            action=f"{channel}_DELETED",
            label="INFO",
            score=0,
            ml_prediction="NOT_SCANNED",
            ml_confidence=0,
            rule_score=0,
            reason="File deletion event logged. No AI scan was performed because the file no longer exists.",
            timestamp=datetime.now(timezone.utc)
        )

        session.add(event)

        session.commit()

        session.close()

    def process_file(self, file_path, action):

        if should_ignore_file(file_path):
            return

        filename = os.path.basename(file_path)

        if file_path in self.confirmed_files:
            return

        current_time = time.time()

        event_key = f"{file_path}"

        if event_key in self.recent_events:

            last_time = self.recent_events[event_key]

            if current_time - last_time < 2:
                return

        self.recent_events[event_key] = current_time

        if not os.path.isfile(file_path):
            return

        marker = file_path + ".ignore"

        if os.path.exists(marker):

            os.remove(marker)

            print(f"[INFO] Ignored restored file: {filename}")

            return

        time.sleep(0.5)

        try:

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

        except:

            content = ""

        channel = detect_channel(file_path)

        if channel == "NEXTCLOUD" and is_nextcloud_internal_file(file_path):
            return

        if channel == "LOCAL_FOLDER":

            if self.last_processed_content.get(file_path) == content:
                return

            self.last_processed_content[file_path] = content

        label, score, _, _, explanation = predict_file(file_path)

        ml_label = explanation["ml_prediction"]
        confidence = explanation["ml_confidence"]

        if ml_label == "SENSITIVE" and confidence >= 0.60:

            initial_classification = "SENSITIVE"

        elif ml_label == "MEDIUM" and confidence >= 0.50:

            initial_classification = "MEDIUM"

        else:

            initial_classification = "SAFE"

        policy_result = decide_action(
            classification=initial_classification,
            channel=channel,
            organization=None,
            content=content
        )

        final_label = policy_result["final_classification"]

        policy_action = policy_result["action"]

        if channel == "LOCAL_FOLDER":

            print(f"\n[{channel}] {action} -> {filename}")

            print(f"Classification: {final_label}")
            print(f"AI Prediction: {ml_label}")
            print(f"Confidence: {confidence}")
            print(f"Policy Action: {policy_action}")

            if final_label == "SENSITIVE":
                print(f"Detection Reason: {explanation['reason']}")

        elif channel == "NEXTCLOUD":

            print(f"\n[NEXTCLOUD UPLOAD] -> {filename}")
            print(f"Classification: {final_label}")
            print(f"Policy Action: {policy_action}")

        else:

            print(f"\n[{channel}]")
            print(f"Classification: {final_label}")
            print(f"Policy Action: {policy_action}")

        if channel == "LOCAL_FOLDER":

            if policy_action == "QUARANTINE":

                self.system_deleted_files.add(file_path)

                quarantine_path, quarantine_filename = secure_quarantine_file(
                    file_path,
                    filename
                )

                print("[ACTION] moved to secure quarantine")
                print(f"[QUARANTINE] Stored as: {quarantine_filename}")
                print("[QUARANTINE] Folder permission: 700")
                print("[QUARANTINE] File permission: 600")

                send_email(
                    "DLP Alert",
                    (
                        f"Sensitive local file detected: {filename}\n"
                        f"Stored securely in quarantine as: "
                        f"{quarantine_filename}"
                    )
                )

        elif channel == "NEXTCLOUD":

            if policy_action == "BLOCK":

                self.system_deleted_files.add(file_path)

                os.remove(file_path)

                print("[NEXTCLOUD] Upload BLOCKED by DLP policy.")
                print("[NEXTCLOUD] Sensitive file removed from cloud storage.")

                rescan_nextcloud()

                send_email(
                    "DLP Cloud Alert",
                    f"Sensitive file upload blocked in Nextcloud: {filename}"
                )

            elif policy_action == "WARN":

                print("[NEXTCLOUD] Medium-risk upload detected.")
                print("[NEXTCLOUD] Upload kept for now and logged for review.")

            elif policy_action == "ALLOW":

                print("[NEXTCLOUD] Upload ALLOWED.")

        else:

            if policy_action == "BLOCK":

                self.system_deleted_files.add(file_path)

                os.remove(file_path)

                print(f"[{channel}] Transfer BLOCKED.")

            elif policy_action == "WARN":

                if file_path in self.confirmed_files:
                    return

                print(f"[{channel}] Transfer requires confirmation.")

                user_input = input(
                    "Do you still want to continue? (yes/no): "
                ).strip().lower()

                if user_input == "yes":

                    self.confirmed_files.add(file_path)

                    print(f"[{channel}] Transfer CONFIRMED.")

                else:

                    self.system_deleted_files.add(file_path)

                    os.remove(file_path)

                    print(f"[{channel}] Transfer CANCELLED.")

            elif policy_action == "ALLOW":

                print(f"[{channel}] Transfer ALLOWED.")

        session = SessionLocal()

        event = FileEvent(
            filename=filename,
            action=f"{channel}_{action}",
            label=final_label,
            score=score,
            ml_prediction=ml_label,
            ml_confidence=confidence,
            rule_score=0,
            reason=policy_result["reason"],
            timestamp=datetime.now(timezone.utc)
        )

        session.add(event)

        session.commit()

        session.close()

    def on_created(self, event):

        if not event.is_directory:

            self.process_file(event.src_path, "CREATED")

    def on_modified(self, event):

        if not event.is_directory:

            self.process_file(event.src_path, "MODIFIED")

    def on_moved(self, event):

        if not event.is_directory:

            self.process_file(event.dest_path, "MOVED")

    def on_closed(self, event):

        if not event.is_directory:

            self.process_file(event.src_path, "MODIFIED")

    def on_deleted(self, event):

        if not event.is_directory:

            self.log_deletion_event(event.src_path)


if __name__ == "__main__":

    observer = Observer()

    handler = UnifiedDLPHandler()

    observer.schedule(handler, WATCHED_FOLDER, recursive=True)

    observer.schedule(handler, FTP_FOLDER, recursive=True)

    observer.schedule(handler, SMB_FOLDER, recursive=True)

    observer.schedule(handler, USB_FOLDER, recursive=True)

    observer.schedule(handler, NEXTCLOUD_DATA_FOLDER, recursive=True)

    observer.start()

    print("[DLP] Unified Enterprise DLP started...")
    print("[DLP] Monitoring Local / REAL FTP / REAL SMB / USB / Nextcloud")

    try:

        while True:
            time.sleep(1)

    except KeyboardInterrupt:

        observer.stop()

    observer.join()
