import hashlib
import os
import re
import shutil
import smtplib
import subprocess
import time

from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from database.db import (
    FileEvent,
    PendingApproval,
    SessionLocal,
    init_db
)

from content_classifier import predict_file
from policy_engine import decide_action


EMAIL_FROM = "hanihammoud312@gmail.com"
EMAIL_TO = "hanihammoud312@gmail.com"
EMAIL_PASSWORD = "cfpjdapicsmskrvz"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

WATCHED_FOLDER = os.path.join(
    BASE_DIR,
    "watched_folder"
)

QUARANTINE_FOLDER = os.path.join(
    BASE_DIR,
    "quarantine"
)

FTP_FOLDER = "/home/ftpuser/uploads"
SMB_FOLDER = "/srv/smb_dlp_share"

# Existing local USB testing folder remains supported.
USB_FOLDER = os.path.join(
    BASE_DIR,
    "usb_folder"
)

NEXTCLOUD_DATA_FOLDER = "/var/www/nextcloud/data"

# Dynamically detected real USB mount paths.
DYNAMIC_USB_MOUNTS = set()

# Watchdog watch objects for connected USB devices.
USB_WATCHES = {}

os.makedirs(
    WATCHED_FOLDER,
    exist_ok=True
)

os.makedirs(
    QUARANTINE_FOLDER,
    exist_ok=True
)

os.makedirs(
    USB_FOLDER,
    exist_ok=True
)

try:
    os.chmod(
        QUARANTINE_FOLDER,
        0o700
    )

except Exception as e:
    print(
        "[QUARANTINE WARNING] "
        f"Could not secure quarantine folder: {e}"
    )

init_db()


def send_email(subject, body):
    try:
        msg = MIMEMultipart()

        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject

        msg.attach(
            MIMEText(
                body,
                "plain"
            )
        )

        with smtplib.SMTP_SSL(
            SMTP_SERVER,
            SMTP_PORT
        ) as server:

            server.login(
                EMAIL_FROM,
                EMAIL_PASSWORD
            )

            server.send_message(msg)

        print(
            "[EMAIL] Alert sent successfully"
        )

    except Exception as e:
        print(
            f"[EMAIL ERROR] {e}"
        )


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

        print(
            "[NEXTCLOUD] Platform cache synchronized."
        )

    except Exception as e:
        print(
            f"[NEXTCLOUD RESCAN ERROR] {e}"
        )


def sanitize_filename(filename):
    safe_name = re.sub(
        r"[^A-Za-z0-9_.-]",
        "_",
        filename
    )

    if not safe_name:
        safe_name = "quarantined_file"

    return safe_name


def secure_quarantine_file(
    file_path,
    original_filename
):
    os.makedirs(
        QUARANTINE_FOLDER,
        exist_ok=True
    )

    try:
        os.chmod(
            QUARANTINE_FOLDER,
            0o700
        )

    except Exception as e:
        print(
            "[QUARANTINE WARNING] "
            f"Could not set folder permission: {e}"
        )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    safe_original_name = sanitize_filename(
        original_filename
    )

    quarantine_filename = (
        f"QUARANTINED_{timestamp}_"
        f"{safe_original_name}"
    )

    quarantine_path = os.path.join(
        QUARANTINE_FOLDER,
        quarantine_filename
    )

    counter = 1

    while os.path.exists(quarantine_path):
        quarantine_filename = (
            f"QUARANTINED_{timestamp}_"
            f"{counter}_{safe_original_name}"
        )

        quarantine_path = os.path.join(
            QUARANTINE_FOLDER,
            quarantine_filename
        )

        counter += 1

    shutil.move(
        file_path,
        quarantine_path
    )

    try:
        os.chmod(
            quarantine_path,
            0o600
        )

    except Exception as e:
        print(
            "[QUARANTINE WARNING] "
            f"Could not set file permission: {e}"
        )

    return (
        quarantine_path,
        quarantine_filename
    )


def is_nextcloud_internal_file(file_path):
    normalized_path = file_path.replace(
        "\\",
        "/"
    )

    filename = os.path.basename(
        normalized_path
    )

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

    if filename_lower in [
        "nextcloud.log",
        "index.html"
    ]:
        return True

    if filename.startswith("."):
        return True

    if filename_lower.endswith(".part"):
        return True

    if filename_lower.endswith(".tmp"):
        return True

    if "octransferid" in filename_lower:
        return True

    if re.search(
        r"\.d\d+$",
        filename_lower
    ):
        return True

    if re.search(
        r"\.v\d+$",
        filename_lower
    ):
        return True

    return False


def is_trash_path(file_path):
    """
    Detect Linux desktop trash folders and trash metadata.

    Examples:
    /run/media/hani/DLP-USB/.Trash-1000/files/file.txt
    /run/media/hani/DLP-USB/.Trash-1000/info/file.txt.trashinfo
    """

    normalized_path = file_path.replace(
        "\\",
        "/"
    )

    path_lower = normalized_path.lower()

    filename_lower = os.path.basename(
        normalized_path
    ).lower()

    if "/.trash-" in path_lower:
        return True

    if "/.trash/" in path_lower:
        return True

    if filename_lower.endswith(
        ".trashinfo"
    ):
        return True

    return False


def should_ignore_file(file_path):
    filename = os.path.basename(
        file_path
    )

    filename_lower = filename.lower()

    if is_trash_path(file_path):
        return True

    if file_path.startswith(
        NEXTCLOUD_DATA_FOLDER
    ):
        if is_nextcloud_internal_file(
            file_path
        ):
            return True

    if filename_lower.endswith(
        ".ignore"
    ):
        return True

    if filename.startswith(
        ".goutputstream"
    ):
        return True

    if filename.startswith("."):
        return True

    if filename_lower.endswith(
        ".swp"
    ):
        return True

    if filename_lower.endswith(
        ".tmp"
    ):
        return True

    if filename_lower.endswith(
        ".part"
    ):
        return True

    if "appdata_" in file_path.lower():
        return True

    if filename_lower in [
        "nextcloud.log",
        "index.html"
    ]:
        return True

    return False


def path_is_inside(
    file_path,
    folder_path
):
    try:
        normalized_file = os.path.realpath(
            file_path
        )

        normalized_folder = os.path.realpath(
            folder_path
        )

        return os.path.commonpath(
            [
                normalized_file,
                normalized_folder
            ]
        ) == normalized_folder

    except Exception:
        return False


def discover_usb_mounts():
    """
    Detect real removable-media mount paths.

    Supported examples:
    /run/media/hani/DLP-USB
    /media/hani/DLP-USB
    """

    mount_points = set()

    try:
        with open(
            "/proc/self/mounts",
            "r",
            encoding="utf-8"
        ) as mounts_file:

            for line in mounts_file:
                parts = line.split()

                if len(parts) < 3:
                    continue

                device = parts[0]

                mount_path = parts[1].replace(
                    "\\040",
                    " "
                )

                if not (
                    mount_path.startswith(
                        "/run/media/"
                    )
                    or mount_path.startswith(
                        "/media/"
                    )
                ):
                    continue

                if not device.startswith(
                    "/dev/"
                ):
                    continue

                if os.path.isdir(
                    mount_path
                ):
                    mount_points.add(
                        os.path.realpath(
                            mount_path
                        )
                    )

    except Exception as e:
        print(
            f"[USB DETECTION WARNING] {e}"
        )

    return mount_points


def refresh_usb_watches(
    observer,
    handler
):
    """
    Start monitoring newly connected USB devices and remove
    watches for disconnected devices.
    """

    global DYNAMIC_USB_MOUNTS

    detected_mounts = discover_usb_mounts()

    new_mounts = (
        detected_mounts
        - DYNAMIC_USB_MOUNTS
    )

    for mount_path in sorted(
        new_mounts
    ):
        try:
            watch = observer.schedule(
                handler,
                mount_path,
                recursive=True
            )

            USB_WATCHES[
                mount_path
            ] = watch

            print(
                "[USB] Removable device detected: "
                f"{mount_path}"
            )

            print(
                "[USB] Real-time DLP monitoring started."
            )

        except Exception as e:
            print(
                "[USB WATCH ERROR] "
                f"Could not monitor {mount_path}: {e}"
            )

    disconnected_mounts = (
        DYNAMIC_USB_MOUNTS
        - detected_mounts
    )

    for mount_path in sorted(
        disconnected_mounts
    ):
        watch = USB_WATCHES.pop(
            mount_path,
            None
        )

        if watch is not None:
            try:
                observer.unschedule(
                    watch
                )

            except Exception:
                pass

        print(
            "[USB] Removable device disconnected: "
            f"{mount_path}"
        )

    DYNAMIC_USB_MOUNTS = detected_mounts


def detect_channel(file_path):
    if file_path.startswith(
        FTP_FOLDER
    ):
        return "FTP"

    if file_path.startswith(
        SMB_FOLDER
    ):
        return "SMB"

    if file_path.startswith(
        USB_FOLDER
    ):
        return "USB"

    for usb_mount in tuple(
        DYNAMIC_USB_MOUNTS
    ):
        if path_is_inside(
            file_path,
            usb_mount
        ):
            return "USB"

    if file_path.startswith(
        NEXTCLOUD_DATA_FOLDER
    ):
        return "NEXTCLOUD"

    return "LOCAL_FOLDER"


def wait_for_file_stable(
    file_path,
    checks=3,
    delay=0.5
):
    """
    Wait until a copied file stops changing.

    Drag-and-drop commonly generates CREATED, MODIFIED,
    and CLOSED events while the same file is still being written.
    """

    previous_signature = None
    stable_checks = 0

    for _ in range(12):
        if not os.path.isfile(
            file_path
        ):
            return False

        try:
            file_stat = os.stat(
                file_path
            )

            current_signature = (
                file_stat.st_size,
                file_stat.st_mtime_ns
            )

        except Exception:
            return False

        if (
            current_signature
            == previous_signature
        ):
            stable_checks += 1

            if stable_checks >= checks:
                return True

        else:
            stable_checks = 0

            previous_signature = (
                current_signature
            )

        time.sleep(delay)

    return os.path.isfile(
        file_path
    )


def calculate_file_hash(file_path):
    """
    Calculate a SHA-256 fingerprint.

    Repeated events with identical content are ignored.
    Genuine future file changes are still processed.
    """

    file_hash = hashlib.sha256()

    try:
        with open(
            file_path,
            "rb"
        ) as file:

            while True:
                chunk = file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                file_hash.update(chunk)

        return file_hash.hexdigest()

    except Exception as e:
        print(
            "[HASH WARNING] "
            f"Could not hash {file_path}: {e}"
        )

        return None


def read_medium_preview(file_path):
    try:
        with open(
            file_path,
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as file:

            content = file.read(
                3000
            )

        if not content.strip():
            return (
                "Preview unavailable: "
                "file is empty or not readable as text."
            )

        return content

    except Exception as e:
        return (
            f"Preview unavailable: {e}"
        )


def add_pending_approval(
    filename,
    file_path,
    channel,
    confidence,
    reason
):
    session = SessionLocal()

    existing = session.query(
        PendingApproval
    ).filter(
        PendingApproval.file_path
        == file_path,
        PendingApproval.status
        == "PENDING"
    ).first()

    if existing:
        session.close()
        return

    preview = read_medium_preview(
        file_path
    )

    approval = PendingApproval(
        filename=filename,
        file_path=file_path,
        channel=channel,
        classification="MEDIUM",
        confidence=confidence,
        status="PENDING",
        reason=reason,
        content_preview=preview,
        created_at=datetime.now(
            timezone.utc
        )
    )

    session.add(approval)
    session.commit()
    session.close()

    print(
        "[APPROVAL] Medium-risk file added "
        "to dashboard pending approvals."
    )


class UnifiedDLPHandler(
    FileSystemEventHandler
):

    def __init__(self):
        super().__init__()

        self.last_processed_content = {}
        self.last_processed_hash = {}
        self.recent_events = {}
        self.confirmed_files = set()
        self.system_deleted_files = set()

    def clear_file_cache(
        self,
        file_path
    ):
        self.last_processed_content.pop(
            file_path,
            None
        )

        self.last_processed_hash.pop(
            file_path,
            None
        )

        self.recent_events.pop(
            file_path,
            None
        )

    def process_pending_deletions(self):
        session = SessionLocal()

        delete_requests = session.query(
            PendingApproval
        ).filter(
            PendingApproval.status
            == "DELETE_REQUESTED"
        ).all()

        for approval in delete_requests:
            file_path = approval.file_path
            filename = approval.filename
            channel = approval.channel

            if os.path.exists(
                file_path
            ):
                try:
                    self.system_deleted_files.add(
                        file_path
                    )

                    self.clear_file_cache(
                        file_path
                    )

                    os.remove(file_path)

                    if channel == "NEXTCLOUD":
                        rescan_nextcloud()

                    approval.status = "DELETED"

                    approval.decided_at = datetime.now(
                        timezone.utc
                    )

                    event = FileEvent(
                        filename=filename,
                        action=(
                            f"{channel}_"
                            "MEDIUM_DELETED"
                        ),
                        label="MEDIUM",
                        score=0,
                        ml_prediction="MEDIUM",
                        ml_confidence=(
                            approval.confidence
                        ),
                        rule_score=0,
                        reason=(
                            "Medium-risk file deleted "
                            "after dashboard denial."
                        ),
                        timestamp=datetime.now(
                            timezone.utc
                        )
                    )

                    session.add(event)

                    print(
                        f"\n[{channel}] "
                        f"MEDIUM DENIED -> {filename}"
                    )

                    print(
                        "[APPROVAL] File deleted by monitor "
                        "after dashboard denial."
                    )

                except Exception as e:
                    approval.status = (
                        "DELETE_FAILED"
                    )

                    approval.reason = (
                        f"{approval.reason}\n"
                        f"Delete error: {e}"
                    )

                    approval.decided_at = datetime.now(
                        timezone.utc
                    )

                    print(
                        f"[APPROVAL DELETE ERROR] {e}"
                    )

            else:
                approval.status = (
                    "FILE_NOT_FOUND"
                )

                approval.decided_at = datetime.now(
                    timezone.utc
                )

                print(
                    "[APPROVAL] File not found "
                    f"for deletion: {filename}"
                )

        session.commit()
        session.close()

    def log_deletion_event(
        self,
        file_path
    ):
        if should_ignore_file(
            file_path
        ):
            return

        self.clear_file_cache(
            file_path
        )

        if (
            file_path
            in self.system_deleted_files
        ):
            self.system_deleted_files.discard(
                file_path
            )

            return

        filename = os.path.basename(
            file_path
        )

        channel = detect_channel(
            file_path
        )

        print(
            f"\n[{channel}] DELETED -> {filename}"
        )

        print(
            "Classification: INFO"
        )

        print(
            "Policy Action: DELETION_LOGGED"
        )

        session = SessionLocal()

        event = FileEvent(
            filename=filename,
            action=f"{channel}_DELETED",
            label="INFO",
            score=0,
            ml_prediction="NOT_SCANNED",
            ml_confidence=0,
            rule_score=0,
            reason=(
                "File deletion event logged. "
                "No AI scan was performed because "
                "the file no longer exists."
            ),
            timestamp=datetime.now(
                timezone.utc
            )
        )

        session.add(event)
        session.commit()
        session.close()

    def process_file(
        self,
        file_path,
        action
    ):
        if should_ignore_file(
            file_path
        ):
            return

        filename = os.path.basename(
            file_path
        )

        if (
            file_path
            in self.confirmed_files
        ):
            return

        current_time = time.time()
        event_key = file_path

        if (
            event_key
            in self.recent_events
        ):
            last_time = self.recent_events[
                event_key
            ]

            if (
                current_time
                - last_time
                < 2
            ):
                return

        self.recent_events[
            event_key
        ] = current_time

        if not os.path.isfile(
            file_path
        ):
            return

        marker = (
            file_path
            + ".ignore"
        )

        if os.path.exists(
            marker
        ):
            os.remove(marker)

            print(
                "[INFO] Ignored restored file: "
                f"{filename}"
            )

            return

        if not wait_for_file_stable(
            file_path
        ):
            return

        current_file_hash = (
            calculate_file_hash(
                file_path
            )
        )

        if (
            current_file_hash
            and self.last_processed_hash.get(
                file_path
            ) == current_file_hash
        ):
            return

        if current_file_hash:
            self.last_processed_hash[
                file_path
            ] = current_file_hash

        try:
            with open(
                file_path,
                "r",
                encoding="utf-8",
                errors="ignore"
            ) as file:

                content = file.read()

        except Exception:
            content = ""

        channel = detect_channel(
            file_path
        )

        if (
            channel == "NEXTCLOUD"
            and is_nextcloud_internal_file(
                file_path
            )
        ):
            return

        if channel == "LOCAL_FOLDER":
            if (
                self.last_processed_content.get(
                    file_path
                ) == content
            ):
                return

            self.last_processed_content[
                file_path
            ] = content

        (
            label,
            score,
            _,
            _,
            explanation
        ) = predict_file(
            file_path
        )

        ml_label = explanation[
            "ml_prediction"
        ]

        confidence = explanation[
            "ml_confidence"
        ]

        if (
            ml_label == "SENSITIVE"
            and confidence >= 0.60
        ):
            initial_classification = (
                "SENSITIVE"
            )

        elif (
            ml_label == "MEDIUM"
            and confidence >= 0.50
        ):
            initial_classification = (
                "MEDIUM"
            )

        else:
            initial_classification = (
                "SAFE"
            )

        policy_result = decide_action(
            classification=(
                initial_classification
            ),
            channel=channel,
            organization=None,
            content=content
        )

        final_label = policy_result[
            "final_classification"
        ]

        policy_action = policy_result[
            "action"
        ]

        if channel == "LOCAL_FOLDER":
            print(
                f"\n[{channel}] "
                f"{action} -> {filename}"
            )

            print(
                f"Classification: {final_label}"
            )

            print(
                f"AI Prediction: {ml_label}"
            )

            print(
                f"Confidence: {confidence}"
            )

            print(
                f"Policy Action: {policy_action}"
            )

            if final_label == "SENSITIVE":
                print(
                    "Detection Reason: "
                    f"{explanation['reason']}"
                )

        elif channel == "NEXTCLOUD":
            print(
                "\n[NEXTCLOUD UPLOAD] "
                f"-> {filename}"
            )

            print(
                f"Classification: {final_label}"
            )

            print(
                f"Policy Action: {policy_action}"
            )

        else:
            print(
                f"\n[{channel}]"
            )

            print(
                f"File: {filename}"
            )

            print(
                f"Event: {action}"
            )

            print(
                f"Classification: {final_label}"
            )

            print(
                f"Policy Action: {policy_action}"
            )

        if channel == "LOCAL_FOLDER":

            if policy_action == "QUARANTINE":
                self.system_deleted_files.add(
                    file_path
                )

                (
                    quarantine_path,
                    quarantine_filename
                ) = secure_quarantine_file(
                    file_path,
                    filename
                )

                print(
                    "[ACTION] moved to secure quarantine"
                )

                print(
                    "[QUARANTINE] Stored as: "
                    f"{quarantine_filename}"
                )

                print(
                    "[QUARANTINE] Folder permission: 700"
                )

                print(
                    "[QUARANTINE] File permission: 600"
                )

                send_email(
                    "DLP Alert",
                    (
                        "Sensitive local file detected: "
                        f"{filename}\n"
                        "Stored securely in quarantine as: "
                        f"{quarantine_filename}"
                    )
                )

            elif policy_action == "WARN":
                add_pending_approval(
                    filename=filename,
                    file_path=file_path,
                    channel=channel,
                    confidence=confidence,
                    reason=policy_result[
                        "reason"
                    ]
                )

                print(
                    "[LOCAL_FOLDER] Medium-risk file "
                    "pending dashboard approval."
                )

        elif channel == "NEXTCLOUD":

            if policy_action == "BLOCK":
                self.system_deleted_files.add(
                    file_path
                )

                self.clear_file_cache(
                    file_path
                )

                os.remove(file_path)

                print(
                    "[NEXTCLOUD] Upload BLOCKED "
                    "by DLP policy."
                )

                print(
                    "[NEXTCLOUD] Sensitive file removed "
                    "from cloud storage."
                )

                rescan_nextcloud()

                send_email(
                    "DLP Cloud Alert",
                    (
                        "Sensitive file upload blocked "
                        f"in Nextcloud: {filename}"
                    )
                )

            elif policy_action == "WARN":
                add_pending_approval(
                    filename=filename,
                    file_path=file_path,
                    channel=channel,
                    confidence=confidence,
                    reason=policy_result[
                        "reason"
                    ]
                )

                print(
                    "[NEXTCLOUD] Medium-risk upload "
                    "pending dashboard approval."
                )

                print(
                    "[NEXTCLOUD] Upload kept temporarily."
                )

            elif policy_action == "ALLOW":
                print(
                    "[NEXTCLOUD] Upload ALLOWED."
                )

        else:

            if policy_action == "BLOCK":
                self.system_deleted_files.add(
                    file_path
                )

                self.clear_file_cache(
                    file_path
                )

                os.remove(file_path)

                print(
                    f"[{channel}] Transfer BLOCKED."
                )

            elif policy_action == "WARN":
                add_pending_approval(
                    filename=filename,
                    file_path=file_path,
                    channel=channel,
                    confidence=confidence,
                    reason=policy_result[
                        "reason"
                    ]
                )

                print(
                    f"[{channel}] Medium-risk transfer "
                    "pending dashboard approval."
                )

                print(
                    f"[{channel}] File kept temporarily."
                )

            elif policy_action == "ALLOW":
                print(
                    f"[{channel}] Transfer ALLOWED."
                )

        session = SessionLocal()

        event = FileEvent(
            filename=filename,
            action=(
                f"{channel}_{action}"
            ),
            label=final_label,
            score=score,
            ml_prediction=ml_label,
            ml_confidence=confidence,
            rule_score=0,
            reason=policy_result[
                "reason"
            ],
            timestamp=datetime.now(
                timezone.utc
            )
        )

        session.add(event)
        session.commit()
        session.close()

    def on_created(
        self,
        event
    ):
        if event.is_directory:
            return

        if is_trash_path(
            event.src_path
        ):
            return

        self.process_file(
            event.src_path,
            "CREATED"
        )

    def on_modified(
        self,
        event
    ):
        if event.is_directory:
            return

        if is_trash_path(
            event.src_path
        ):
            return

        self.process_file(
            event.src_path,
            "MODIFIED"
        )

    def on_moved(
        self,
        event
    ):
        if event.is_directory:
            return

        # Moving a normal file into the Linux trash means that
        # the user deleted it. Log the original file as deleted,
        # but never scan the trash destination or .trashinfo file.
        if is_trash_path(
            event.dest_path
        ):
            self.log_deletion_event(
                event.src_path
            )

            return

        if is_trash_path(
            event.src_path
        ):
            return

        self.process_file(
            event.dest_path,
            "MOVED"
        )

    def on_closed(
        self,
        event
    ):
        if event.is_directory:
            return

        if is_trash_path(
            event.src_path
        ):
            return

        self.process_file(
            event.src_path,
            "MODIFIED"
        )

    def on_deleted(
        self,
        event
    ):
        if event.is_directory:
            return

        if is_trash_path(
            event.src_path
        ):
            return

        self.log_deletion_event(
            event.src_path
        )


if __name__ == "__main__":

    observer = Observer()

    handler = UnifiedDLPHandler()

    observer.schedule(
        handler,
        WATCHED_FOLDER,
        recursive=True
    )

    observer.schedule(
        handler,
        FTP_FOLDER,
        recursive=True
    )

    observer.schedule(
        handler,
        SMB_FOLDER,
        recursive=True
    )

    observer.schedule(
        handler,
        USB_FOLDER,
        recursive=True
    )

    observer.schedule(
        handler,
        NEXTCLOUD_DATA_FOLDER,
        recursive=True
    )

    # Detect USB devices already connected before startup.
    refresh_usb_watches(
        observer,
        handler
    )

    observer.start()

    print(
        "[DLP] Unified Enterprise DLP started..."
    )

    print(
        "[DLP] Monitoring Local / REAL FTP / "
        "REAL SMB / USB / Nextcloud"
    )

    print(
        "[USB] Automatic removable-media "
        "detection is active."
    )

    last_usb_refresh = 0

    try:
        while True:
            handler.process_pending_deletions()

            current_time = time.time()

            if (
                current_time
                - last_usb_refresh
                >= 2
            ):
                refresh_usb_watches(
                    observer,
                    handler
                )

                last_usb_refresh = (
                    current_time
                )

            time.sleep(1)

    except KeyboardInterrupt:
        observer.stop()

    observer.join()
