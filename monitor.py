import os
import time
import shutil
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from database.db import init_db, SessionLocal, FileEvent
from content_classifier import predict_file

EMAIL_FROM = "hanihammoud312@gmail.com"
EMAIL_TO = "hanihammoud312@gmail.com"
EMAIL_PASSWORD = "cfpjdapicsmskrvz"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHED_FOLDER = os.path.join(BASE_DIR, "watched_folder")
QUARANTINE_FOLDER = os.path.join(BASE_DIR, "quarantine")

os.makedirs(WATCHED_FOLDER, exist_ok=True)
os.makedirs(QUARANTINE_FOLDER, exist_ok=True)

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

def should_ignore_file(file_path):
    filename = os.path.basename(file_path)

    if filename.endswith(".ignore"):
        return True

    if filename.startswith(".goutputstream"):
        return True

    if filename.startswith(".") or filename.endswith(".swp") or filename.endswith(".tmp"):
        return True

    return False


class DLPHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.last_processed_content = {}

    def process_file(self, file_path, action):

        if should_ignore_file(file_path):
            return

        filename = os.path.basename(file_path)

        if not os.path.isfile(file_path):
            return

        marker = file_path + ".ignore"

        if os.path.exists(marker):
            os.remove(marker)
            print(f"[INFO] Ignored restored file: {filename}")
            return

        time.sleep(0.3)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

        except:
            content = ""

        if self.last_processed_content.get(filename) == content:
            return

        self.last_processed_content[filename] = content

        label, score, _, _, explanation = predict_file(file_path)

        ml_label = explanation["ml_prediction"]
        confidence = explanation["ml_confidence"]

        if ml_label == "SENSITIVE" and confidence >= 0.60:
            final_label = "SENSITIVE"

        elif ml_label == "MEDIUM" and confidence >= 0.50:
            final_label = "MEDIUM"

        else:
            final_label = "SAFE"

        print(f"{action} -> {filename} ({final_label} - {score})")
        print(f"    ML Prediction: {ml_label}")
        print(f"    ML Confidence: {confidence}")
        print(f"    ML Score: {score}")

        if final_label == "SENSITIVE":
            print(f"    Reason: {explanation['reason']}")

        print(f"[FINAL DECISION] {final_label}")

        if final_label == "SENSITIVE":

            quarantine_path = os.path.join(QUARANTINE_FOLDER, filename)

            shutil.move(file_path, quarantine_path)

            print(f"[ACTION] moved to quarantine")

            send_email("DLP Alert", f"Sensitive file detected: {filename}")

        session = SessionLocal()

        event = FileEvent(
            filename=filename,
            action=action,
            label=final_label,
            score=score,
            ml_prediction=ml_label,
            ml_confidence=confidence,
            rule_score=0,
            reason=explanation["reason"],
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
            self.process_file(event.dest_path, "MODIFIED")

    def on_closed(self, event):

        if not event.is_directory:
            self.process_file(event.src_path, "MODIFIED")


if __name__ == "__main__":

    observer = Observer()
    handler = DLPHandler()

    observer.schedule(handler, WATCHED_FOLDER, recursive=True)

    observer.start()

    print("[DLP] Monitoring started...")

    try:

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        observer.stop()

    observer.join()
