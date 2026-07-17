"""Text processing and validation utilities."""

import re
import secrets
import string
import unicodedata
import uuid
from urllib.parse import urlparse


def json_extractor(text: str) -> dict:
    """Extract a JSON object from a string and return it as a dict."""
    import json

    json_string = text[text.find("{") : text.rfind("}") + 1]
    return json.loads(json_string)


def format_string_keys(text: str) -> set[str]:
    """Return the set of placeholder keys found in a format string."""
    return {t[1] for t in string.Formatter().parse(text) if t[1]}


def format_string_fixer(**kwargs: object) -> list[dict[str, object]]:
    """Convert parallel keyword lists into a list of dicts."""
    list_length = len(next(iter(kwargs.values())))

    # Initialize the target list
    target = []

    # Iterate over each index of the lists
    for i in range(list_length):
        # Create a new dictionary for each index
        entry = {key: kwargs[key][i] for key in kwargs}
        # Append the new dictionary to the target list
        target.append(entry)

    return target


def escape_markdown(text: str) -> str:
    """Escape Markdown special characters in a string."""
    replacements = [
        ("_", r"\_"),
        ("*", r"\*"),
        ("[", r"\["),
        ("]", r"\]"),
        ("(", r"\("),
        (")", r"\)"),
        ("~", r"\~"),
        (">", r"\>"),
        ("#", r"\#"),
        ("+", r"\+"),
        ("-", r"\-"),
        ("=", r"\="),
        ("|", r"\|"),
        ("{", r"\{"),
        ("}", r"\}"),
        (".", r"\."),
        ("!", r"\!"),
        ("=", r"\="),
    ]

    for old, new in replacements:
        text = text.replace(old, new)

    return text


def _split_sentence(sentence: str, max_chunk_size: int, current_chunk: str) -> str:
    """Split a sentence into chunks."""
    if len(sentence) > max_chunk_size:
        # Split sentence into words
        words = sentence.split(" ")
        for word in words:
            if len(current_chunk) + len(word) + 1 > max_chunk_size and current_chunk:
                return current_chunk.strip()
            current_chunk += word + " "
    else:
        current_chunk += sentence + " "

    return current_chunk


def _split_paragraph(
    paragraph: str, max_chunk_size: int, current_chunk: str
) -> tuple[list[str], str]:
    """Split a paragraph into chunks."""
    chunks = []

    if len(current_chunk) + len(paragraph) + 1 > max_chunk_size and current_chunk:
        if current_chunk.count("```") % 2 == 1:
            chunks.append(current_chunk[: current_chunk.rfind("```")].strip())
            current_chunk = current_chunk[current_chunk.rfind("```") :]
            return chunks, current_chunk

        chunks.append(current_chunk.strip())
        current_chunk = ""
        return chunks, current_chunk

    if len(paragraph) > max_chunk_size:
        # Split paragraph into sentences
        sentences = re.split(r"(?<=[.!?]) +", paragraph)
        for sentence in sentences:
            if (
                len(current_chunk) + len(sentence) + 1 > max_chunk_size
                and current_chunk
            ):
                chunks.append(current_chunk.strip())
                current_chunk = ""

            current_chunk = _split_sentence(sentence, max_chunk_size, current_chunk)
    else:
        current_chunk += paragraph + "\n"

    return chunks, current_chunk


def split_text(text: str, max_chunk_size: int = 4096) -> list[str]:
    """Split text into chunks while preserving structure."""
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""

    for paragraph in paragraphs:
        new_chunks, current_chunk = _split_paragraph(
            paragraph, max_chunk_size, current_chunk
        )
        chunks.extend(new_chunks)

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def replace_unicode_digits(match: re.Match) -> str:
    """Replace a single unicode digit character with its ASCII equivalent."""
    char = match.group()
    return str(unicodedata.digit(char))


def convert_to_english_digits(input_str: str) -> str:
    """Convert all unicode digits in a string to their ASCII equivalents."""
    non_ascii_digit_pattern = re.compile(r"\d", re.UNICODE)
    return non_ascii_digit_pattern.sub(replace_unicode_digits, input_str)


url_regex = re.compile(r"(?:https?|ftp)://[^\s<>()]+", re.IGNORECASE)
phone_regex = re.compile(r"^[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}$")
email_regex = re.compile(r"^[a-zA-Z\._]+@[a-zA-Z0-9\.-_]+\.[a-zA-Z]{2,}$")
username_regex = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{2,16}$")


def is_valid_uuid(val: str) -> bool:
    """Check whether a string is a valid UUID."""
    try:
        uuid.UUID(str(val))
    except ValueError:
        return False
    return True


def is_valid_url(url: str) -> bool:
    """Check whether a string is a valid URL."""
    if url_regex.fullmatch(url) is None:
        return False

    # Additional check using urllib.parse to ensure proper scheme and netloc
    parsed_url = urlparse(url)
    return all([parsed_url.scheme, parsed_url.netloc])


def contains_valid_urls(text: str) -> list[str]:
    """Return all valid URLs found within a string."""
    return [
        url
        for match in url_regex.finditer(text)
        if (url := match.group().rstrip(".,!?;:")) and is_valid_url(url)
    ]


def is_username(username: str) -> bool:
    """Check whether a string matches the username pattern."""
    return bool(username_regex.search(username))


def is_email(email: str) -> bool:
    """Check whether a string matches the email pattern."""
    return bool(email_regex.search(email))


def is_phone(phone: str) -> bool:
    """Check whether a string matches the phone number pattern."""
    return bool(phone_regex.search(phone))


def normalize_phone(phone: str) -> str:
    """Remove + prefix and whitespace from a phone number."""
    return phone.removeprefix("+").replace(" ", "").replace("-", "")


def generate_random_chars(
    length: int = 6, characters: str = string.ascii_letters + string.digits
) -> str:
    """Generate a cryptographically random string of the given length."""
    # Generate the random characters
    return "".join(secrets.choice(characters) for _ in range(length))


def replace_whitespace(match: re.Match) -> str:
    """Replace whitespace runs with either a newline or a space."""
    if "\n" in match.group():
        return "\n"
    else:
        return " "


def remove_whitespace(text: str) -> str:
    """Collapse consecutive whitespace into single spaces, preserving newlines."""
    return re.sub(r"\s+", replace_whitespace, text)


def sanitize_filename(
    draft_name: str, max_length: int = 0, space_remover: bool = True
) -> str:
    """Sanitize a filename by removing invalid characters and optionally truncating."""
    # get filename from URL
    if draft_name.startswith("http"):
        url_parts = urlparse(draft_name)
        draft_name = url_parts.path

    # Remove path and extension
    draft_name = draft_name.split("/")[-1].strip()
    dotted_name = draft_name.split(".")
    pure_name = ".".join(dotted_name[:-1] if len(dotted_name) > 1 else dotted_name)

    # Remove invalid characters and replace spaces with underscores
    # Valid characters: alphanumeric, underscores, and periods and spaces
    sanitized = re.sub(r"[^a-zA-Z0-9_. ]", "", pure_name)

    if max_length > 0:
        position = pure_name.find(" ", max_length * 4 // 5)
        if position > max_length * 6 // 5 or position == -1:
            position = max_length
        sanitized = sanitized[:position]  # Limit to 100 characters

    if space_remover:
        # Replace spaces with underscores
        sanitized = sanitized.replace(" ", "_")

    return sanitized
