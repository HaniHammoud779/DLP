import json
import os

from transformers import pipeline


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

POLICY_PATH = os.path.join(BASE_DIR, "policies", "default_policy.json")
ORGANIZATION_PATH = os.path.join(BASE_DIR, "policies", "organizations.json")


classifier = pipeline(
    "zero-shot-classification",
    model="facebook/bart-large-mnli"
)


def load_json(path):

    try:

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return {}


def load_default_policy():

    return load_json(POLICY_PATH)


def load_organizations():

    return load_json(ORGANIZATION_PATH)


def semantic_organization_match(content, organization):

    if not content.strip():
        return False, 0, ""

    organizations = load_organizations()

    org_data = organizations.get(organization)

    if not org_data:
        return False, 0, ""

    organization_description = org_data.get("description", "")

    labels = [
        organization_description,
        "This text is unrelated to the organization's sensitive business context."
    ]

    result = classifier(content, labels)

    best_label = result["labels"][0]

    confidence = float(result["scores"][0])

    if (
        best_label == organization_description
        and confidence >= 0.75
    ):

        return True, confidence, organization_description

    return False, confidence, organization_description


def decide_action(
    classification,
    channel="LOCAL_FOLDER",
    organization=None,
    content=""
):

    policies = load_default_policy()

    classification = classification.upper()
    channel = channel.upper()

    organization_match, semantic_confidence, organization_description = (
        semantic_organization_match(content, organization)
    )

    adjusted_classification = classification

    reason = "Decision based on default DLP policy."

    if organization_match and classification == "SAFE":

        adjusted_classification = "MEDIUM"

        reason = (
            f"AI semantic organization-context match detected "
            f"(confidence={round(semantic_confidence, 2)}). "
            f"Classification upgraded from SAFE to MEDIUM."
        )

    elif organization_match and classification == "MEDIUM":

        adjusted_classification = "SENSITIVE"

        reason = (
            f"AI semantic organization-context match detected "
            f"(confidence={round(semantic_confidence, 2)}). "
            f"Classification upgraded from MEDIUM to SENSITIVE."
        )

    elif organization_match and classification == "SENSITIVE":

        reason = (
            f"AI semantic organization-context match detected "
            f"(confidence={round(semantic_confidence, 2)}). "
            f"Classification remains SENSITIVE."
        )

    channel_policy = policies.get(channel, {})

    action = channel_policy.get(
        adjusted_classification,
        "ALLOW"
    )

    return {
        "original_classification": classification,
        "final_classification": adjusted_classification,
        "channel": channel,
        "organization": organization,
        "action": action,
        "organization_match": organization_match,
        "semantic_confidence": round(semantic_confidence, 2),
        "reason": reason
    }


if __name__ == "__main__":

    test_content = (
        "The burger preparation process contains "
        "proprietary cooking techniques."
    )

    result = decide_action(
        classification="SAFE",
        channel="FTP",
        organization="Restaurant",
        content=test_content
    )

    print(result)
