import re
from random import uniform

# ---------------- Keywords / secret patterns ----------------
SECRET_KEYWORDS = [
    "password", "pwd", "pass",
    "social security number", "ssn",
    "bank account number", "account",
    "cvv", "cvc"
]

# Words that indicate non-secret / descriptive words (expanded)
NON_SECRET_WORDS = [
    "strong", "secure", "good", "example", "your",
    "demo", "test", "sample", "weak", "complex",
    "default", "placeholder", "temporary", "my", "admin", "user"
]

# ---------------- Helper functions ----------------
def build_pattern(keyword):
    """
    Capture the token right after a keyword.
    Stops at space or punctuation.
    """
    return rf"\b{keyword}\b\s*(?:is\s+|[:=]\s*)?(\S+)"

def is_non_secret(value):
    """
    Returns True if value is descriptive/advice word (case-insensitive)
    """
    return value.lower().strip(".,!?:;") in NON_SECRET_WORDS

def is_real_secret(keyword, value):
    """
    Returns True only if value is a real secret
    """
    value_clean = value.lower().strip(".,!?:;")  # normalize

    if is_non_secret(value_clean):
        return False

    if keyword.lower() in ["password", "pwd", "pass"]:
        # Anything >= 4 chars that's not descriptive → secret
        return len(value_clean) >= 4

    if keyword.lower() in ["ssn", "social security number"]:
        return bool(re.match(r"^\d{2,3}-\d{2}-\d{2,4}$", value_clean))

    if keyword.lower() in ["bank account number", "account"]:
        return value_clean.isdigit() and len(value_clean) >= 6

    if keyword.lower() in ["cvv", "cvc"]:
        return value_clean.isdigit() and len(value_clean) in [3, 4]

    return True

# ---------------- Main prediction ----------------
def predict_file(file_path):
    """
    Analyze a file for sensitive data.
    Returns: label, score, triggered_words, masked_content
    """
    label = "SAFE"
    score = round(uniform(0, 15), 2)  # initial SAFE score
    triggered_words = []
    masked_content = ""

    # Read file content
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        content = ""

    masked_content = content

    # ---------------- Detect secrets ----------------
    for keyword in SECRET_KEYWORDS:
        pattern = build_pattern(keyword)
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            match_clean = match.lower().strip(".,!?:;")

            if is_non_secret(match_clean):
                # descriptive → MEDIUM random 30–50
                score = max(score, round(30 + uniform(0, 20), 2))
            elif is_real_secret(keyword, match_clean):
                # real secret → SENSITIVE random 80–100
                masked_content = re.sub(re.escape(match), "*" * len(match), masked_content)
                score = max(score, round(80 + uniform(0, 20), 2))

            if keyword not in triggered_words:
                triggered_words.append(keyword)

    # ---------------- Determine label ----------------
    if score >= 80:
        label = "SENSITIVE"
    elif score >= 50:
        label = "MEDIUM"
    else:
        label = "SAFE"

    triggered_words = list(dict.fromkeys(triggered_words))

    return label, score, triggered_words, masked_content
