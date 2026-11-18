"""Pure mapping from a classifier result to an application status change."""

from enum import StrEnum

from app.providers.classifier.types import ClassificationResult, Label


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    ONLINE_ASSESSMENT = "online_assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"


_LABEL_TO_STATUS: dict[Label, ApplicationStatus] = {
    Label.CONFIRMATION: ApplicationStatus.APPLIED,
    Label.ONLINE_ASSESSMENT: ApplicationStatus.ONLINE_ASSESSMENT,
    Label.INTERVIEW: ApplicationStatus.INTERVIEW,
    Label.OFFER: ApplicationStatus.OFFER,
    Label.REJECTION: ApplicationStatus.REJECTED,
}


def apply_result(
    current_status: ApplicationStatus | None, result: ClassificationResult
) -> ApplicationStatus | None:
    """New status, or None for no change. Forward-only rules and locking come later (US-50/51)."""
    if result.needs_review or result.label is None:
        return None
    return _LABEL_TO_STATUS.get(result.label)
