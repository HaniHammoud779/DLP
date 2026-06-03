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


def mask_word(value):

    return "*" * len(value)


def looks_like_sensitive_value(value):

    cleaned = value.strip().strip(".,!?;:'\"")

    if len(cleaned) < 6:
        return False

    has_letter = re.search(r"[A-Za-z]", cleaned) is not None

    has_digit = re.search(r"\d", cleaned) is not None

    has_special = re.search(r"[@#$%^&*!_+=\-./]", cleaned) is not None

    if has_letter and has_digit:
        return True

    if has_special and len(cleaned) >= 8:
        return True

    return False


def mask_sensitive_content(text):

    sensitive_snippets = []

    assignment_pattern = re.compile(
        r"(?P<left>\b[A-Za-z_][A-Za-z0-9_\-]{2,40}\b)"
        r"(?P<separator>\s*(?:is|=|:)\s*)"
        r"(?P<quote>[\"']?)"
        r"(?P<value>[A-Za-z0-9@#$%^&*!_+=\-./]{4,})"
        r"(?P=quote)",
        re.IGNORECASE
    )

    standalone_value_pattern = re.compile(
        r"\b(?=[A-Za-z0-9@#$%^&*!_+=\-./]*[A-Za-z])"
        r"(?=[A-Za-z0-9@#$%^&*!_+=\-./]*\d)"
        r"[A-Za-z0-9@#$%^&*!_+=\-./]{6,}\b"
    )

    for line in text.splitlines():

        line = line.strip()

        if not line:
            continue

        assignment_matches = list(
            assignment_pattern.finditer(line)
        )

        for match in assignment_matches:

            left = match.group("left")
            separator = match.group("separator")
            quote = match.group("quote")
            value = match.group("value")

            if looks_like_sensitive_value(value):

                snippet = (
                    mask_word(left)
                    + separator
                    + quote
                    + mask_word(value)
                    + quote
                )

                sensitive_snippets.append(snippet)

        if assignment_matches:
            continue

        value_matches = standalone_value_pattern.findall(line)

        for value in value_matches:

            if looks_like_sensitive_value(value):

                sensitive_snippets.append(
                    mask_word(value)
                )

    if not sensitive_snippets:

        return (
            "Sensitive content detected semantically by AI. "
            "No direct secret-like value was extracted for display."
        )

    unique_snippets = []

    for snippet in sensitive_snippets:

        if snippet not in unique_snippets:

            unique_snippets.append(snippet)

    return "\n".join(unique_snippets)


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
