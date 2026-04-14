import os
import time
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from database.db import init_db, FileEvent, session
from ml_detection import predict_file
import shutil

# ----------------- Email Configuration -----------------
EMAIL_FROM = "hanihammoud312@gmail.com"
EMAIL_TO   = "hanihammoud312@gmail.com"
EMAIL_PASSWORD = "cfpjdapicsmskrvz"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

# ----------------- Watched and Quarantine folders -----------------
WATCHED_FOLDER = os.path.join(os.getcwd(), "watched_folder")
QUARANTINE_FOLDER = os.path.join(os.getcwd(), "quarantine")
os.makedirs(WATCHED_FOLDER, exist_ok=True)
os.makedirs(QUARANTINE_FOLDER, exist_ok=True)

# Initialize DB
init_db()

# ----------------- Email function -----------------
def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Error sending email: {e}")

# ----------------- DLP Handler -----------------
class DLPHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.recently_created = {}
        self.last_processed_content = {}

    def get_real_filename(self, file_path):
        filename = os.path.basename(file_path)
        if filename.startswith(".goutputstream-"):
            folder = os.path.dirname(file_path)
            candidates = [f for f in os.listdir(folder) if not f.startswith(".")]
            if candidates:
                filename = candidates[0]
                file_path = os.path.join(folder, filename)
        return file_path, filename

    def process_file(self, file_path, action):
        file_path, filename = self.get_real_filename(file_path)
        if action != "DELETED" and not os.path.isfile(file_path):
            return

        if action != "DELETED":
            time.sleep(0.05)

        content = ""
        if action != "DELETED":
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                pass
            if filename in self.last_processed_content and self.last_processed_content[filename] == content:
                return
            self.last_processed_content[filename] = content

        if action == "DELETED":
            print(f"{action} -> {filename}")
            event = FileEvent(
                filename=filename,
                action=action,
                timestamp=datetime.now(timezone.utc)
            )
            session.add(event)
            session.commit()
            return

        label, score, triggered_words, masked_content = predict_file(file_path)
        display_name = f"{filename} ({label} - {score})"
        print(f"{action} -> {display_name}")

        if label == "SENSITIVE":
            print(f"⚠️ ALERT: Sensitive data detected in {filename}!")
            if triggered_words:
                print(f"    Triggered words: {', '.join(triggered_words)}")

            quarantine_path = os.path.join(QUARANTINE_FOLDER, filename)
            try:
                shutil.move(file_path, quarantine_path)
                print(f"File moved to quarantine: {quarantine_path}")
            except Exception as e:
                print(f"Failed to move file to quarantine: {e}")

            body = f"File: {filename}\nScore: {score}\nTriggered words: {', '.join(triggered_words)}\nMoved to quarantine: {quarantine_path}\nMasked content:\n{masked_content}"
            send_email(subject=f"SENSITIVE data detected: {filename}", body=body)

        # Save event to database
        event = FileEvent(
            filename=display_name,
            action=action,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(event)
        session.commit()

    def on_created(self, event):
        if not event.is_directory:
            self.recently_created[event.src_path] = time.time()
            self.process_file(event.src_path, "CREATED")

    def on_modified(self, event):
        if not event.is_directory:
            if event.src_path in self.recently_created:
                if time.time() - self.recently_created[event.src_path] < 1:
                    return
            self.process_file(event.src_path, "MODIFIED")

    def on_deleted(self, event):
        if not event.is_directory:
            self.process_file(event.src_path, "DELETED")

# ----------------- Main -----------------
if __name__ == "__main__":
    event_handler = DLPHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCHED_FOLDER, recursive=True)
    observer.start()

    print(f"Monitoring folder: {WATCHED_FOLDER}")
    print(f"Quarantine folder (outside watched folder): {QUARANTINE_FOLDER}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
