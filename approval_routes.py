from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required

from web.admin_routes import security_required
from database.db import SessionLocal, PendingApproval, FileEvent


approval_bp = Blueprint("approval", __name__)


def log_approval_event(filename, channel, status, reason, confidence=0):

    session = SessionLocal()

    event = FileEvent(
        filename=filename,
        action=f"{channel}_{status}",
        label="MEDIUM",
        score=0,
        ml_prediction="MEDIUM",
        ml_confidence=confidence,
        rule_score=0,
        reason=reason,
        timestamp=datetime.now(timezone.utc)
    )

    session.add(event)
    session.commit()
    session.close()


@approval_bp.route("/approvals")
@login_required
@security_required
def approvals():

    session = SessionLocal()

    pending = session.query(PendingApproval).filter(
        PendingApproval.status == "PENDING"
    ).order_by(
        PendingApproval.created_at.desc()
    ).all()

    recent = session.query(PendingApproval).order_by(
        PendingApproval.created_at.desc()
    ).limit(30).all()

    session.close()

    return render_template(
        "approvals.html",
        pending=pending,
        recent=recent
    )


@approval_bp.route("/approvals/<int:approval_id>/approve", methods=["POST"])
@login_required
@security_required
def approve_file(approval_id):

    session = SessionLocal()

    approval = session.query(PendingApproval).filter(
        PendingApproval.id == approval_id
    ).first()

    if approval:

        approval.status = "APPROVED"
        approval.decided_at = datetime.now(timezone.utc)

        log_approval_event(
            approval.filename,
            approval.channel,
            "MEDIUM_APPROVED",
            "Medium-risk file approved from dashboard after content review.",
            approval.confidence
        )

        session.commit()

    session.close()

    return redirect(url_for("approval.approvals"))


@approval_bp.route("/approvals/<int:approval_id>/delete", methods=["POST"])
@login_required
@security_required
def delete_file(approval_id):

    session = SessionLocal()

    approval = session.query(PendingApproval).filter(
        PendingApproval.id == approval_id
    ).first()

    if approval:

        approval.status = "DELETE_REQUESTED"
        approval.decided_at = datetime.now(timezone.utc)

        log_approval_event(
            approval.filename,
            approval.channel,
            "MEDIUM_DELETE_REQUESTED",
            "Medium-risk file deletion requested after dashboard content review. Monitor will delete it.",
            approval.confidence
        )

        session.commit()

    session.close()

    return redirect(url_for("approval.approvals"))
