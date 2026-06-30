from transformers import pipeline
import re
import os
import json
import csv
from html.parser import HTMLParser


try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


try:
    from docx import Document
except Exception:
    Document = None


try:
    from openpyxl import load_workbook
except Exception:
    load_workbook = None


try:
    from pptx import Presentation
except Exception:
    Presentation = None


classifier = pipeline(
    "zero-shot-classification",
    model="facebook/bart-large-mnli"
)


AI_SECRET_SENSITIVE_THRESHOLD = 0.55
AI_SECRET_MEDIUM_THRESHOLD = 0.45
AI_SECRET_MIN_MARGIN_OVER_SAFE = 0.03

AI_SECRET_REFINEMENT_EXPOSED_STRONG_THRESHOLD = 0.70
AI_SECRET_REFINEMENT_SENSITIVE_THRESHOLD = 0.55
AI_SECRET_REFINEMENT_SAFE_THRESHOLD = 0.55
AI_SECRET_REFINEMENT_MIN_MARGIN = 0.02

AI_BUSINESS_SENSITIVE_THRESHOLD = 0.90
AI_BUSINESS_MEDIUM_THRESHOLD = 0.80
AI_MIN_MARGIN_OVER_SAFE = 0.12

AI_GENERIC_SENSITIVE_THRESHOLD = 0.98
AI_GENERIC_MEDIUM_THRESHOLD = 0.95

AI_RESTAURANT_REFINEMENT_SENSITIVE_THRESHOLD = 0.88
AI_RESTAURANT_REFINEMENT_MIN_MARGIN = 0.10
AI_RESTAURANT_REFINEMENT_SAFE_THRESHOLD = 0.70

MAX_EXTRACTED_CHARS = 20000


GENERIC_LABELS = [
    "This text is about confidential or sensitive information",
    "This text is normal and harmless"
]


GENERIC_SENSITIVE_LABEL = (
    "This text is about confidential or sensitive information"
)


GENERIC_SAFE_LABEL = (
    "This text is normal and harmless"
)


SECRET_PAYMENT_LABEL = (
    "This text is about confidential payment card or financial payment data, "
    "such as credit cards, debit cards, CVV, CVC, expiry dates, cardholder "
    "payment details, customer billing card information, bank card data, or "
    "customer payment information."
)


SECRET_CREDENTIAL_LABEL = (
    "This text is about login credentials, passwords, usernames with passwords, "
    "PINs, OTP codes, recovery codes, account access details, database "
    "credentials, or private authentication information."
)


SECRET_TOKEN_LABEL = (
    "This text is about API tokens, bearer tokens, access tokens, refresh "
    "tokens, secret keys, private keys, authorization headers, session cookies, "
    "cloud service keys, or technical authentication secrets."
)


SECRET_FINANCIAL_IDENTITY_LABEL = (
    "This text is about sensitive financial, banking, account, payroll, tax, "
    "customer account, or identity-related confidential data."
)


SECRET_SAFE_LABEL = (
    "This text is harmless. It only discusses passwords, tokens, authentication, "
    "payments, credit cards, banking, security policies, examples, placeholders, "
    "templates, order numbers, tracking numbers, or public operational text in a "
    "general way, without exposing actual usable secret values, payment details, "
    "financial records, credentials, or private account data."
)


SECRET_SEMANTIC_LABELS = [
    SECRET_PAYMENT_LABEL,
    SECRET_CREDENTIAL_LABEL,
    SECRET_TOKEN_LABEL,
    SECRET_FINANCIAL_IDENTITY_LABEL,
    SECRET_SAFE_LABEL
]


SECRET_REFINEMENT_EXPOSED_LABEL = (
    "This text actually exposes usable sensitive data. It contains real-looking "
    "payment card details, card number with CVV or expiry, usable password, "
    "usable credential, usable API token, bearer token, secret key, private key, "
    "bank account detail, financial account data, or private customer financial "
    "record. The information could be copied and misused."
)


SECRET_REFINEMENT_POLICY_LABEL = (
    "This text only gives a policy, warning, instruction, prevention rule, "
    "security recommendation, or general discussion about passwords, tokens, "
    "credit cards, payment gateways, banking, or sensitive data. It does not "
    "reveal any actual usable secret, credential, token, card number, CVV, "
    "expiry date, or private customer data."
)


SECRET_REFINEMENT_PLACEHOLDER_LABEL = (
    "This text only contains placeholders, examples, templates, dummy values, "
    "or instructions to replace a password, token, API key, or card number. "
    "It does not reveal an actual usable secret or real customer payment data."
)


SECRET_REFINEMENT_ORDER_LABEL = (
    "This text contains normal public order numbers, tracking numbers, reference "
    "numbers, invoice numbers, or customer service identifiers. It does not "
    "contain payment card details, CVV, expiry date, password, API token, or "
    "usable secret data."
)


SECRET_REFINEMENT_PUBLIC_LABEL = (
    "This text is normal public or harmless operational information. It does "
    "not expose usable credentials, tokens, payment card data, financial data, "
    "or private account information."
)


SECRET_REFINEMENT_LABELS = [
    SECRET_REFINEMENT_EXPOSED_LABEL,
    SECRET_REFINEMENT_POLICY_LABEL,
    SECRET_REFINEMENT_PLACEHOLDER_LABEL,
    SECRET_REFINEMENT_ORDER_LABEL,
    SECRET_REFINEMENT_PUBLIC_LABEL
]


HEALTHCARE_LABEL = (
    "This text contains private healthcare information such as patient "
    "records, medical diagnoses, prescriptions, lab results, treatment "
    "details, or personal medical history."
)


RESTAURANT_LABEL = (
    "This text exposes restaurant business-sensitive recipe or food "
    "production information, such as actual ingredient quantities, sauce "
    "formulas, seasoning blends, preparation steps, storage timing, or "
    "repeatable methods used to prepare a restaurant menu item, even if "
    "the text does not explicitly say confidential or secret."
)


SOFTWARE_LABEL = (
    "This text contains confidential software company intellectual "
    "property such as private source code, proprietary algorithms, "
    "internal system designs, architecture details, or unreleased "
    "technical plans."
)


BUSINESS_SAFE_LABEL = (
    "This text contains normal public or harmless information that does "
    "not expose confidential, private, personal, medical, technical, or "
    "business-sensitive data."
)


BUSINESS_SEMANTIC_LABELS = [
    HEALTHCARE_LABEL,
    RESTAURANT_LABEL,
    SOFTWARE_LABEL,
    BUSINESS_SAFE_LABEL
]


RESTAURANT_REFINEMENT_SENSITIVE_LABEL = (
    "This text clearly reveals enough concrete restaurant food-production "
    "information to reproduce a menu item or internal recipe. It includes "
    "substantial formula details such as actual ingredient quantities, "
    "specific preparation steps, mixing instructions, storage timing, or a "
    "complete repeatable method. A simple mention, description, opinion, "
    "or review of a recipe, sauce, burger, or taste is not included in this "
    "category."
)


RESTAURANT_REFINEMENT_PUBLIC_LABEL = (
    "This text only mentions, describes, praises, reviews, or discusses a "
    "restaurant recipe, sauce, burger, taste, or menu item. It does not "
    "reveal enough concrete formula details to reproduce the food item. "
    "This includes sentences like saying a restaurant recipe or sauce is "
    "delicious."
)


RESTAURANT_REFINEMENT_OPERATIONAL_LABEL = (
    "This text is normal restaurant operational information, such as "
    "opening hours, menu availability, cleaning schedules, customer service, "
    "staff notes, daily activity, or general business updates."
)


RESTAURANT_REFINEMENT_LABELS = [
    RESTAURANT_REFINEMENT_SENSITIVE_LABEL,
    RESTAURANT_REFINEMENT_PUBLIC_LABEL,
    RESTAURANT_REFINEMENT_OPERATIONAL_LABEL
]


TEXT_EXTENSIONS = {
    ".txt", ".log", ".csv", ".json", ".xml", ".html", ".htm", ".md",
    ".py", ".java", ".cs", ".js", ".php", ".sql", ".env", ".conf",
    ".ini", ".yml", ".yaml", ".sh", ".bat", ".ps1", ".config"
}


PLACEHOLDER_WORDS = [
    "your_password_here",
    "your_api_key_here",
    "replace_this_with_real_token",
    "replace_with_real_token",
    "replace_with_token",
    "replace_me",
    "changeme",
    "change_me",
    "example",
    "sample",
    "dummy",
    "placeholder",
    "template",
    "insert_here",
    "enter_password",
    "enter_api_key",
    "api_key_here",
    "password_here",
    "token_here",
    "secret_here",
    "xxxxx",
    "xxxx",
    "****",
    "<password>",
    "<api_key>",
    "<token>",
    "<secret>",
    "null",
    "none"
]


SAFE_IDENTIFIER_WORDS = [
    "order",
    "tracking",
    "reference",
    "invoice",
    "ticket",
    "receipt",
    "shipment",
    "delivery",
    "booking"
]


class SimpleHTMLTextExtractor(HTMLParser):

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data and data.strip():
            self.parts.append(data.strip())

    def get_text(self):
        return "\n".join(self.parts)


def limit_text(text):

    if not text:
        return ""

    if len(text) > MAX_EXTRACTED_CHARS:
        return text[:MAX_EXTRACTED_CHARS]

    return text


def read_text_file(file_path):

    try:
        with open(file_path, "r", errors="ignore", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(file_path, "r", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""


def extract_html_text(file_path):

    raw_text = read_text_file(file_path)

    if not raw_text:
        return ""

    parser = SimpleHTMLTextExtractor()

    try:
        parser.feed(raw_text)
        return parser.get_text()
    except Exception:
        return raw_text


def extract_pdf_text(file_path):

    if PdfReader is None:
        return ""

    extracted_parts = []

    try:
        reader = PdfReader(file_path)

        for page in reader.pages:
            try:
                page_text = page.extract_text()
            except Exception:
                page_text = ""

            if page_text:
                extracted_parts.append(page_text)

            if len("\n".join(extracted_parts)) >= MAX_EXTRACTED_CHARS:
                break

    except Exception:
        return ""

    return "\n".join(extracted_parts)


def extract_docx_text(file_path):

    if Document is None:
        return ""

    extracted_parts = []

    try:
        document = Document(file_path)

        for paragraph in document.paragraphs:
            text = paragraph.text.strip()

            if text:
                extracted_parts.append(text)

        for table in document.tables:
            for row in table.rows:
                row_values = []

                for cell in row.cells:
                    cell_text = cell.text.strip()

                    if cell_text:
                        row_values.append(cell_text)

                if row_values:
                    extracted_parts.append(" | ".join(row_values))

    except Exception:
        return ""

    return "\n".join(extracted_parts)


def extract_xlsx_text(file_path):

    if load_workbook is None:
        return ""

    extracted_parts = []

    try:
        workbook = load_workbook(
            filename=file_path,
            read_only=True,
            data_only=True
        )

        for sheet in workbook.worksheets:
            extracted_parts.append(f"Sheet: {sheet.title}")

            for row in sheet.iter_rows(values_only=True):
                values = []

                for cell in row:
                    if cell is not None:
                        values.append(str(cell))

                if values:
                    extracted_parts.append(" | ".join(values))

                if len("\n".join(extracted_parts)) >= MAX_EXTRACTED_CHARS:
                    break

            if len("\n".join(extracted_parts)) >= MAX_EXTRACTED_CHARS:
                break

        workbook.close()

    except Exception:
        return ""

    return "\n".join(extracted_parts)


def extract_pptx_text(file_path):

    if Presentation is None:
        return ""

    extracted_parts = []

    try:
        presentation = Presentation(file_path)

        for slide_number, slide in enumerate(presentation.slides, start=1):
            extracted_parts.append(f"Slide {slide_number}")

            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text = shape.text.strip()

                    if text:
                        extracted_parts.append(text)

            if len("\n".join(extracted_parts)) >= MAX_EXTRACTED_CHARS:
                break

    except Exception:
        return ""

    return "\n".join(extracted_parts)


def extract_csv_text(file_path):

    extracted_parts = []

    try:
        with open(file_path, "r", errors="ignore", encoding="utf-8") as f:
            reader = csv.reader(f)

            for row in reader:
                if row:
                    extracted_parts.append(" | ".join(row))

                if len("\n".join(extracted_parts)) >= MAX_EXTRACTED_CHARS:
                    break

    except Exception:
        return read_text_file(file_path)

    return "\n".join(extracted_parts)


def extract_json_text(file_path):

    raw_text = read_text_file(file_path)

    if not raw_text:
        return ""

    try:
        data = json.loads(raw_text)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return raw_text


def read_file_content(file_path):

    extension = os.path.splitext(file_path)[1].lower()

    content = ""

    if extension in {".html", ".htm"}:
        content = extract_html_text(file_path)

    elif extension == ".pdf":
        content = extract_pdf_text(file_path)

    elif extension == ".docx":
        content = extract_docx_text(file_path)

    elif extension == ".xlsx":
        content = extract_xlsx_text(file_path)

    elif extension == ".pptx":
        content = extract_pptx_text(file_path)

    elif extension == ".csv":
        content = extract_csv_text(file_path)

    elif extension == ".json":
        content = extract_json_text(file_path)

    elif extension in TEXT_EXTENSIONS:
        content = read_text_file(file_path)

    else:
        content = read_text_file(file_path)

    return limit_text(content)


def has_reproducible_formula_detail(text):
    cleaned_text = text.strip()

    if not cleaned_text:
        return False

    lines = [
        line.strip()
        for line in cleaned_text.splitlines()
        if line.strip()
    ]

    number_pattern = re.compile(r"\b\d+(?:\.\d+)?\b")

    measurement_pattern = re.compile(
        r"\b\d+(?:\.\d+)?\s*"
        r"(ml|l|liter|liters|litre|litres|g|gram|grams|kg|mg|"
        r"tsp|tbsp|cup|cups|oz|lb|pound|pounds|minutes|minute|"
        r"hours|hour)\b",
        re.IGNORECASE
    )

    number_count = len(number_pattern.findall(cleaned_text))
    measurement_count = len(measurement_pattern.findall(cleaned_text))

    bullet_or_list_lines = 0

    for line in lines:
        if re.match(r"^\s*(-|\*|\d+\.|\d+\)|•)", line):
            bullet_or_list_lines += 1

    multiline_detail = len(lines) >= 4
    has_colon_structure = ":" in cleaned_text
    enough_numbers = number_count >= 3
    enough_measurements = measurement_count >= 2
    enough_list_structure = bullet_or_list_lines >= 2

    detail_score = 0

    if multiline_detail:
        detail_score += 1

    if has_colon_structure:
        detail_score += 1

    if enough_numbers:
        detail_score += 1

    if enough_measurements:
        detail_score += 2

    if enough_list_structure:
        detail_score += 1

    return detail_score >= 3


def is_placeholder_value(value):

    cleaned = value.strip().strip(".,!?;:'\"").lower()

    if not cleaned:
        return True

    for placeholder in PLACEHOLDER_WORDS:
        if placeholder.lower() in cleaned:
            return True

    if re.fullmatch(r"x{3,}", cleaned):
        return True

    if re.fullmatch(r"\*{3,}", cleaned):
        return True

    return False


def left_side_is_safe_identifier(left):

    cleaned = left.strip().lower()

    for word in SAFE_IDENTIFIER_WORDS:
        if word in cleaned:
            return True

    return False


def assignment_matches(text):

    pattern = re.compile(
        r"(?P<left>\b[A-Za-z_][A-Za-z0-9_\-]{2,40}\b)"
        r"(?P<separator>\s*(?:is|=|:)\s*)"
        r"(?P<quote>[\"']?)"
        r"(?P<value>[A-Za-z0-9@#$%^&*!_+=\-./]{3,})"
        r"(?P=quote)",
        re.IGNORECASE
    )

    return list(pattern.finditer(text))


def looks_like_sensitive_value(value):

    cleaned = value.strip().strip(".,!?;:'\"")

    if is_placeholder_value(cleaned):
        return False

    if len(cleaned) < 4:
        return False

    has_letter = re.search(r"[A-Za-z]", cleaned) is not None
    has_digit = re.search(r"\d", cleaned) is not None
    has_special = re.search(r"[@#$%^&*!_+=\-./]", cleaned) is not None
    is_numeric = cleaned.isdigit()

    if is_numeric:
        return False

    if has_letter and has_digit and len(cleaned) >= 6:
        return True

    if has_special and len(cleaned) >= 6 and has_letter:
        return True

    return False


def contains_real_password_or_secret_assignment(text):

    matches = assignment_matches(text)

    for match in matches:

        left = match.group("left").lower()
        value = match.group("value").strip().strip(".,!?;:'\"")

        if is_placeholder_value(value):
            continue

        if left_side_is_safe_identifier(left):
            continue

        secret_left_names = [
            "password",
            "passwd",
            "pwd",
            "api_key",
            "apikey",
            "api-token",
            "api_token",
            "token",
            "access_token",
            "refresh_token",
            "secret",
            "secret_key",
            "private_key",
            "auth_token",
            "authorization",
            "bearer"
        ]

        for name in secret_left_names:
            if name in left:
                if len(value) >= 4:
                    return True

    return False


def contains_value(text):

    if contains_real_password_or_secret_assignment(text):
        return True

    for match in assignment_matches(text):

        left = match.group("left").strip()
        value = match.group("value").strip().strip(".,!?;:'\"")

        if is_placeholder_value(value):
            continue

        if left_side_is_safe_identifier(left):
            continue

        if looks_like_sensitive_value(value):
            return True

    matches = re.findall(r"\b\S+\b", text)

    for value in matches:

        cleaned = value.strip().strip(".,!?;:'\"")

        if is_placeholder_value(cleaned):
            continue

        if cleaned.isalpha():
            continue

        if cleaned.isdigit():
            continue

        if (
            re.search(r"[A-Za-z]", cleaned)
            and re.search(r"\d", cleaned)
            and len(cleaned) >= 12
        ):
            return True

        if (
            re.search(r"[@#$%^&*!_+=]", cleaned)
            and re.search(r"[A-Za-z]", cleaned)
            and len(cleaned) >= 12
        ):
            return True

    return False


def is_placeholder_template_document(text):

    matches = assignment_matches(text)

    if not matches:
        return False

    placeholder_count = 0
    real_secret_count = 0

    for match in matches:

        left = match.group("left").lower()
        value = match.group("value").strip().strip(".,!?;:'\"")

        if (
            "password" in left
            or "api" in left
            or "key" in left
            or "token" in left
            or "secret" in left
        ):
            if is_placeholder_value(value):
                placeholder_count += 1
            else:
                real_secret_count += 1

    return placeholder_count > 0 and real_secret_count == 0


def is_clear_order_or_tracking_document(text):

    lower_text = text.lower()

    if not any(word in lower_text for word in SAFE_IDENTIFIER_WORDS):
        return False

    if any(
        word in lower_text
        for word in [
            "cvv",
            "cvc",
            "expiry",
            "expiration",
            "valid thru",
            "credit card",
            "debit card",
            "cardholder",
            "payment card",
            "password",
            "api_token",
            "api key",
            "bearer"
        ]
    ):
        if (
            "does not include cvv" in lower_text
            or "does not contain cvv" in lower_text
            or "no cvv" in lower_text
            or "does not include" in lower_text
            or "does not contain" in lower_text
            or "no customer card" in lower_text
        ):
            return True

        return False

    return True


def mask_word(value):

    return "*" * len(value)


def mask_sensitive_content(text):

    sensitive_snippets = []

    standalone_value_pattern = re.compile(
        r"\b(?=[A-Za-z0-9@#$%^&*!_+=\-./]*[A-Za-z])"
        r"(?=[A-Za-z0-9@#$%^&*!_+=\-./]*\d)"
        r"[A-Za-z0-9@#$%^&*!_+=\-./]{6,}\b"
    )

    for line in text.splitlines():

        line = line.strip()

        if not line:
            continue

        matches = assignment_matches(line)

        for match in matches:

            left = match.group("left")
            separator = match.group("separator")
            quote = match.group("quote")
            value = match.group("value")

            if is_placeholder_value(value):
                continue

            if left_side_is_safe_identifier(left):
                continue

            if looks_like_sensitive_value(value) or contains_real_password_or_secret_assignment(line):

                snippet = (
                    mask_word(left)
                    + separator
                    + quote
                    + mask_word(value)
                    + quote
                )

                sensitive_snippets.append(snippet)

        if matches:
            continue

        value_matches = standalone_value_pattern.findall(line)

        for value in value_matches:

            if is_placeholder_value(value):
                continue

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


def run_secret_ai_analysis(content):

    try:

        result = classifier(
            content,
            SECRET_SEMANTIC_LABELS,
            hypothesis_template="{}",
            truncation=True
        )

    except Exception as e:

        return {
            "best_label": SECRET_SAFE_LABEL,
            "best_score": 0,
            "safe_score": 1,
            "margin_over_safe": 0,
            "error": str(e)
        }

    labels = result["labels"]
    scores = result["scores"]

    best_label = labels[0]
    best_score = float(scores[0])

    safe_score = 0

    for label, score in zip(labels, scores):

        if label == SECRET_SAFE_LABEL:
            safe_score = float(score)
            break

    margin_over_safe = best_score - safe_score

    return {
        "best_label": best_label,
        "best_score": best_score,
        "safe_score": safe_score,
        "margin_over_safe": margin_over_safe,
        "error": ""
    }


def run_secret_refinement_ai_analysis(content):

    try:

        result = classifier(
            content,
            SECRET_REFINEMENT_LABELS,
            hypothesis_template="{}",
            truncation=True
        )

    except Exception as e:

        return {
            "best_label": SECRET_REFINEMENT_PUBLIC_LABEL,
            "best_score": 0,
            "second_score": 0,
            "margin": 0,
            "error": str(e)
        }

    labels = result["labels"]
    scores = result["scores"]

    best_label = labels[0]
    best_score = float(scores[0])

    second_score = 0

    if len(scores) > 1:
        second_score = float(scores[1])

    margin = best_score - second_score

    return {
        "best_label": best_label,
        "best_score": best_score,
        "second_score": second_score,
        "margin": margin,
        "error": ""
    }


def get_secret_reason(best_secret_label):

    if best_secret_label == SECRET_PAYMENT_LABEL:
        return (
            "AI semantic analysis detected payment-card or financial-payment "
            "context."
        )

    if best_secret_label == SECRET_CREDENTIAL_LABEL:
        return (
            "AI semantic analysis detected credential or account-access context."
        )

    if best_secret_label == SECRET_TOKEN_LABEL:
        return (
            "AI semantic analysis detected technical-secret or token context."
        )

    if best_secret_label == SECRET_FINANCIAL_IDENTITY_LABEL:
        return (
            "AI semantic analysis detected financial, banking, account, payroll, "
            "tax, customer-account, or identity-related context."
        )

    return ""


def run_generic_ai_analysis(content):

    try:

        result = classifier(
            content,
            GENERIC_LABELS,
            truncation=True
        )

    except Exception as e:

        return {
            "best_label": GENERIC_SAFE_LABEL,
            "best_score": 0,
            "error": str(e)
        }

    return {
        "best_label": result["labels"][0],
        "best_score": float(result["scores"][0]),
        "error": ""
    }


def run_business_ai_analysis(content):

    try:

        result = classifier(
            content,
            BUSINESS_SEMANTIC_LABELS,
            hypothesis_template="{}",
            truncation=True
        )

    except Exception as e:

        return {
            "best_label": BUSINESS_SAFE_LABEL,
            "best_score": 0,
            "safe_score": 1,
            "margin_over_safe": 0,
            "error": str(e)
        }

    labels = result["labels"]
    scores = result["scores"]

    best_label = labels[0]
    best_score = float(scores[0])

    safe_score = 0

    for label, score in zip(labels, scores):

        if label == BUSINESS_SAFE_LABEL:
            safe_score = float(score)
            break

    margin_over_safe = best_score - safe_score

    return {
        "best_label": best_label,
        "best_score": best_score,
        "safe_score": safe_score,
        "margin_over_safe": margin_over_safe,
        "error": ""
    }


def run_restaurant_refinement_ai_analysis(content):

    try:

        result = classifier(
            content,
            RESTAURANT_REFINEMENT_LABELS,
            hypothesis_template="{}",
            truncation=True
        )

    except Exception as e:

        return {
            "best_label": RESTAURANT_REFINEMENT_PUBLIC_LABEL,
            "best_score": 0,
            "second_score": 0,
            "margin": 0,
            "error": str(e)
        }

    labels = result["labels"]
    scores = result["scores"]

    best_label = labels[0]
    best_score = float(scores[0])

    second_score = 0

    if len(scores) > 1:
        second_score = float(scores[1])

    margin = best_score - second_score

    return {
        "best_label": best_label,
        "best_score": best_score,
        "second_score": second_score,
        "margin": margin,
        "error": ""
    }


def get_business_reason(best_business_label):

    if best_business_label == HEALTHCARE_LABEL:
        return (
            "AI semantic analysis detected private healthcare information, "
            "such as patient records, diagnoses, prescriptions, lab results, "
            "treatment details, or medical history."
        )

    if best_business_label == RESTAURANT_LABEL:
        return (
            "AI semantic analysis detected restaurant business-sensitive "
            "recipe or food production information."
        )

    if best_business_label == SOFTWARE_LABEL:
        return (
            "AI semantic analysis detected software-company intellectual "
            "property, such as proprietary algorithms, private source code, "
            "internal system design, architecture details, or unreleased "
            "technical plans."
        )

    return ""


def predict_file(file_path):

    try:
        content = read_file_content(file_path)
    except Exception:
        content = ""

    file_extension = os.path.splitext(file_path)[1].lower()

    if not content.strip():

        return "SAFE", 0, [], "", {
            "ml_prediction": "SAFE",
            "ml_confidence": 0,
            "ml_score": 0,
            "rule_score": 0,
            "reason": (
                "No readable text content was extracted from the file. "
                "If this is a scanned image PDF, OCR is required."
            ),
            "file_extension": file_extension,
            "extraction_status": "NO_TEXT_EXTRACTED"
        }

    if is_placeholder_template_document(content):

        return "SAFE", 0, [], content, {
            "ml_prediction": "SAFE",
            "ml_confidence": 0.99,
            "ml_score": 99,
            "rule_score": 0,
            "reason": (
                "The document contains placeholder/template secret fields only. "
                "No actual usable password, token, API key, or credential value "
                "was exposed."
            ),
            "secret_ai_label": "",
            "secret_ai_score": 0,
            "secret_safe_score": 1,
            "secret_margin_over_safe": 0,
            "secret_refinement_label": SECRET_REFINEMENT_PLACEHOLDER_LABEL,
            "secret_refinement_score": 1,
            "secret_refinement_margin": 1,
            "generic_ai_label": "",
            "generic_ai_score": 0,
            "business_ai_label": "",
            "business_ai_score": 0,
            "business_safe_score": 0,
            "business_margin_over_safe": 0,
            "restaurant_refinement_label": "",
            "restaurant_refinement_score": 0,
            "restaurant_refinement_margin": 0,
            "reproducible_formula_detail": False,
            "file_extension": file_extension,
            "extraction_status": "TEXT_EXTRACTED"
        }

    if is_clear_order_or_tracking_document(content):

        return "SAFE", 0, [], content, {
            "ml_prediction": "SAFE",
            "ml_confidence": 0.99,
            "ml_score": 99,
            "rule_score": 0,
            "reason": (
                "The document contains an order/tracking/reference number or "
                "public operational identifier. It does not expose usable "
                "payment card data, credentials, tokens, or private account data."
            ),
            "secret_ai_label": "",
            "secret_ai_score": 0,
            "secret_safe_score": 1,
            "secret_margin_over_safe": 0,
            "secret_refinement_label": SECRET_REFINEMENT_ORDER_LABEL,
            "secret_refinement_score": 1,
            "secret_refinement_margin": 1,
            "generic_ai_label": "",
            "generic_ai_score": 0,
            "business_ai_label": "",
            "business_ai_score": 0,
            "business_safe_score": 0,
            "business_margin_over_safe": 0,
            "restaurant_refinement_label": "",
            "restaurant_refinement_score": 0,
            "restaurant_refinement_margin": 0,
            "reproducible_formula_detail": False,
            "file_extension": file_extension,
            "extraction_status": "TEXT_EXTRACTED"
        }

    if contains_real_password_or_secret_assignment(content):

        final_confidence = 0.99
        final_score = int(final_confidence * 100)
        masked_content = mask_sensitive_content(content)

        return "SENSITIVE", final_score, [], content, {
            "ml_prediction": "SENSITIVE",
            "ml_confidence": round(final_confidence, 2),
            "ml_score": final_score,
            "rule_score": 100,
            "reason": (
                "Usable credential or technical secret assignment detected ->\n"
                f"{masked_content}"
            ),
            "secret_ai_label": SECRET_CREDENTIAL_LABEL,
            "secret_ai_score": 0.99,
            "secret_safe_score": 0,
            "secret_margin_over_safe": 0.99,
            "secret_refinement_label": SECRET_REFINEMENT_EXPOSED_LABEL,
            "secret_refinement_score": 0.99,
            "secret_refinement_margin": 0.99,
            "generic_ai_label": "",
            "generic_ai_score": 0,
            "business_ai_label": "",
            "business_ai_score": 0,
            "business_safe_score": 0,
            "business_margin_over_safe": 0,
            "restaurant_refinement_label": "",
            "restaurant_refinement_score": 0,
            "restaurant_refinement_margin": 0,
            "reproducible_formula_detail": False,
            "file_extension": file_extension,
            "extraction_status": "TEXT_EXTRACTED"
        }

    secret_result = run_secret_ai_analysis(content)

    secret_label = secret_result["best_label"]
    secret_score = secret_result["best_score"]
    secret_safe_score = secret_result["safe_score"]
    secret_margin = secret_result["margin_over_safe"]

    secret_refinement_label = ""
    secret_refinement_score = 0
    secret_refinement_margin = 0

    secret_sensitive_labels = [
        SECRET_PAYMENT_LABEL,
        SECRET_CREDENTIAL_LABEL,
        SECRET_TOKEN_LABEL,
        SECRET_FINANCIAL_IDENTITY_LABEL
    ]

    if secret_label in secret_sensitive_labels:

        secret_refinement = run_secret_refinement_ai_analysis(content)

        secret_refinement_label = secret_refinement["best_label"]
        secret_refinement_score = secret_refinement["best_score"]
        secret_refinement_margin = secret_refinement["margin"]

        secret_reason = get_secret_reason(secret_label)

        if (
            secret_refinement_label in [
                SECRET_REFINEMENT_POLICY_LABEL,
                SECRET_REFINEMENT_PLACEHOLDER_LABEL,
                SECRET_REFINEMENT_ORDER_LABEL,
                SECRET_REFINEMENT_PUBLIC_LABEL
            ]
            and secret_refinement_score >= AI_SECRET_REFINEMENT_SAFE_THRESHOLD
        ):

            pass

        elif (
            secret_refinement_label == SECRET_REFINEMENT_EXPOSED_LABEL
            and (
                secret_refinement_score >= AI_SECRET_REFINEMENT_EXPOSED_STRONG_THRESHOLD
                or secret_score >= AI_SECRET_REFINEMENT_EXPOSED_STRONG_THRESHOLD
                or (
                    secret_refinement_score >= AI_SECRET_REFINEMENT_SENSITIVE_THRESHOLD
                    and secret_refinement_margin >= AI_SECRET_REFINEMENT_MIN_MARGIN
                )
            )
        ):

            final_confidence = max(secret_score, secret_refinement_score, 0.61)
            final_score = int(final_confidence * 100)

            masked_content = mask_sensitive_content(content)

            explanation = {
                "ml_prediction": "SENSITIVE",
                "ml_confidence": round(final_confidence, 2),
                "ml_score": final_score,
                "rule_score": 0,
                "reason": (
                    secret_reason
                    + "\n"
                    + "Focused AI secret-data analysis confirmed that the "
                    + "text exposes actual usable sensitive data, not only a "
                    + "policy, warning, placeholder, order number, or general discussion."
                    + "\n"
                    + masked_content
                ),
                "secret_ai_label": secret_label,
                "secret_ai_score": round(secret_score, 2),
                "secret_safe_score": round(secret_safe_score, 2),
                "secret_margin_over_safe": round(secret_margin, 2),
                "secret_refinement_label": secret_refinement_label,
                "secret_refinement_score": round(secret_refinement_score, 2),
                "secret_refinement_margin": round(secret_refinement_margin, 2),
                "generic_ai_label": "",
                "generic_ai_score": 0,
                "business_ai_label": "",
                "business_ai_score": 0,
                "business_safe_score": 0,
                "business_margin_over_safe": 0,
                "restaurant_refinement_label": "",
                "restaurant_refinement_score": 0,
                "restaurant_refinement_margin": 0,
                "reproducible_formula_detail": False,
                "file_extension": file_extension,
                "extraction_status": "TEXT_EXTRACTED"
            }

            return "SENSITIVE", final_score, [], content, explanation

        elif (
            secret_score >= AI_SECRET_MEDIUM_THRESHOLD
            and secret_margin > 0
            and secret_refinement_label == SECRET_REFINEMENT_EXPOSED_LABEL
        ):

            final_confidence = max(secret_score, secret_refinement_score, 0.51)
            final_score = int(final_confidence * 100)

            explanation = {
                "ml_prediction": "MEDIUM",
                "ml_confidence": round(final_confidence, 2),
                "ml_score": final_score,
                "rule_score": 0,
                "reason": (
                    secret_reason
                    + "\n"
                    + "AI secret-data layer detected possible exposed "
                    + "sensitive data, but confidence was not strong enough "
                    + "for automatic blocking."
                ),
                "secret_ai_label": secret_label,
                "secret_ai_score": round(secret_score, 2),
                "secret_safe_score": round(secret_safe_score, 2),
                "secret_margin_over_safe": round(secret_margin, 2),
                "secret_refinement_label": secret_refinement_label,
                "secret_refinement_score": round(secret_refinement_score, 2),
                "secret_refinement_margin": round(secret_refinement_margin, 2),
                "generic_ai_label": "",
                "generic_ai_score": 0,
                "business_ai_label": "",
                "business_ai_score": 0,
                "business_safe_score": 0,
                "business_margin_over_safe": 0,
                "restaurant_refinement_label": "",
                "restaurant_refinement_score": 0,
                "restaurant_refinement_margin": 0,
                "reproducible_formula_detail": False,
                "file_extension": file_extension,
                "extraction_status": "TEXT_EXTRACTED"
            }

            return "MEDIUM", final_score, [], content, explanation

    if contains_value(content):

        final_confidence = 0.99
        final_score = int(final_confidence * 100)

        masked_content = mask_sensitive_content(content)

        explanation = {
            "ml_prediction": "SENSITIVE",
            "ml_confidence": round(final_confidence, 2),
            "ml_score": final_score,
            "rule_score": 100,
            "reason": f"Sensitive data detected ->\n{masked_content}",
            "secret_ai_label": secret_label,
            "secret_ai_score": round(secret_score, 2),
            "secret_safe_score": round(secret_safe_score, 2),
            "secret_margin_over_safe": round(secret_margin, 2),
            "secret_refinement_label": secret_refinement_label,
            "secret_refinement_score": round(secret_refinement_score, 2),
            "secret_refinement_margin": round(secret_refinement_margin, 2),
            "generic_ai_label": "",
            "generic_ai_score": 0,
            "business_ai_label": "",
            "business_ai_score": 0,
            "business_safe_score": 0,
            "business_margin_over_safe": 0,
            "restaurant_refinement_label": "",
            "restaurant_refinement_score": 0,
            "restaurant_refinement_margin": 0,
            "reproducible_formula_detail": False,
            "file_extension": file_extension,
            "extraction_status": "TEXT_EXTRACTED"
        }

        return "SENSITIVE", final_score, [], content, explanation

    generic_result = run_generic_ai_analysis(content)

    generic_label = generic_result["best_label"]
    generic_score = generic_result["best_score"]

    business_result = run_business_ai_analysis(content)

    business_label = business_result["best_label"]
    business_score = business_result["best_score"]
    business_safe_score = business_result["safe_score"]
    business_margin = business_result["margin_over_safe"]

    restaurant_refinement_label = ""
    restaurant_refinement_score = 0
    restaurant_refinement_margin = 0

    reproducible_formula_detail = has_reproducible_formula_detail(content)

    final_label = "SAFE"
    final_confidence = max(generic_score, business_score, secret_safe_score)
    final_score = int(final_confidence * 100)
    rule_score = 0
    reason_text = ""

    business_sensitive_labels = [
        HEALTHCARE_LABEL,
        RESTAURANT_LABEL,
        SOFTWARE_LABEL
    ]

    if business_label in business_sensitive_labels:

        business_reason = get_business_reason(business_label)

        if (
            business_score >= AI_BUSINESS_SENSITIVE_THRESHOLD
            and business_margin >= AI_MIN_MARGIN_OVER_SAFE
        ):

            final_label = "SENSITIVE"
            rule_score = 90
            reason_text = business_reason

        elif (
            business_score >= AI_BUSINESS_MEDIUM_THRESHOLD
            and business_margin > 0
        ):

            final_label = "MEDIUM"
            rule_score = 50
            reason_text = business_reason

    if final_label == "SAFE":

        if (
            generic_label == GENERIC_SENSITIVE_LABEL
            and generic_score >= AI_GENERIC_SENSITIVE_THRESHOLD
            and len(content.split()) > 5
        ):

            final_label = "SENSITIVE"
            rule_score = 85
            reason_text = (
                "AI semantic analysis detected highly confident confidential "
                "or sensitive information."
            )

        elif (
            generic_label == GENERIC_SENSITIVE_LABEL
            and generic_score >= AI_GENERIC_MEDIUM_THRESHOLD
            and len(content.split()) > 5
        ):

            final_label = "MEDIUM"
            rule_score = 40
            reason_text = (
                "AI semantic analysis detected general confidential or "
                "sensitive information."
            )

    if (
        final_label == "MEDIUM"
        and generic_label == GENERIC_SENSITIVE_LABEL
        and generic_score >= AI_GENERIC_SENSITIVE_THRESHOLD
        and len(content.split()) > 5
    ):

        final_label = "SENSITIVE"
        rule_score = max(rule_score, 85)

        if reason_text:
            reason_text = (
                reason_text
                + " Also, the generic AI detector found highly confident "
                + "confidential or sensitive information."
            )

        else:
            reason_text = (
                "AI semantic analysis detected highly confident confidential "
                "or sensitive information."
            )

    if (
        business_label == RESTAURANT_LABEL
        and final_label in ["SAFE", "MEDIUM", "SENSITIVE"]
    ):

        restaurant_result = run_restaurant_refinement_ai_analysis(content)

        restaurant_refinement_label = restaurant_result["best_label"]
        restaurant_refinement_score = restaurant_result["best_score"]
        restaurant_refinement_margin = restaurant_result["margin"]

        final_confidence = max(
            final_confidence,
            restaurant_refinement_score
        )

        final_score = int(final_confidence * 100)

        if not reproducible_formula_detail:

            if (
                restaurant_refinement_label
                == RESTAURANT_REFINEMENT_PUBLIC_LABEL
                and restaurant_refinement_score
                >= AI_RESTAURANT_REFINEMENT_SAFE_THRESHOLD
            ):

                final_label = "SAFE"
                rule_score = 0
                reason_text = (
                    "Focused AI restaurant analysis determined that the text "
                    "only mentions or discusses a restaurant recipe, sauce, "
                    "taste, or menu item without revealing enough concrete "
                    "details to reproduce the internal food product."
                )

            elif final_label == "SENSITIVE":

                final_label = "MEDIUM"
                rule_score = min(rule_score, 50)
                reason_text = (
                    "AI detected restaurant-related sensitive context, but "
                    "the file does not contain enough concrete reproducible "
                    "formula detail. It is treated as medium-risk for review."
                )

        else:

            if (
                restaurant_refinement_label
                == RESTAURANT_REFINEMENT_SENSITIVE_LABEL
                and restaurant_refinement_score
                >= AI_RESTAURANT_REFINEMENT_SENSITIVE_THRESHOLD
                and restaurant_refinement_margin
                >= AI_RESTAURANT_REFINEMENT_MIN_MARGIN
            ):

                final_label = "SENSITIVE"
                rule_score = max(rule_score, 92)

                reason_text = (
                    "Focused AI restaurant analysis detected business-sensitive "
                    "recipe or food production information. The content contains "
                    "enough concrete formula or preparation details to reproduce "
                    "an internal restaurant menu item."
                )

            elif (
                reproducible_formula_detail
                and business_label == RESTAURANT_LABEL
                and business_score >= AI_BUSINESS_MEDIUM_THRESHOLD
            ):

                final_label = "SENSITIVE"
                rule_score = max(rule_score, 92)

                reason_text = (
                    "AI semantic analysis detected restaurant business-sensitive "
                    "recipe or food production information. The file contains "
                    "concrete reproducible formula details such as ingredient "
                    "quantities, preparation timing, or storage instructions."
                )

    explanation = {
        "ml_prediction": final_label,
        "ml_confidence": round(final_confidence, 2),
        "ml_score": final_score,
        "rule_score": rule_score,
        "reason": reason_text,
        "secret_ai_label": secret_label,
        "secret_ai_score": round(secret_score, 2),
        "secret_safe_score": round(secret_safe_score, 2),
        "secret_margin_over_safe": round(secret_margin, 2),
        "secret_refinement_label": secret_refinement_label,
        "secret_refinement_score": round(secret_refinement_score, 2),
        "secret_refinement_margin": round(secret_refinement_margin, 2),
        "generic_ai_label": generic_label,
        "generic_ai_score": round(generic_score, 2),
        "business_ai_label": business_label,
        "business_ai_score": round(business_score, 2),
        "business_safe_score": round(business_safe_score, 2),
        "business_margin_over_safe": round(business_margin, 2),
        "restaurant_refinement_label": restaurant_refinement_label,
        "restaurant_refinement_score": round(restaurant_refinement_score, 2),
        "restaurant_refinement_margin": round(restaurant_refinement_margin, 2),
        "reproducible_formula_detail": reproducible_formula_detail,
        "file_extension": file_extension,
        "extraction_status": "TEXT_EXTRACTED"
    }

    return final_label, final_score, [], content, explanation
