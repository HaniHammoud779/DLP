import re
from random import uniform

# ---------------- Keywords ----------------
SECRET_KEYWORDS = [
    "password", "pwd", "pass",
    "social security number", "ssn",
    "bank account number", "account",
    "cvv", "cvc"
]

NON_SECRET_WORDS = [
    "strong", "secure", "good", "example", "your",
    "demo", "test", "sample", "weak", "complex",
    "default", "placeholder", "temporary"
]

CONTEXT_WORDS = [
    "my", "customer", "user", "client"
]

SAFE_CONTEXT_PHRASES = [
    "for testing",
    "for demo",
    "example",
    "placeholder",
    "dummy",
    "for illustration",
    "sample data",
    "not real",
    "fake data",
    "do not use",
    "only for"
]

# ---------------- PII REGEX ----------------
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
PHONE_REGEX = r"\+?\d{8,14}"
CREDIT_CARD_REGEX = r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"


def is_non_secret(value):
    return value.lower().strip(".,!?:;") in NON_SECRET_WORDS


def is_safe_context(text_lower):
    return any(p in text_lower for p in SAFE_CONTEXT_PHRASES)


# ---------------- MAIN FUNCTION ----------------
def predict_file(file_path):
    risk = 0
    masked_content = ""
    is_sensitive = False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except:
        content = ""

    masked_content = content
    content_lower = content.lower()

    safe_context = is_safe_context(content_lower)

    triggers = {"keywords": []}

    lines = [l.strip() for l in content.split("\n") if l.strip()]

    global_risk = 0

    for line in lines:
        line_lower = line.lower()
        line_risk = 0
        line_sensitive = False

        # ---------------- CONTEXT ----------------
        for word in CONTEXT_WORDS:
            if word in line_lower:
                line_risk += 10

        # ---------------- PII DETECTION (FIXED CORE ISSUE) ----------------
        emails = re.findall(EMAIL_REGEX, line)
        phones = re.findall(PHONE_REGEX, line)
        cards = re.findall(CREDIT_CARD_REGEX, line)

        # EMAIL = HARD TRIGGER (FIX)
        if emails:
            line_sensitive = True
            line_risk += len(emails) * 40

            for email in emails:
                masked_content = masked_content.replace(email, "*" * len(email))

            # 🔥 FORCE HIGH RISK (CRITICAL FIX)
            global_risk = max(global_risk, 90)

        if phones:
            line_risk += len(phones) * 30

            for phone in phones:
                masked_content = masked_content.replace(phone, "*" * len(phone))

        if cards:
            line_sensitive = True
            line_risk += len(cards) * 70

            for card in cards:
                masked_content = masked_content.replace(card, "*" * len(card))

            global_risk = max(global_risk, 90)

        # ---------------- KEYWORDS ----------------
        for keyword in SECRET_KEYWORDS:
            pattern = rf"\b{keyword}\b\s*(?:is\s+|[:=]\s*)?(\S+)"
            matches = re.findall(pattern, line, re.IGNORECASE)

            for match in matches:
                value = match.lower().strip(".,!?:;")

                # ---------------- ACCOUNT ----------------
                if keyword.lower() == "account":
                    if re.search(r"@", value) or re.match(r"^\d{6,}$", value):
                        line_sensitive = True
                        line_risk += 60
                        masked_content = masked_content.replace(match, "*" * len(match))

                # ---------------- PASSWORD ----------------
                elif keyword.lower() in ["password", "pwd", "pass"]:
                    has_digit = bool(re.search(r"\d", value))
                    has_symbol = bool(re.search(r"[^a-zA-Z0-9]", value))
                    is_long = len(value) >= 6

                    if has_digit and (has_symbol or is_long):
                        line_sensitive = True
                        line_risk += 70
                        masked_content = masked_content.replace(match, "*" * len(match))
                    else:
                        line_risk += 10

                # ---------------- NON-SECRET ----------------
                elif is_non_secret(value):
                    line_risk += 20 if not safe_context else 5

                # ---------------- OTHER ----------------
                else:
                    line_sensitive = True
                    line_risk += 60
                    masked_content = masked_content.replace(match, "*" * len(match))

                if keyword not in triggers["keywords"]:
                    triggers["keywords"].append(keyword)

        # ---------------- RISK AGGREGATION ----------------
        global_risk = max(global_risk, line_risk)

        if line_sensitive:
            is_sensitive = True

    # ---------------- SAFE CONTEXT CONTROL ----------------
    if safe_context and not (
        re.search(EMAIL_REGEX, content) or
        re.search(PHONE_REGEX, content) or
        re.search(CREDIT_CARD_REGEX, content)
    ):
        global_risk = min(global_risk, 35)

    # ---------------- FINAL SCORE ----------------
    final_score = round(global_risk + uniform(0, 5), 2)
    final_score = min(final_score, 100)

    # ---------------- LABEL ----------------
    if is_sensitive and final_score >= 80:
        label = "SENSITIVE"
    elif final_score >= 40:
        label = "MEDIUM"
    else:
        label = "SAFE"

    return label, final_score, triggers["keywords"], masked_content
