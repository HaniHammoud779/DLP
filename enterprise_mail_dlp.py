import os
import json
import tempfile
import smtplib

from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    request,
    redirect,
    url_for,
    render_template_string
)

from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)

from flask_sqlalchemy import SQLAlchemy

from sqlalchemy import text

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase

from email import encoders

from content_classifier import predict_file


app = Flask(__name__)

app.config["SECRET_KEY"] = "enterprise-dlp-secret-key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///enterprise_mail_users.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465


class User(UserMixin, db.Model):

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    smtp_email = db.Column(
        db.String(150),
        nullable=False
    )

    smtp_password = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(50),
        nullable=False,
        default="Employee"
    )


class EmailIncident(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    sender = db.Column(
        db.String(150),
        nullable=False
    )

    recipient = db.Column(
        db.String(150),
        nullable=False
    )

    filename = db.Column(
        db.String(255),
        nullable=False
    )

    classification = db.Column(
        db.String(50),
        nullable=False
    )

    action = db.Column(
        db.String(50),
        nullable=False
    )

    confidence = db.Column(
        db.String(50),
        nullable=False
    )

    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )


@login_manager.user_loader
def load_user(user_id):

    return User.query.get(int(user_id))


def ensure_database_schema():

    db.create_all()

    try:

        result = db.session.execute(
            text("PRAGMA table_info(user)")
        )

        columns = [
            row[1]
            for row in result.fetchall()
        ]

        if "role" not in columns:

            db.session.execute(
                text(
                    "ALTER TABLE user "
                    "ADD COLUMN role VARCHAR(50) "
                    "NOT NULL DEFAULT 'Employee'"
                )
            )

            db.session.commit()

    except Exception as e:

        print(f"[DB SCHEMA WARNING] {e}")

    try:

        admin_exists = User.query.filter_by(
            role="Admin"
        ).first()

        first_user = User.query.order_by(
            User.id.asc()
        ).first()

        if first_user and not admin_exists:

            first_user.role = "Admin"

            db.session.commit()

            print(
                f"[ACCESS CONTROL] "
                f"User {first_user.username} promoted to Admin."
            )

    except Exception as e:

        print(f"[ROLE INIT WARNING] {e}")


def is_security_user():

    return (
        current_user.is_authenticated
        and current_user.role in [
            "Admin",
            "Security Analyst"
        ]
    )


def is_admin():

    return (
        current_user.is_authenticated
        and current_user.role == "Admin"
    )


def security_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not is_security_user():

            return render_template_string(
                ACCESS_DENIED_PAGE,
                style=BASE_STYLE
            )

        return function(*args, **kwargs)

    return wrapper


def admin_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if not is_admin():

            return render_template_string(
                ACCESS_DENIED_PAGE,
                style=BASE_STYLE
            )

        return function(*args, **kwargs)

    return wrapper


def log_incident(
    sender,
    recipient,
    filename,
    classification,
    action,
    confidence
):

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

        if risk_value(item["classification"]) > risk_value(highest):

            highest = item["classification"]
            highest_confidence = item["confidence"]

        elif item["classification"] == highest:

            try:

                if float(item["confidence"]) > float(highest_confidence):

                    highest_confidence = item["confidence"]

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


BASE_STYLE = """
<style>

body {
    font-family: Arial, sans-serif;
    background: #f3f6fb;
    margin: 0;
    padding: 0;
}

.container {
    max-width: 1100px;
    margin: 50px auto;
    background: white;
    padding: 30px;
    border-radius: 14px;
    box-shadow: 0 6px 20px rgba(0,0,0,0.12);
}

h2 {
    text-align: center;
    color: #1f2937;
}

input, textarea, select {
    width: 100%;
    padding: 12px;
    margin-top: 12px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    font-size: 14px;
    box-sizing: border-box;
}

button {
    width: 100%;
    padding: 12px;
    margin-top: 16px;
    background: #2563eb;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    cursor: pointer;
}

button:hover {
    background: #1d4ed8;
}

.link {
    text-align: center;
    margin-top: 16px;
}

.link a {
    color: #2563eb;
    text-decoration: none;
}

.topbar {
    background: #111827;
    color: white;
    padding: 14px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.topbar a {
    color: white;
    text-decoration: none;
    margin-left: 18px;
}

.role-badge {
    background: #2563eb;
    padding: 4px 8px;
    border-radius: 8px;
    margin-left: 8px;
    font-size: 12px;
}

.safe {
    color: #15803d;
    font-weight: bold;
}

.medium {
    color: #d97706;
    font-weight: bold;
}

.sensitive {
    color: #dc2626;
    font-weight: bold;
}

.result {
    margin-top: 25px;
    padding: 18px;
    border-radius: 10px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
}

.warning-box {
    margin-top: 20px;
    padding: 15px;
    background: #fff7ed;
    border: 1px solid #fed7aa;
    border-radius: 10px;
}

.danger-box {
    margin-top: 20px;
    padding: 15px;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 10px;
}

.success-box {
    margin-top: 20px;
    padding: 15px;
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 10px;
}

.scan-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 18px;
}

.scan-table th,
.scan-table td {
    border: 1px solid #d1d5db;
    padding: 10px;
    text-align: left;
    font-size: 14px;
}

.scan-table th {
    background: #111827;
    color: white;
}

.table-wrapper {
    overflow-x: auto;
    margin-top: 25px;
}

.incident-table {
    width: 100%;
    border-collapse: collapse;
    min-width: 1200px;
}

.incident-table th,
.incident-table td {
    border: 1px solid #d1d5db;
    padding: 12px;
    text-align: left;
    font-size: 14px;
    vertical-align: top;
    white-space: nowrap;
}

.incident-table th {
    background: #111827;
    color: white;
}

.incident-table td {
    background: white;
}

.timestamp-column {
    min-width: 220px;
}

.sender-column {
    min-width: 250px;
}

.recipient-column {
    min-width: 250px;
}

.file-column {
    min-width: 160px;
}

.classification-column {
    min-width: 140px;
}

.action-column {
    min-width: 180px;
}

.confidence-column {
    min-width: 100px;
}

.role-column {
    min-width: 170px;
}

</style>
"""


def topbar(title):

    return f"""
<div class="topbar">

<div>
{title}
<span class="role-badge">
{current_user.role if current_user.is_authenticated else ""}
</span>
</div>

<div>
<a href="{url_for('compose')}">Compose</a>
"""

def topbar_links():

    links = ""

    if is_security_user():

        links += f'<a href="{url_for("incidents")}">Incidents</a>'

    if is_admin():

        links += f'<a href="{url_for("users")}">Users</a>'

    links += f'<a href="{url_for("logout")}">Logout</a>'

    return links + "</div></div>"


ACCESS_DENIED_PAGE = """
<!DOCTYPE html>
<html>

<head>
<title>Access Denied</title>
{{ style|safe }}
</head>

<body>

<div class="container">

<h2>Access Denied</h2>

<div class="danger-box">
You do not have permission to access this page.
</div>

<div class="link">
<a href="{{ url_for('compose') }}">Back to Compose</a>
</div>

</div>

</body>
</html>
"""


REGISTER_PAGE = """
<!DOCTYPE html>
<html>

<head>
<title>Register</title>
{{ style|safe }}
</head>

<body>

<div class="container">

<h2>Create Corporate Account</h2>

<form method="POST">

<input type="text" name="username" placeholder="Username" required>

<input type="email" name="email" placeholder="Corporate Email Identity" required>

<input type="password" name="password" placeholder="Portal Password" required>

<input type="email" name="smtp_email" placeholder="Real Gmail Address" required>

<input type="password" name="smtp_password" placeholder="Gmail App Password" required>

<button type="submit">Register</button>

</form>

<div class="link">
Already have account?
<a href="{{ url_for('login') }}">Login</a>
</div>

{% if message %}
<div class="danger-box">
{{ message }}
</div>
{% endif %}

</div>

</body>
</html>
"""


LOGIN_PAGE = """
<!DOCTYPE html>
<html>

<head>
<title>Login</title>
{{ style|safe }}
</head>

<body>

<div class="container">

<h2>Enterprise Mail DLP Login</h2>

<form method="POST">

<input type="text" name="username" placeholder="Username" required>

<input type="password" name="password" placeholder="Password" required>

<button type="submit">Login</button>

</form>

<div class="link">
No account?
<a href="{{ url_for('register') }}">Register</a>
</div>

{% if message %}
<div class="danger-box">
{{ message }}
</div>
{% endif %}

</div>

</body>
</html>
"""


COMPOSE_PAGE = """
<!DOCTYPE html>
<html>

<head>
<title>Secure Corporate Mail</title>
{{ style|safe }}
</head>

<body>

{{ topbar|safe }}

<div class="container">

<h2>Compose Secure Email</h2>

<form method="POST" enctype="multipart/form-data">

<input type="email" name="to" placeholder="Recipient Email" required>

<input type="text" name="subject" placeholder="Subject" required>

<textarea name="message" rows="8" placeholder="Message"></textarea>

<input type="file" name="attachments" multiple required>

<button type="submit">Scan and Send</button>

</form>

{% if result %}

<div class="result">

<h3>DLP Scan Result</h3>

<p>
Sender:
<strong>{{ sender }}</strong>
</p>

<p>
Recipient:
<strong>{{ recipient }}</strong>
</p>

<p>
Final Classification:
<span class="{{ css_class }}">
{{ classification }}
</span>
</p>

<p>
Final Confidence:
<strong>{{ confidence }}</strong>
</p>

{% if scan_results %}

<table class="scan-table">

<tr>
<th>Scanned Item</th>
<th>Classification</th>
<th>Confidence</th>
</tr>

{% for item in scan_results %}

<tr>

<td>{{ item.name }}</td>

<td>
<span class="
{% if item.classification == 'SAFE' %}safe
{% elif item.classification == 'MEDIUM' %}medium
{% elif item.classification == 'SENSITIVE' %}sensitive
{% endif %}
">
{{ item.classification }}
</span>
</td>

<td>{{ item.confidence }}</td>

</tr>

{% endfor %}

</table>

{% endif %}

{% if classification == "SAFE" %}

<div class="success-box">
Email body and attachments are SAFE.
Email sent successfully.
</div>

{% elif classification == "MEDIUM" %}

{% if confidence == "confirmed" %}

<div class="success-box">
MEDIUM-risk content detected.
User confirmed the action.
Email sent successfully.
</div>

{% elif confidence == "expired" %}

<div class="danger-box">
The confirmation session expired.
Please scan the email again.
</div>

{% else %}

<div class="warning-box">
MEDIUM-risk content detected in the email body or attachments.
Please confirm the action or delete the email.
</div>

<form method="POST" action="{{ url_for('confirm_medium') }}">

<input type="hidden" name="to" value="{{ recipient }}">
<input type="hidden" name="subject" value="{{ subject }}">
<input type="hidden" name="message" value="{{ message }}">
<input type="hidden" name="temp_paths_json" value="{{ temp_paths_json }}">
<input type="hidden" name="filenames_json" value="{{ filenames_json }}">
<input type="hidden" name="confidence" value="{{ confidence }}">
<input type="hidden" name="scan_results_json" value='{{ scan_results_json }}'>

<button type="submit">Confirm and Send</button>

</form>

<form method="POST" action="{{ url_for('delete_medium') }}">

<input type="hidden" name="temp_paths_json" value="{{ temp_paths_json }}">
<input type="hidden" name="to" value="{{ recipient }}">
<input type="hidden" name="filenames_json" value="{{ filenames_json }}">
<input type="hidden" name="scan_results_json" value='{{ scan_results_json }}'>

<button
type="submit"
style="background:#dc2626;margin-top:10px;"
>
Delete Email
</button>

</form>

{% endif %}

{% elif classification == "SENSITIVE" %}

<div class="danger-box">
SENSITIVE content detected in the email body or attachments.
Email blocked by DLP policy.
</div>

{% endif %}

</div>

{% endif %}

</div>

</body>
</html>
"""


INCIDENTS_PAGE = """
<!DOCTYPE html>
<html>

<head>
<title>Email DLP Incidents</title>
{{ style|safe }}
</head>

<body>

{{ topbar|safe }}

<div class="container">

<h2>Email DLP Incidents</h2>

<div class="table-wrapper">

<table class="incident-table">

<tr>
<th>ID</th>
<th class="sender-column">Sender</th>
<th class="recipient-column">Recipient</th>
<th class="file-column">Item</th>
<th class="classification-column">Classification</th>
<th class="action-column">Action</th>
<th class="confidence-column">Confidence</th>
<th class="timestamp-column">Timestamp</th>
</tr>

{% for incident in incidents %}

<tr>

<td>{{ incident.id }}</td>

<td class="sender-column">{{ incident.sender }}</td>

<td class="recipient-column">{{ incident.recipient }}</td>

<td class="file-column">{{ incident.filename }}</td>

<td class="classification-column">
<span class="
{% if incident.classification == 'SAFE' %}safe
{% elif incident.classification == 'MEDIUM' %}medium
{% elif incident.classification == 'SENSITIVE' %}sensitive
{% endif %}
">
{{ incident.classification }}
</span>
</td>

<td class="action-column">{{ incident.action }}</td>

<td class="confidence-column">{{ incident.confidence }}</td>

<td class="timestamp-column">{{ incident.timestamp }}</td>

</tr>

{% endfor %}

</table>

</div>

</div>

</body>
</html>
"""


USERS_PAGE = """
<!DOCTYPE html>
<html>

<head>
<title>User Management</title>
{{ style|safe }}
</head>

<body>

{{ topbar|safe }}

<div class="container">

<h2>User Role Management</h2>

<div class="table-wrapper">

<table class="incident-table">

<tr>
<th>ID</th>
<th>Username</th>
<th>Email</th>
<th>SMTP Email</th>
<th class="role-column">Current Role</th>
<th class="role-column">Update Role</th>
</tr>

{% for user in users %}

<tr>

<td>{{ user.id }}</td>

<td>{{ user.username }}</td>

<td>{{ user.email }}</td>

<td>{{ user.smtp_email }}</td>

<td class="role-column">
<strong>{{ user.role }}</strong>
</td>

<td class="role-column">

<form method="POST" action="{{ url_for('update_role') }}">

<input type="hidden" name="user_id" value="{{ user.id }}">

<select name="role">
<option value="Employee" {% if user.role == "Employee" %}selected{% endif %}>Employee</option>
<option value="Security Analyst" {% if user.role == "Security Analyst" %}selected{% endif %}>Security Analyst</option>
<option value="Admin" {% if user.role == "Admin" %}selected{% endif %}>Admin</option>
</select>

<button type="submit">Update</button>

</form>

</td>

</tr>

{% endfor %}

</table>

</div>

</div>

</body>
</html>
"""


def send_email(
    to_email,
    subject,
    message,
    attachment_paths=None
):

    sender_email = current_user.smtp_email
    sender_password = current_user.smtp_password

    if attachment_paths is None:
        attachment_paths = []

    msg = MIMEMultipart()

    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject

    body = (
        f"Corporate User: "
        f"{current_user.username}\n\n"
        f"{message}"
    )

    msg.attach(
        MIMEText(body, "plain")
    )

    for attachment_path in attachment_paths:

        if attachment_path and os.path.exists(attachment_path):

            filename = os.path.basename(attachment_path)

            with open(attachment_path, "rb") as attachment:

                part = MIMEBase(
                    "application",
                    "octet-stream"
                )

                part.set_payload(
                    attachment.read()
                )

            encoders.encode_base64(part)

            part.add_header(
                "Content-Disposition",
                f"attachment; filename={filename}"
            )

            msg.attach(part)

    with smtplib.SMTP_SSL(
        SMTP_SERVER,
        SMTP_PORT
    ) as server:

        server.login(
            sender_email,
            sender_password
        )

        server.send_message(msg)


def scan_email_body(message):

    temp_dir = tempfile.gettempdir()

    body_path = os.path.join(
        temp_dir,
        f"dlp_mail_body_{current_user.id}.txt"
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

        temp_path = os.path.join(
            temp_dir,
            f"dlp_mail_{current_user.id}_{int(datetime.now().timestamp())}_{filename}"
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


@app.route("/")
def index():

    if current_user.is_authenticated:

        return redirect(
            url_for("compose")
        )

    return redirect(
        url_for("login")
    )


@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    message = ""

    if request.method == "POST":

        username = request.form["username"].strip()

        email = request.form["email"].strip()

        password = request.form["password"]

        smtp_email = request.form["smtp_email"].strip()

        smtp_password = request.form["smtp_password"].strip()

        existing_user = User.query.filter(
            (User.username == username)
            |
            (User.email == email)
        ).first()

        if existing_user:

            message = "User already exists."

        else:

            user_count = User.query.count()

            assigned_role = "Admin" if user_count == 0 else "Employee"

            new_user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                smtp_email=smtp_email,
                smtp_password=smtp_password,
                role=assigned_role
            )

            db.session.add(new_user)

            db.session.commit()

            login_user(new_user)

            return redirect(
                url_for("compose")
            )

    return render_template_string(
        REGISTER_PAGE,
        style=BASE_STYLE,
        message=message
    )


@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    message = ""

    if request.method == "POST":

        username = request.form["username"].strip()

        password = request.form["password"]

        user = User.query.filter_by(
            username=username
        ).first()

        if (
            user
            and check_password_hash(
                user.password_hash,
                password
            )
        ):

            login_user(user)

            return redirect(
                url_for("compose")
            )

        else:

            message = "Invalid username or password."

    return render_template_string(
        LOGIN_PAGE,
        style=BASE_STYLE,
        message=message
    )


@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(
        url_for("login")
    )


@app.route(
    "/compose",
    methods=["GET", "POST"]
)
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

        temp_paths, filenames, attachment_results = scan_attachments(
            uploaded_files
        )

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

    return render_template_string(
        COMPOSE_PAGE,
        style=BASE_STYLE,
        topbar=topbar("Secure Corporate Mail Portal") + topbar_links(),
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


@app.route(
    "/confirm-medium",
    methods=["POST"]
)
@login_required
def confirm_medium():

    recipient = request.form.get("to")
    subject = request.form.get("subject")
    message = request.form.get("message")
    temp_paths_json = request.form.get("temp_paths_json")
    filenames_json = request.form.get("filenames_json")
    scan_results_json = request.form.get("scan_results_json")
    confidence = request.form.get("confidence", "confirmed")

    if not temp_paths_json:

        return redirect(
            url_for("compose")
        )

    temp_paths = json.loads(temp_paths_json)

    filenames = json.loads(filenames_json) if filenames_json else []

    scan_results = json.loads(scan_results_json) if scan_results_json else []

    existing_paths = [
        path for path in temp_paths
        if os.path.exists(path)
    ]

    if not existing_paths:

        return render_template_string(
            COMPOSE_PAGE,
            style=BASE_STYLE,
            topbar=topbar("Secure Corporate Mail Portal") + topbar_links(),
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

    return render_template_string(
        COMPOSE_PAGE,
        style=BASE_STYLE,
        topbar=topbar("Secure Corporate Mail Portal") + topbar_links(),
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


@app.route(
    "/delete-medium",
    methods=["POST"]
)
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

    return redirect(
        url_for("compose")
    )


@app.route("/incidents")
@login_required
@security_required
def incidents():

    all_incidents = EmailIncident.query.order_by(
        EmailIncident.timestamp.desc()
    ).all()

    return render_template_string(
        INCIDENTS_PAGE,
        style=BASE_STYLE,
        topbar=topbar("Email DLP Incident Dashboard") + topbar_links(),
        incidents=all_incidents
    )


@app.route("/users")
@login_required
@admin_required
def users():

    all_users = User.query.order_by(
        User.id.asc()
    ).all()

    return render_template_string(
        USERS_PAGE,
        style=BASE_STYLE,
        topbar=topbar("User Role Management") + topbar_links(),
        users=all_users
    )


@app.route(
    "/update-role",
    methods=["POST"]
)
@login_required
@admin_required
def update_role():

    user_id = request.form.get("user_id")

    new_role = request.form.get("role")

    allowed_roles = [
        "Employee",
        "Security Analyst",
        "Admin"
    ]

    if new_role not in allowed_roles:

        return redirect(
            url_for("users")
        )

    user = User.query.get(int(user_id))

    if user:

        user.role = new_role

        db.session.commit()

    return redirect(
        url_for("users")
    )


if __name__ == "__main__":

    with app.app_context():

        ensure_database_schema()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
