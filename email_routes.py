import os
import json
import tempfile
import smtplib

from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required, current_user

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from content_classifier import predict_file

from web.models import db, EmailIncident


email_bp = Blueprint("email", __name__)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465


def log_incident(sender, recipient, filename, classification, action, confidence):

    incident = EmailIncident(
        sender=sender,
        recipient=recipient,
        filename=filename,
        classification=classification,
        action=action,
        confidence=str(confidence),
        timestamp=datetime.now(timezone.utc)
    )

    db.session.add(incident)
    db.session.commit()


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

        item_classification = item["classification"]
        item_confidence = item["confidence"]

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


def cleanup_files(paths):

    for path in paths:

        try:

            if path and os.path.exists(path):
                os.remove(path)

        except Exception:
            pass


def send_email(to_email, subject, message, attachment_paths=None):

    sender_email = current_user.smtp_email
    sender_password = current_user.smtp_password

    if attachment_paths is None:
        attachment_paths = []

    msg = MIMEMultipart()

    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject

    body = (
        f"Corporate User: {current_user.username}\n\n"
        f"{message}"
    )

    msg.attach(MIMEText(body, "plain"))

    for attachment_path in attachment_paths:

        if attachment_path and os.path.exists(attachment_path):

            filename = os.path.basename(attachment_path)

            with open(attachment_path, "rb") as attachment:

                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())

            encoders.encode_base64(part)

            part.add_header(
                "Content-Disposition",
                f"attachment; filename={filename}"
            )

            msg.attach(part)

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:

        server.login(sender_email, sender_password)
        server.send_message(msg)


def scan_email_body(message):

    temp_dir = tempfile.gettempdir()

    body_path = os.path.join(
        temp_dir,
        f"dlp_mail_body_{current_user.id}_{int(datetime.now().timestamp())}.txt"
    )

    with open(body_path, "w", encoding="utf-8") as f:
        f.write(message or "")

    label, score, _, _, explanation = predict_file(body_path)

    cleanup_files([body_path])

    return {
        "name": "EMAIL_BODY",
        "classification": label,
        "confidence": explanation["ml_confidence"],
        "path": ""
    }


def scan_attachments(uploaded_files):

    temp_paths = []
    filenames = []
    scan_results = []

    temp_dir = tempfile.gettempdir()

    for uploaded_file in uploaded_files:

        if not uploaded_file or uploaded_file.filename == "":
            continue

        filename = uploaded_file.filename

        safe_filename = filename.replace("/", "_").replace("\\", "_")

        temp_path = os.path.join(
            temp_dir,
            f"dlp_mail_{current_user.id}_{int(datetime.now().timestamp())}_{safe_filename}"
        )

        uploaded_file.save(temp_path)

        label, score, _, _, explanation = predict_file(temp_path)

        temp_paths.append(temp_path)
        filenames.append(filename)

        scan_results.append(
            {
                "name": filename,
                "classification": label,
                "confidence": explanation["ml_confidence"],
                "path": temp_path
            }
        )

    return temp_paths, filenames, scan_results


@email_bp.route("/compose", methods=["GET", "POST"])
@login_required
def compose():

    result = False
    classification = ""
    confidence = ""
    css_class = ""
    recipient = ""
    subject = ""
    message = ""
    temp_paths = []
    filenames = []
    scan_results = []

    if request.method == "POST":

        recipient = request.form["to"]
        subject = request.form["subject"]
        message = request.form["message"]

        uploaded_files = request.files.getlist("attachments")

        body_result = scan_email_body(message)

        temp_paths, filenames, attachment_results = scan_attachments(uploaded_files)

        scan_results = [body_result] + attachment_results

        classification, confidence = highest_risk(scan_results)

        result = True

        if classification == "SAFE":

            send_email(
                recipient,
                subject,
                message,
                temp_paths
            )

            cleanup_files(temp_paths)

            css_class = "safe"

            for item in scan_results:

                log_incident(
                    current_user.smtp_email,
                    recipient,
                    item["name"],
                    item["classification"],
                    "ALLOWED_SENT",
                    item["confidence"]
                )

        elif classification == "MEDIUM":

            css_class = "medium"

            for item in scan_results:

                log_incident(
                    current_user.smtp_email,
                    recipient,
                    item["name"],
                    item["classification"],
                    "PENDING_CONFIRMATION",
                    item["confidence"]
                )

        elif classification == "SENSITIVE":

            cleanup_files(temp_paths)

            css_class = "sensitive"

            for item in scan_results:

                log_incident(
                    current_user.smtp_email,
                    recipient,
                    item["name"],
                    item["classification"],
                    "BLOCKED",
                    item["confidence"]
                )

    return render_template(
        "compose.html",
        result=result,
        sender=current_user.smtp_email,
        recipient=recipient,
        classification=classification,
        confidence=confidence,
        css_class=css_class,
        subject=subject,
        message=message,
        temp_paths_json=json.dumps(temp_paths),
        filenames_json=json.dumps(filenames),
        scan_results=scan_results,
        scan_results_json=json.dumps(scan_results)
    )


@email_bp.route("/confirm-medium", methods=["POST"])
@login_required
def confirm_medium():

    recipient = request.form.get("to")
    subject = request.form.get("subject")
    message = request.form.get("message")
    temp_paths_json = request.form.get("temp_paths_json")
    filenames_json = request.form.get("filenames_json")
    scan_results_json = request.form.get("scan_results_json")

    if not temp_paths_json:

        return redirect(url_for("email.compose"))

    temp_paths = json.loads(temp_paths_json)
    filenames = json.loads(filenames_json) if filenames_json else []
    scan_results = json.loads(scan_results_json) if scan_results_json else []

    existing_paths = [
        path for path in temp_paths
        if os.path.exists(path)
    ]

    if not existing_paths:

        return render_template(
            "compose.html",
            result=True,
            sender=current_user.smtp_email,
            recipient=recipient,
            classification="MEDIUM",
            confidence="expired",
            css_class="medium",
            subject=subject,
            message=message,
            temp_paths_json="[]",
            filenames_json="[]",
            scan_results=scan_results,
            scan_results_json=json.dumps(scan_results)
        )

    send_email(
        recipient,
        subject,
        message,
        existing_paths
    )

    cleanup_files(existing_paths)

    for item in scan_results:

        log_incident(
            current_user.smtp_email,
            recipient,
            item["name"],
            item["classification"],
            "CONFIRMED_SENT",
            item["confidence"]
        )

    return render_template(
        "compose.html",
        result=True,
        sender=current_user.smtp_email,
        recipient=recipient,
        classification="MEDIUM",
        confidence="confirmed",
        css_class="medium",
        subject=subject,
        message=message,
        temp_paths_json="[]",
        filenames_json=json.dumps(filenames),
        scan_results=scan_results,
        scan_results_json=json.dumps(scan_results)
    )


@email_bp.route("/delete-medium", methods=["POST"])
@login_required
def delete_medium():

    recipient = request.form.get("to")
    temp_paths_json = request.form.get("temp_paths_json")
    scan_results_json = request.form.get("scan_results_json")

    temp_paths = json.loads(temp_paths_json) if temp_paths_json else []
    scan_results = json.loads(scan_results_json) if scan_results_json else []

    cleanup_files(temp_paths)

    for item in scan_results:

        log_incident(
            current_user.smtp_email,
            recipient,
            item["name"],
            item["classification"],
            "USER_DELETED",
            item["confidence"]
        )

    return redirect(url_for("email.compose"))
