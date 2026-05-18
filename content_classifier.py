from transformers import pipeline
import re

classifier = pipeline(
    "zero-shot-classification",
    model="facebook/bart-large-mnli"
)

def contains_value(text):

    matches = re.findall(r"\b\S+\b", text)

    for value in matches:

        cleaned = value.strip().strip(".,!?;:'\"")

        if cleaned.isalpha() and len(cleaned) < 8:
            continue

        if (
            re.search(r"[A-Za-z]", cleaned)
            and re.search(r"\d", cleaned)
            and len(cleaned) >= 6
        ):
            return True

        if (
            re.search(r"[@#$%^&*!_+=]", cleaned)
            and len(cleaned) >= 6
        ):
            return True

    return False


def mask_sensitive_content(text):

    sensitive_lines = []

    for line in text.splitlines():

        if ":" in line or "=" in line or re.search(r"[A-Za-z].*\d", line):

            masked_line = re.sub(
                r'([A-Za-z0-9@#$%^&*!_+=-]{3,})',
                lambda m: "*" * len(m.group(1)),
                line
            )

            sensitive_lines.append(masked_line)

    return "\n".join(sensitive_lines)


def predict_file(file_path):

    try:
        with open(file_path, "r", errors="ignore") as f:
            content = f.read()

    except:
        content = ""

    if not content.strip():

        return "SAFE", 0, [], "", {
            "ml_prediction": "SAFE",
            "ml_confidence": 0,
            "ml_score": 0,
            "rule_score": 0,
            "reason": ""
        }

    labels = [
        "This text is about confidential or sensitive information",
        "This text is normal and harmless"
    ]

    result = classifier(content, labels)

    best_label = result["labels"][0]
    confidence = float(result["scores"][0])
    score = int(confidence * 100)

    if contains_value(content):

        label = "SENSITIVE"

    elif (
        "confidential" in best_label.lower()
        and confidence >= 0.95
        and len(content.split()) > 5
    ):
        label = "MEDIUM"

    else:
        label = "SAFE"

    reason_text = ""

    if label == "SENSITIVE":

        masked_content = mask_sensitive_content(content)

        reason_text = f"Sensitive data detected ->\n{masked_content}"

    explanation = {
        "ml_prediction": label,
        "ml_confidence": round(confidence, 2),
        "ml_score": score,
        "rule_score": 0,
        "reason": reason_text
    }

    return label, score, [], content, explanation
