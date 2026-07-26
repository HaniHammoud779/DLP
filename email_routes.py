import os
import base64
import tempfile
import hashlib
import json
import shutil
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from datetime import datetime

from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    jsonify,
    make_response
)
from flask_login import login_required
from sqlalchemy import func

from content_classifier import (
    predict_file,
    read_file_content,
    read_file_preview,
)

from web.models import db, EmailIncident, User

from database.db import (
    SessionLocal,
    ClassificationReview,
    PendingApproval,
    FileEvent
)


email_bp = Blueprint("email", __name__)

MAX_BROWSER_ATTACHMENT_BYTES = 25 * 1024 * 1024

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL_REVIEW_HOLD_FOLDER = os.path.join(PROJECT_DIR, "email_review_hold")

os.makedirs(EMAIL_REVIEW_HOLD_FOLDER, exist_ok=True)

try:
    os.chmod(EMAIL_REVIEW_HOLD_FOLDER, 0o700)
except Exception:
    pass



def normalize_email_list(value):
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = str(value or "").replace(";", ",").split(",")

    cleaned = []

    for item in raw_values:
        email = str(item or "").strip()

        if email and "@" in email and email not in cleaned:
            cleaned.append(email)

    return cleaned


def held_email_directory(email_key):
    fingerprint = str(email_key or "").replace("EMAIL_FINGERPRINT:", "")
    safe_fingerprint = "".join(
        character
        for character in fingerprint
        if character.isalnum() or character in "-_"
    )

    if not safe_fingerprint:
        raise ValueError("Invalid Gmail email fingerprint.")

    return os.path.join(
        EMAIL_REVIEW_HOLD_FOLDER,
        safe_fingerprint
    )


def held_email_metadata_path(email_key):
    return os.path.join(
        held_email_directory(email_key),
        "metadata.json"
    )


def secure_path_permissions(path, mode):
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def store_held_gmail_email(
    email_key,
    sender,
    to_email,
    cc_email,
    bcc_email,
    subject,
    body,
    attachments
):
    hold_directory = held_email_directory(email_key)

    if os.path.isdir(hold_directory):
        return hold_directory

    os.makedirs(hold_directory, exist_ok=True)
    secure_path_permissions(hold_directory, 0o700)

    attachment_records = []

    try:
        for index, attachment in enumerate(attachments or [], start=1):
            if not isinstance(attachment, dict):
                continue

            filename = safe_browser_filename(
                attachment.get("filename", f"attachment_{index}")
            )
            content_base64 = str(attachment.get("content_base64", "") or "")

            if not content_base64:
                raise ValueError(
                    f"Attachment {filename} could not be held because its content was missing."
                )

            try:
                raw_bytes = base64.b64decode(content_base64)
            except Exception as error:
                raise ValueError(
                    f"Attachment {filename} could not be decoded for secure holding: {error}"
                )

            if len(raw_bytes) > MAX_BROWSER_ATTACHMENT_BYTES:
                raise ValueError(
                    f"Attachment {filename} is larger than the allowed Gmail DLP limit."
                )

            stored_name = f"{index:03d}_{filename}"
            stored_path = os.path.join(hold_directory, stored_name)

            with open(stored_path, "wb") as attachment_file:
                attachment_file.write(raw_bytes)

            secure_path_permissions(stored_path, 0o600)

            attachment_records.append(
                {
                    "filename": filename,
                    "stored_name": stored_name,
                    "content_type": attachment.get(
                        "type",
                        "application/octet-stream"
                    ),
                    "size": len(raw_bytes)
                }
            )

        metadata = {
            "email_key": email_key,
            "sender": str(sender or "").strip(),
            "to": normalize_email_list(to_email),
            "cc": normalize_email_list(cc_email),
            "bcc": normalize_email_list(bcc_email),
            "subject": str(subject or ""),
            "body": str(body or ""),
            "attachments": attachment_records,
            "created_at": datetime.now().isoformat()
        }

        metadata_path = held_email_metadata_path(email_key)

        with open(metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, indent=2, ensure_ascii=False)

        secure_path_permissions(metadata_path, 0o600)

        return hold_directory

    except Exception:
        shutil.rmtree(hold_directory, ignore_errors=True)
        raise


def load_held_gmail_email(email_key):
    metadata_path = held_email_metadata_path(email_key)

    if not os.path.isfile(metadata_path):
        raise FileNotFoundError(
            "The securely held Gmail message could not be found."
        )

    with open(metadata_path, "r", encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)

    metadata["hold_directory"] = held_email_directory(email_key)
    return metadata


def cleanup_held_gmail_email(email_key):
    try:
        shutil.rmtree(
            held_email_directory(email_key),
            ignore_errors=True
        )
    except Exception:
        pass


def find_smtp_user(email_address):
    clean_email = str(email_address or "").strip().lower()

    if not clean_email:
        return None

    return User.query.filter(
        func.lower(User.smtp_email) == clean_email
    ).first() or User.query.filter(
        func.lower(User.email) == clean_email
    ).first()


def send_smtp_message(smtp_user, message):
    if smtp_user is None:
        raise ValueError("No dashboard user SMTP account was found for this email address.")

    smtp_email = str(smtp_user.smtp_email or "").strip()
    smtp_password = str(smtp_user.smtp_password or "").strip()

    if not smtp_email or not smtp_password:
        raise ValueError("SMTP email or App Password is missing for this account.")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(smtp_email, smtp_password)
        smtp.send_message(message)


def send_held_gmail_email(email_key):
    metadata = load_held_gmail_email(email_key)
    sender = str(metadata.get("sender", "")).strip()
    smtp_user = find_smtp_user(sender)

    recipients_to = normalize_email_list(metadata.get("to", []))
    recipients_cc = normalize_email_list(metadata.get("cc", []))
    recipients_bcc = normalize_email_list(metadata.get("bcc", []))

    if not recipients_to and not recipients_cc and not recipients_bcc:
        raise ValueError("The held Gmail message has no valid recipients.")

    message = EmailMessage()
    message["From"] = formataddr((smtp_user.username, smtp_user.smtp_email))

    if recipients_to:
        message["To"] = ", ".join(recipients_to)

    if recipients_cc:
        message["Cc"] = ", ".join(recipients_cc)

    message["Subject"] = str(metadata.get("subject", "") or "")
    message.set_content(str(metadata.get("body", "") or ""))

    hold_directory = metadata["hold_directory"]

    for attachment in metadata.get("attachments", []):
        stored_path = os.path.join(
            hold_directory,
            attachment.get("stored_name", "")
        )

        if not os.path.isfile(stored_path):
            raise FileNotFoundError(
                f"Held attachment is missing: {attachment.get('filename', 'unknown')}"
            )

        with open(stored_path, "rb") as attachment_file:
            attachment_bytes = attachment_file.read()

        content_type = str(
            attachment.get("content_type", "application/octet-stream")
        )

        if "/" in content_type:
            maintype, subtype = content_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"

        message.add_attachment(
            attachment_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.get("filename", "attachment")
        )

    message["X-DLP-Approved"] = "true"
    send_smtp_message(smtp_user, message)
    cleanup_held_gmail_email(email_key)

    return {
        "sender": sender,
        "to": recipients_to,
        "cc": recipients_cc,
        "bcc": recipients_bcc,
        "subject": message["Subject"],
        "attachment_names": [
            item.get("filename", "attachment")
            for item in metadata.get("attachments", [])
        ]
    }


def send_gmail_block_notification(
    email_key,
    final_classification,
    blocking_reason,
    decided_by_user
):
    metadata = load_held_gmail_email(email_key)
    original_sender = str(metadata.get("sender", "")).strip()

    if not original_sender or "@" not in original_sender:
        raise ValueError("The original Gmail sender address is unavailable.")

    attachment_names = [
        item.get("filename", "attachment")
        for item in metadata.get("attachments", [])
    ]

    attachment_text = (
        ", ".join(attachment_names)
        if attachment_names
        else "No attachments"
    )

    reviewer_name = getattr(decided_by_user, "username", "unknown")
    reviewer_role = getattr(decided_by_user, "role", "Security Reviewer")

    message = EmailMessage()
    message["From"] = formataddr(
        (reviewer_name, decided_by_user.smtp_email)
    )
    message["To"] = original_sender
    message["Subject"] = (
        "DLP Security Decision: Email Sending Blocked"
    )
    message.set_content(
        "Your outbound Gmail message was blocked by the organization DLP system.\n\n"
        f"Original subject: {metadata.get('subject', '') or '[No Subject]'}\n"
        f"Original recipients: {', '.join(normalize_email_list(metadata.get('to', [])))}\n"
        f"Attachment files: {attachment_text}\n"
        f"Final classification: {str(final_classification).upper()}\n"
        f"Blocking reason: {blocking_reason}\n"
        f"Decision made by: {reviewer_name} ({reviewer_role})\n"
        f"Decision time: {datetime.now()}\n\n"
        "The original email was not sent to its intended recipients."
    )
    message["X-DLP-Notification"] = "blocked-email"

    send_smtp_message(decided_by_user, message)
    cleanup_held_gmail_email(email_key)

    return {
        "original_sender": original_sender,
        "subject": metadata.get("subject", ""),
        "attachment_names": attachment_names
    }


def add_cors_headers(response):

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"

    return response


def cleanup_files(paths):

    for path in paths:

        try:

            if path and os.path.exists(path):
                os.remove(path)

        except Exception:
            pass


def log_incident(sender, recipient, filename, classification, action, confidence):

    incident = EmailIncident(
        sender=sender,
        recipient=recipient,
        filename=filename,
        classification=classification,
        action=action,
        confidence=str(confidence),
        timestamp=datetime.now()
    )

    db.session.add(incident)
    db.session.commit()


def log_file_event(
    filename,
    action,
    label,
    ml_prediction,
    confidence,
    reason,
    actor
):

    session = SessionLocal()

    event = FileEvent(
        filename=filename,
        action=action,
        label=label,
        score=0,
        ml_prediction=ml_prediction,
        ml_confidence=confidence,
        rule_score=0,
        reason=f"ACTOR={actor} || {reason}",
        timestamp=datetime.now()
    )

    session.add(event)
    session.commit()
    session.close()


def risk_value(label):

    label = str(label).upper()

    if label == "SENSITIVE":
        return 3

    if label == "MEDIUM":
        return 2

    return 1


def highest_risk(scan_results):

    if not scan_results:
        return "SAFE", 0

    highest = "SAFE"
    highest_confidence = 0

    for item in scan_results:

        item_classification = str(
            item.get("classification", "SAFE")
        ).upper()

        item_confidence = item.get(
            "confidence",
            0
        )

        if risk_value(item_classification) > risk_value(highest):

            highest = item_classification
            highest_confidence = item_confidence

        elif item_classification == highest:

            try:
                if float(item_confidence) > float(highest_confidence):
                    highest_confidence = item_confidence
            except Exception:
                pass

    return highest, highest_confidence


def safe_browser_filename(filename):

    if not filename:
        return "unnamed_attachment"

    filename = os.path.basename(filename)
    filename = filename.replace("/", "_").replace("\\", "_")

    if not filename.strip():
        return "unnamed_attachment"

    return filename


def short_text(value, limit=180):

    value = str(value or "").strip()

    if len(value) <= limit:
        return value

    return value[:limit] + "..."


def build_email_fingerprint(sender, to_email, cc_email, bcc_email, subject, body, attachments):

    hash_input = [
        str(sender or ""),
        str(to_email or ""),
        str(cc_email or ""),
        str(bcc_email or ""),
        str(subject or ""),
        str(body or "")
    ]

    for attachment in attachments or []:

        if not isinstance(attachment, dict):
            continue

        hash_input.append(
            str(attachment.get("filename", ""))
        )

        hash_input.append(
            str(attachment.get("size", ""))
        )

        content_base64 = str(
            attachment.get("content_base64", "")
        )

        hash_input.append(
            hashlib.sha256(
                content_base64.encode(
                    "utf-8",
                    errors="ignore"
                )
            ).hexdigest()
        )

    joined = "\n---DLP-GMAIL-FINGERPRINT---\n".join(
        hash_input
    )

    return hashlib.sha256(
        joined.encode(
            "utf-8",
            errors="ignore"
        )
    ).hexdigest()


def scan_browser_email_body(to_email, subject, body):

    temp_dir = tempfile.gettempdir()

    temp_path = os.path.join(
        temp_dir,
        f"dlp_browser_gmail_body_{int(datetime.now().timestamp())}.txt"
    )

    combined_content = (
        "GMAIL COMPOSE EMAIL\n\n"
        f"Recipient: {to_email}\n"
        f"Subject: {subject}\n\n"
        "Body:\n"
        f"{body or ''}"
    )

    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(combined_content)

    label, score, _, _, explanation = predict_file(temp_path)

    cleanup_files([temp_path])

    return {
        "name": "GMAIL_COMPOSE_BODY",
        "type": "BODY",
        "classification": label,
        "confidence": explanation.get("ml_confidence", 0),
        "score": score,
        "reason": explanation.get("reason", ""),
        "content_preview": body or ""
    }


def save_browser_attachment_to_temp(attachment, index):

    filename = safe_browser_filename(
        attachment.get("filename", f"attachment_{index}")
    )

    size = int(attachment.get("size", 0) or 0)

    if size > MAX_BROWSER_ATTACHMENT_BYTES:
        raise ValueError(
            f"Attachment {filename} is larger than the allowed browser DLP limit."
        )

    content_base64 = attachment.get("content_base64", "")

    if not content_base64:
        raise ValueError(f"Attachment {filename} has no readable content.")

    try:
        raw_bytes = base64.b64decode(content_base64)
    except Exception:
        raise ValueError(f"Attachment {filename} could not be decoded.")

    if len(raw_bytes) > MAX_BROWSER_ATTACHMENT_BYTES:
        raise ValueError(
            f"Attachment {filename} is larger than the allowed browser DLP limit."
        )

    temp_dir = tempfile.gettempdir()

    temp_path = os.path.join(
        temp_dir,
        f"dlp_browser_gmail_attachment_{int(datetime.now().timestamp())}_{index}_{filename}"
    )

    with open(temp_path, "wb") as f:
        f.write(raw_bytes)

    return temp_path, filename


def scan_browser_attachments(attachments):

    temp_paths = []
    scan_results = []

    if not attachments:
        return temp_paths, scan_results

    for index, attachment in enumerate(attachments, start=1):

        try:

            temp_path, filename = save_browser_attachment_to_temp(
                attachment,
                index
            )

            label, score, _, _, explanation = predict_file(temp_path)

            try:
                extracted_content = read_file_preview(
                    temp_path
                )
            except Exception as e:
                extracted_content = (
                    "Preview unavailable for this attachment: "
                    f"{e}"
                )

            scan_results.append(
                {
                    "name": filename,
                    "type": "ATTACHMENT",
                    "classification": label,
                    "confidence": explanation.get("ml_confidence", 0),
                    "score": score,
                    "reason": explanation.get("reason", ""),
                    "content_preview": extracted_content[:3000]
                }
            )

            temp_paths.append(temp_path)

        except Exception as e:

            filename = safe_browser_filename(
                attachment.get("filename", f"attachment_{index}")
                if isinstance(attachment, dict)
                else f"attachment_{index}"
            )

            scan_results.append(
                {
                    "name": filename,
                    "type": "ATTACHMENT",
                    "classification": "MEDIUM",
                    "confidence": 0.50,
                    "score": 50,
                    "reason": (
                        "Attachment could not be fully scanned by the browser "
                        f"DLP prototype: {e}"
                    ),
                    "content_preview": (
                        "Attachment preview unavailable because the browser "
                        f"DLP prototype could not fully read this attachment: {e}"
                    )
                }
            )

    return temp_paths, scan_results


def summarize_browser_scan_results(scan_results):

    lines = []

    for item in scan_results:

        lines.append(
            f"{item.get('type', 'ITEM')}: "
            f"{item.get('name', 'UNKNOWN')} -> "
            f"{item.get('classification', 'UNKNOWN')} "
            f"(confidence: {item.get('confidence', 0)})"
        )

    return "\n".join(lines)


def build_combined_email_reason(
    sender,
    to_email,
    subject,
    overall_classification,
    overall_confidence,
    scan_results
):

    lines = []

    lines.append(
        f"Overall Gmail AI Classification: {overall_classification}"
    )

    lines.append(
        f"Overall Confidence: {overall_confidence}"
    )

    lines.append("")
    lines.append(f"Sender: {sender}")
    lines.append(f"Recipient: {to_email}")
    lines.append(f"Subject: {subject}")
    lines.append("")
    lines.append("Per-item AI classification details:")

    for item in scan_results:

        lines.append("")
        lines.append(
            f"{item.get('type', 'ITEM')}: {item.get('name', 'UNKNOWN')}"
        )

        lines.append(
            f"Classification: {item.get('classification', 'UNKNOWN')}"
        )

        lines.append(
            f"Confidence: {item.get('confidence', 0)}"
        )

        lines.append(
            "Reason: "
            f"{item.get('reason', 'No detailed reason available.')}"
        )

    lines.append("")
    lines.append(
        "Final overall classification is based on the highest-risk item. "
        "If any body or attachment is SENSITIVE, the whole email is treated "
        "as SENSITIVE. If nothing is SENSITIVE but one or more parts are "
        "MEDIUM, the whole email is treated as MEDIUM."
    )

    return "\n".join(lines)


def build_combined_email_preview(
    sender,
    to_email,
    subject,
    body,
    scan_results
):

    lines = []

    lines.append("GMAIL EMAIL REVIEW CONTENT")
    lines.append("")
    lines.append(f"Sender: {sender}")
    lines.append(f"Recipient: {to_email}")
    lines.append(f"Subject: {subject}")
    lines.append("")
    lines.append("=" * 70)
    lines.append("EMAIL BODY")
    lines.append("=" * 70)
    lines.append(body or "[No readable body content]")
    lines.append("")

    attachment_items = [
        item for item in scan_results
        if item.get("type") == "ATTACHMENT"
    ]

    if attachment_items:

        lines.append("=" * 70)
        lines.append("ATTACHMENTS")
        lines.append("=" * 70)

        for item in attachment_items:

            lines.append("")
            lines.append(f"Attachment: {item.get('name', 'UNKNOWN')}")
            lines.append(
                f"AI Classification: {item.get('classification', 'UNKNOWN')}"
            )
            lines.append(
                f"AI Confidence: {item.get('confidence', 0)}"
            )
            lines.append("")
            lines.append("Extracted Attachment Content:")
            lines.append(
                item.get(
                    "content_preview",
                    "No preview stored for this attachment."
                )
            )
            lines.append("-" * 70)

    else:

        lines.append("=" * 70)
        lines.append("ATTACHMENTS")
        lines.append("=" * 70)
        lines.append("No attachments were included.")

    return "\n".join(lines)


def get_existing_gmail_review(email_key):

    session = SessionLocal()

    try:
        review = session.query(
            ClassificationReview
        ).filter(
            ClassificationReview.channel == "EMAIL",
            ClassificationReview.held_file_path == email_key
        ).order_by(
            ClassificationReview.created_at.desc()
        ).first()

        return review

    finally:
        session.close()


def get_medium_approval_for_email(email_key):

    session = SessionLocal()

    try:
        approval = session.query(
            PendingApproval
        ).filter(
            PendingApproval.channel == "EMAIL",
            PendingApproval.file_path == email_key
        ).order_by(
            PendingApproval.created_at.desc()
        ).first()

        return approval

    finally:
        session.close()


def create_gmail_classification_review(
    sender,
    to_email,
    subject,
    body,
    email_key,
    overall_classification,
    overall_confidence,
    scan_results
):

    session = SessionLocal()

    try:
        existing = session.query(
            ClassificationReview
        ).filter(
            ClassificationReview.channel == "EMAIL",
            ClassificationReview.held_file_path == email_key,
            ClassificationReview.status == "PENDING"
        ).first()

        if existing:
            return existing.id

        filename = (
            "Gmail Email: "
            + short_text(
                subject or "No Subject",
                120
            )
        )

        ai_reason = build_combined_email_reason(
            sender,
            to_email,
            subject,
            overall_classification,
            overall_confidence,
            scan_results
        )

        content_preview = build_combined_email_preview(
            sender,
            to_email,
            subject,
            body,
            scan_results
        )

        review = ClassificationReview(
            filename=filename,
            original_file_path=(
                f"Sender: {sender} -> Recipient: {to_email}"
            ),
            held_file_path=email_key,
            channel="EMAIL",
            actor=sender,
            ai_classification=overall_classification,
            ai_confidence=overall_confidence,
            ai_reason=ai_reason,
            status="PENDING",
            content_preview=content_preview,
            created_at=datetime.now()
        )

        session.add(review)
        session.commit()

        review_id = review.id

        return review_id

    finally:
        session.close()


def response_for_existing_gmail_decision(
    review,
    sender,
    to_email,
    scan_results
):

    status = str(
        review.status or ""
    ).upper()

    final_classification = str(
        review.admin_final_classification
        or review.ai_classification
        or "UNKNOWN"
    ).upper()

    confidence = review.ai_confidence or 0

    if status == "PENDING":

        return {
            "status": "OK",
            "source": "GMAIL_BROWSER_EXTENSION",
            "classification": review.ai_classification,
            "confidence": confidence,
            "action": "PENDING_REVIEW",
            "message": (
                "This Gmail email is already pending admin AI Classification Review."
            ),
            "reason": (
                "The email body and attachments are waiting for admin/security "
                "analyst review in the dashboard."
            ),
            "scan_results": scan_results
        }

    if status == "APPLIED_EMAIL_SAFE_ALLOWED":

        return {
            "status": "OK",
            "source": "GMAIL_BROWSER_EXTENSION",
            "classification": "SAFE",
            "confidence": confidence,
            "action": "ALLOW",
            "message": (
                "Email was approved as SAFE by admin review. Sending is allowed."
            ),
            "reason": (
                "Admin/security analyst approved this Gmail email as SAFE."
            ),
            "scan_results": scan_results
        }

    if status == "APPLIED_EMAIL_SENSITIVE_BLOCKED":

        return {
            "status": "OK",
            "source": "GMAIL_BROWSER_EXTENSION",
            "classification": "SENSITIVE",
            "confidence": confidence,
            "action": "BLOCK",
            "message": (
                "Email was classified as SENSITIVE by admin review and remains blocked."
            ),
            "reason": (
                "Admin/security analyst selected SENSITIVE for this Gmail email."
            ),
            "scan_results": scan_results
        }

    if status == "APPLIED_EMAIL_MEDIUM_PENDING":

        approval = get_medium_approval_for_email(
            review.held_file_path
        )

        if approval and approval.status == "APPROVED":

            return {
                "status": "OK",
                "source": "GMAIL_BROWSER_EXTENSION",
                "classification": "MEDIUM",
                "confidence": confidence,
                "action": "ALLOW",
                "message": (
                    "Email was approved through Medium Approvals. Sending is allowed."
                ),
                "reason": (
                    "Admin/security analyst approved the medium-risk Gmail email."
                ),
                "scan_results": scan_results
            }

        if approval and approval.status in [
            "DELETE_REQUESTED",
            "DELETED",
            "USER_DELETED",
            "REJECTED"
        ]:

            return {
                "status": "OK",
                "source": "GMAIL_BROWSER_EXTENSION",
                "classification": "MEDIUM",
                "confidence": confidence,
                "action": "BLOCK",
                "message": (
                    "Medium-risk Gmail email was rejected in Medium Approvals."
                ),
                "reason": (
                    "The Gmail email was not approved by admin/security analyst."
                ),
                "scan_results": scan_results
            }

        return {
            "status": "OK",
            "source": "GMAIL_BROWSER_EXTENSION",
            "classification": "MEDIUM",
            "confidence": confidence,
            "action": "PENDING_REVIEW",
            "message": (
                "Email is waiting for Medium Approval after AI Classification Review."
            ),
            "reason": (
                "Admin/security analyst selected MEDIUM. The combined Gmail email "
                "body and attachments are now waiting in Medium Approvals."
            ),
            "scan_results": scan_results
        }

    return {
        "status": "OK",
        "source": "GMAIL_BROWSER_EXTENSION",
        "classification": final_classification,
        "confidence": confidence,
        "action": "PENDING_REVIEW",
        "message": (
            "Email review decision is still being processed."
        ),
        "reason": (
            f"Current Gmail review status: {status}"
        ),
        "scan_results": scan_results
    }


@email_bp.route("/compose", methods=["GET", "POST"])
@login_required
def compose():

    return redirect(url_for("dashboard.dashboard_home"))


@email_bp.route("/confirm-medium", methods=["GET", "POST"])
@login_required
def confirm_medium():

    return redirect(url_for("dashboard.dashboard_home"))


@email_bp.route("/delete-medium", methods=["GET", "POST"])
@login_required
def delete_medium():

    return redirect(url_for("dashboard.dashboard_home"))


@email_bp.route("/api/browser-email-scan", methods=["POST", "OPTIONS"])
def browser_email_scan():

    if request.method == "OPTIONS":

        response = make_response("")
        return add_cors_headers(response)

    data = request.get_json(silent=True)

    if not data:

        response = jsonify(
            {
                "status": "ERROR",
                "source": "GMAIL_BROWSER_EXTENSION",
                "classification": "UNKNOWN",
                "confidence": 0,
                "action": "BLOCK",
                "message": "No JSON data received by DLP API.",
                "reason": "The Gmail extension did not send readable email content.",
                "scan_results": []
            }
        )

        return add_cors_headers(response), 400

    to_email = data.get("to", "")
    cc_email = data.get("cc", "")
    bcc_email = data.get("bcc", "")
    subject = data.get("subject", "")
    body = data.get("body", "")
    sender = data.get("sender", "GMAIL_BROWSER_USER")
    attachments = data.get("attachments", [])

    email_fingerprint = build_email_fingerprint(
        sender,
        to_email,
        cc_email,
        bcc_email,
        subject,
        body,
        attachments
    )

    email_key = f"EMAIL_FINGERPRINT:{email_fingerprint}"

    temp_paths = []

    body_result = scan_browser_email_body(
        to_email,
        subject,
        body
    )

    attachment_temp_paths, attachment_results = scan_browser_attachments(
        attachments
    )

    temp_paths.extend(attachment_temp_paths)

    scan_results = [body_result] + attachment_results

    classification, confidence = highest_risk(scan_results)

    try:
        store_held_gmail_email(
            email_key=email_key,
            sender=sender,
            to_email=to_email,
            cc_email=cc_email,
            bcc_email=bcc_email,
            subject=subject,
            body=body,
            attachments=attachments
        )
    except Exception as error:
        cleanup_files(temp_paths)

        response = jsonify(
            {
                "status": "ERROR",
                "source": "GMAIL_BROWSER_EXTENSION",
                "classification": "MEDIUM",
                "confidence": 0.50,
                "action": "BLOCK",
                "message": "Email could not be securely held for admin review.",
                "reason": str(error),
                "scan_results": scan_results
            }
        )

        return add_cors_headers(response), 500

    existing_review = get_existing_gmail_review(
        email_key
    )

    if existing_review:

        cleanup_files(temp_paths)

        result = response_for_existing_gmail_decision(
            existing_review,
            sender,
            to_email,
            scan_results
        )

        response = jsonify(result)
        return add_cors_headers(response)

    review_id = create_gmail_classification_review(
        sender=sender,
        to_email=to_email,
        subject=subject,
        body=body,
        email_key=email_key,
        overall_classification=classification,
        overall_confidence=confidence,
        scan_results=scan_results
    )

    summary = summarize_browser_scan_results(
        scan_results
    )

    try:
        log_incident(
            sender,
            to_email,
            (
                "GMAIL_COMBINED_EMAIL_REVIEW_"
                f"{review_id}"
            ),
            classification,
            "AI_REVIEW_PENDING",
            confidence
        )

        log_file_event(
            filename=(
                "Gmail Email: "
                + short_text(
                    subject or "No Subject",
                    120
                )
            ),
            action="EMAIL_AI_REVIEW_PENDING",
            label=classification,
            ml_prediction=classification,
            confidence=confidence,
            reason=(
                "Gmail email body and attachments were scanned together "
                "and sent as one combined AI Classification Review record."
            ),
            actor=sender
        )

    except Exception as e:

        print(f"[GMAIL EXTENSION LOG WARNING] {e}")

    cleanup_files(temp_paths)

    response = jsonify(
        {
            "status": "OK",
            "source": "GMAIL_BROWSER_EXTENSION",
            "classification": classification,
            "confidence": confidence,
            "action": "PENDING_REVIEW",
            "message": (
                "The Gmail body and attachments were submitted for review. "
                "The email will be sent automatically if approved."
            ),
            "reason": summary,
            "scan_results": scan_results,
            "review_id": review_id
        }
    )

    return add_cors_headers(response)


@email_bp.route("/api/browser-email-decision", methods=["POST", "OPTIONS"])
def browser_email_decision():

    if request.method == "OPTIONS":

        response = make_response("")
        return add_cors_headers(response)

    data = request.get_json(silent=True)

    if not data:

        response = jsonify(
            {
                "status": "ERROR",
                "message": "No JSON data received."
            }
        )

        return add_cors_headers(response), 400

    sender = data.get("sender", "GMAIL_BROWSER_USER")
    to_email = data.get("to", "")
    classification = data.get("classification", "UNKNOWN")
    confidence = data.get("confidence", 0)
    decision = data.get("decision", "UNKNOWN")

    if decision == "MEDIUM_CONFIRMED_SEND":
        dashboard_action = "CONFIRMED_SENT"

    elif decision == "MEDIUM_CANCELLED":
        dashboard_action = "USER_DELETED"

    elif decision == "SENSITIVE_BLOCKED":
        dashboard_action = "BLOCKED"

    elif decision == "SAFE_SENT":
        dashboard_action = "ALLOWED_SENT"

    else:
        dashboard_action = decision

    try:

        log_incident(
            sender,
            to_email,
            "GMAIL_COMPOSE_DECISION",
            classification,
            dashboard_action,
            confidence
        )

    except Exception as e:

        print(f"[GMAIL EXTENSION DECISION LOG WARNING] {e}")

    response = jsonify(
        {
            "status": "OK",
            "message": "Browser email decision logged.",
            "dashboard_action": dashboard_action
        }
    )

    return add_cors_headers(response)
