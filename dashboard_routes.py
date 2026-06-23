import csv
import io
from collections import Counter, defaultdict
from datetime import datetime

from flask import Blueprint, render_template, request, Response
from flask_login import login_required

from web.admin_routes import security_required
from web.models import EmailIncident

try:
    from database.db import SessionLocal as DLP_SessionLocal
    from database.db import FileEvent as DLP_FileEvent
except Exception:
    DLP_SessionLocal = None
    DLP_FileEvent = None


dashboard_bp = Blueprint("dashboard", __name__)


def extract_channel(action):

    if not action:
        return "UNKNOWN"

    if "_" in action:
        return action.split("_")[0]

    return action


def should_hide_dashboard_file(filename, action):

    if not filename:
        return True

    filename_lower = filename.lower()
    action_upper = str(action).upper()

    if filename_lower.endswith(".part"):
        return True

    if ".octransferid" in filename_lower:
        return True

    if "octransferid" in filename_lower:
        return True

    if filename.startswith("."):
        return True

    if filename_lower in [
        "nextcloud.log",
        "index.html"
    ]:
        return True

    if "appdata_" in filename_lower:
        return True

    if action_upper.startswith("NEXTCLOUD") and filename_lower.endswith(".tmp"):
        return True

    return False


def normalize_file_event(event):

    return {
        "source": "FILE_MONITOR",
        "channel": extract_channel(event.action),
        "user": "-",
        "target": event.action,
        "filename": event.filename,
        "classification": event.label,
        "action": event.action,
        "confidence": event.ml_confidence,
        "timestamp": event.timestamp
    }


def collect_email_incidents():

    rows = []

    incidents = EmailIncident.query.order_by(
        EmailIncident.timestamp.desc()
    ).all()

    for incident in incidents:

        rows.append(
            {
                "source": "EMAIL",
                "channel": "EMAIL",
                "user": incident.sender,
                "target": incident.recipient,
                "filename": incident.filename,
                "classification": incident.classification,
                "action": incident.action,
                "confidence": incident.confidence,
                "timestamp": incident.timestamp
            }
        )

    return rows


def collect_file_monitor_incidents(channel_filter=None):

    rows = []

    if not DLP_SessionLocal or not DLP_FileEvent:
        return rows

    session = None

    try:

        session = DLP_SessionLocal()

        events = session.query(
            DLP_FileEvent
        ).order_by(
            DLP_FileEvent.timestamp.desc()
        ).all()

        for event in events:

            if should_hide_dashboard_file(
                event.filename,
                event.action
            ):
                continue

            row = normalize_file_event(event)

            if channel_filter is None or row["channel"] == channel_filter:
                rows.append(row)

    except Exception as e:

        print(f"[DASHBOARD WARNING] {e}")

    finally:

        if session:
            session.close()

    return rows


def collect_all_incidents():

    rows = []

    rows.extend(collect_email_incidents())

    rows.extend(collect_file_monitor_incidents())

    rows.sort(
        key=lambda item: item["timestamp"],
        reverse=True
    )

    return rows


def is_blocked_or_quarantined(row):

    classification = str(row.get("classification", "")).upper()
    action = str(row.get("action", "")).upper()

    if classification == "SENSITIVE":
        return True

    if "BLOCK" in action:
        return True

    if "QUARANTINE" in action:
        return True

    if "DELETE" in action:
        return True

    if "REMOVED" in action:
        return True

    return False


def calculate_stats(rows):

    total = len(rows)

    safe = sum(
        1 for row in rows
        if row["classification"] == "SAFE"
    )

    medium = sum(
        1 for row in rows
        if row["classification"] == "MEDIUM"
    )

    sensitive = sum(
        1 for row in rows
        if row["classification"] == "SENSITIVE"
    )

    blocked = sum(
        1 for row in rows
        if is_blocked_or_quarantined(row)
    )

    return {
        "total": total,
        "safe": safe,
        "medium": medium,
        "sensitive": sensitive,
        "blocked": blocked
    }


def get_filters():

    return {
        "q": request.args.get("q", "").strip(),
        "classification": request.args.get("classification", "").strip(),
        "action": request.args.get("action", "").strip(),
        "channel": request.args.get("channel", "").strip(),
    }


def row_matches_search(row, query):

    if not query:
        return True

    query = query.lower()

    searchable_text = " ".join(
        [
            str(row.get("source", "")),
            str(row.get("channel", "")),
            str(row.get("user", "")),
            str(row.get("target", "")),
            str(row.get("filename", "")),
            str(row.get("classification", "")),
            str(row.get("action", "")),
            str(row.get("confidence", "")),
            str(row.get("timestamp", "")),
        ]
    ).lower()

    return query in searchable_text


def apply_filters(rows, filters):

    filtered = []

    for row in rows:

        if filters["classification"]:

            if str(row.get("classification", "")).upper() != filters["classification"].upper():
                continue

        if filters["action"]:

            if filters["action"].upper() not in str(row.get("action", "")).upper():
                continue

        if filters["channel"]:

            if str(row.get("channel", "")).upper() != filters["channel"].upper():
                continue

        if not row_matches_search(row, filters["q"]):
            continue

        filtered.append(row)

    return filtered


def count_by(rows, key):

    counter = Counter()

    for row in rows:

        value = str(row.get(key, "UNKNOWN"))

        if not value:
            value = "UNKNOWN"

        counter[value] += 1

    return dict(counter)


def action_group(action):

    action_upper = str(action).upper()

    if "ALLOW" in action_upper:
        return "ALLOWED"

    if "PENDING" in action_upper:
        return "PENDING"

    if "CONFIRM" in action_upper:
        return "CONFIRMED"

    if "BLOCK" in action_upper:
        return "BLOCKED"

    if "QUARANTINE" in action_upper:
        return "QUARANTINED"

    if "DELETE" in action_upper:
        return "DELETED"

    if "CANCEL" in action_upper:
        return "CANCELLED"

    return action_upper if action_upper else "UNKNOWN"


def normalize_date(timestamp):

    if not timestamp:
        return "Unknown"

    if isinstance(timestamp, datetime):
        return timestamp.strftime("%Y-%m-%d")

    try:
        return str(timestamp).split(" ")[0]
    except Exception:
        return "Unknown"


def build_bar_chart_data(counter_dict):

    if not counter_dict:
        return []

    max_value = max(counter_dict.values())

    chart_data = []

    for label, value in counter_dict.items():

        percent = int((value / max_value) * 100) if max_value else 0

        chart_data.append(
            {
                "label": label,
                "value": value,
                "percent": percent
            }
        )

    chart_data.sort(
        key=lambda item: item["value"],
        reverse=True
    )

    return chart_data


def calculate_analytics(rows):

    classification_counts = {
        "SAFE": 0,
        "MEDIUM": 0,
        "SENSITIVE": 0
    }

    for row in rows:

        classification = str(row.get("classification", "")).upper()

        if classification in classification_counts:
            classification_counts[classification] += 1

    channel_counts = count_by(rows, "channel")

    grouped_actions = Counter()

    for row in rows:
        grouped_actions[action_group(row.get("action", ""))] += 1

    timeline_counter = defaultdict(int)

    for row in rows:
        timeline_counter[normalize_date(row.get("timestamp"))] += 1

    timeline = dict(
        sorted(
            timeline_counter.items(),
            key=lambda item: item[0],
            reverse=False
        )[-10:]
    )

    return {
        "classification": build_bar_chart_data(classification_counts),
        "channel": build_bar_chart_data(channel_counts),
        "action": build_bar_chart_data(dict(grouped_actions)),
        "timeline": build_bar_chart_data(timeline)
    }


def make_csv_response(rows, filename):

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow(
        [
            "Source",
            "Channel",
            "User/Sender",
            "Target/Recipient",
            "File/Item",
            "Classification",
            "Action",
            "Confidence",
            "Timestamp"
        ]
    )

    for row in rows:

        writer.writerow(
            [
                row.get("source", ""),
                row.get("channel", ""),
                row.get("user", ""),
                row.get("target", ""),
                row.get("filename", ""),
                row.get("classification", ""),
                row.get("action", ""),
                row.get("confidence", ""),
                row.get("timestamp", "")
            ]
        )

    response = Response(
        output.getvalue(),
        mimetype="text/csv"
    )

    response.headers[
        "Content-Disposition"
    ] = f"attachment; filename={filename}"

    return response


def render_channel_dashboard(
    title,
    subtitle,
    rows,
    template="dashboard_channel.html"
):

    filters = get_filters()

    filtered_rows = apply_filters(rows, filters)

    stats = calculate_stats(filtered_rows)

    analytics = calculate_analytics(filtered_rows)

    return render_template(
        template,
        rows=filtered_rows,
        stats=stats,
        analytics=analytics,
        page_title=title,
        page_subtitle=subtitle,
        filters=filters
    )


@dashboard_bp.route("/dashboard")
@login_required
@security_required
def dashboard_home():

    all_rows = collect_all_incidents()

    filters = get_filters()

    filtered_rows = apply_filters(all_rows, filters)

    stats = calculate_stats(filtered_rows)

    analytics = calculate_analytics(filtered_rows)

    channel_counts = {
        "email": len(collect_email_incidents()),
        "local": len(collect_file_monitor_incidents("LOCAL")),
        "ftp": len(collect_file_monitor_incidents("FTP")),
        "smb": len(collect_file_monitor_incidents("SMB")),
        "nextcloud": len(collect_file_monitor_incidents("NEXTCLOUD")),
        "usb": len(collect_file_monitor_incidents("USB")),
    }

    return render_template(
        "dashboard_home.html",
        rows=filtered_rows[:50],
        stats=stats,
        analytics=analytics,
        channel_counts=channel_counts,
        filters=filters
    )


@dashboard_bp.route("/dashboard/export")
@login_required
@security_required
def export_dashboard_home():

    rows = collect_all_incidents()

    filters = get_filters()

    filtered_rows = apply_filters(rows, filters)

    return make_csv_response(
        filtered_rows,
        "central_dlp_dashboard_export.csv"
    )


@dashboard_bp.route("/dashboard/email")
@login_required
@security_required
def dashboard_email():

    rows = collect_email_incidents()

    return render_channel_dashboard(
        "Email DLP Dashboard",
        "Outbound email body and attachment incidents.",
        rows
    )


@dashboard_bp.route("/dashboard/email/export")
@login_required
@security_required
def export_dashboard_email():

    rows = collect_email_incidents()

    filters = get_filters()

    filtered_rows = apply_filters(rows, filters)

    return make_csv_response(
        filtered_rows,
        "email_dlp_dashboard_export.csv"
    )


@dashboard_bp.route("/dashboard/local")
@login_required
@security_required
def dashboard_local():

    rows = collect_file_monitor_incidents("LOCAL")

    return render_channel_dashboard(
        "Local Endpoint DLP Dashboard",
        "Local watched-folder file activity and quarantine decisions.",
        rows
    )


@dashboard_bp.route("/dashboard/local/export")
@login_required
@security_required
def export_dashboard_local():

    rows = collect_file_monitor_incidents("LOCAL")

    filters = get_filters()

    filtered_rows = apply_filters(rows, filters)

    return make_csv_response(
        filtered_rows,
        "local_dlp_dashboard_export.csv"
    )


@dashboard_bp.route("/dashboard/ftp")
@login_required
@security_required
def dashboard_ftp():

    rows = collect_file_monitor_incidents("FTP")

    return render_channel_dashboard(
        "FTP DLP Dashboard",
        "Real FTP upload and transfer incidents.",
        rows
    )


@dashboard_bp.route("/dashboard/ftp/export")
@login_required
@security_required
def export_dashboard_ftp():

    rows = collect_file_monitor_incidents("FTP")

    filters = get_filters()

    filtered_rows = apply_filters(rows, filters)

    return make_csv_response(
        filtered_rows,
        "ftp_dlp_dashboard_export.csv"
    )


@dashboard_bp.route("/dashboard/smb")
@login_required
@security_required
def dashboard_smb():

    rows = collect_file_monitor_incidents("SMB")

    return render_channel_dashboard(
        "SMB DLP Dashboard",
        "Real Samba network-share file transfer incidents.",
        rows
    )


@dashboard_bp.route("/dashboard/smb/export")
@login_required
@security_required
def export_dashboard_smb():

    rows = collect_file_monitor_incidents("SMB")

    filters = get_filters()

    filtered_rows = apply_filters(rows, filters)

    return make_csv_response(
        filtered_rows,
        "smb_dlp_dashboard_export.csv"
    )


@dashboard_bp.route("/dashboard/nextcloud")
@login_required
@security_required
def dashboard_nextcloud():

    rows = collect_file_monitor_incidents("NEXTCLOUD")

    return render_channel_dashboard(
        "Nextcloud DLP Dashboard",
        "Cloud collaboration upload incidents from Nextcloud.",
        rows
    )


@dashboard_bp.route("/dashboard/nextcloud/export")
@login_required
@security_required
def export_dashboard_nextcloud():

    rows = collect_file_monitor_incidents("NEXTCLOUD")

    filters = get_filters()

    filtered_rows = apply_filters(rows, filters)

    return make_csv_response(
        filtered_rows,
        "nextcloud_dlp_dashboard_export.csv"
    )


@dashboard_bp.route("/dashboard/usb")
@login_required
@security_required
def dashboard_usb():

    rows = collect_file_monitor_incidents("USB")

    return render_channel_dashboard(
        "USB / Removable Media DLP Dashboard",
        "Removable media incidents. This will become active when real USB monitoring is added.",
        rows
    )


@dashboard_bp.route("/dashboard/usb/export")
@login_required
@security_required
def export_dashboard_usb():

    rows = collect_file_monitor_incidents("USB")

    filters = get_filters()

    filtered_rows = apply_filters(rows, filters)

    return make_csv_response(
        filtered_rows,
        "usb_dlp_dashboard_export.csv"
    )
