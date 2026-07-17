"""Base64 UUID encoding and decoding utilities."""

import base64
import uuid


def b64_encode_uuid(uuid_str: str) -> str:
    """Encode a UUID string into a base64 URL-safe string."""
    uuid_bytes = uuid.UUID(uuid_str).bytes
    encoded_uuid = base64.urlsafe_b64encode(uuid_bytes).decode()
    return encoded_uuid


def b64_encode_uuid_strip(uuid_str: str) -> str:
    """Encode a UUID string into a base64 string without padding."""
    return b64_encode_uuid(uuid_str).rstrip("=")


def b64_decode_uuid(encoded_uuid: str) -> uuid.UUID:
    """Decode a base64 URL-safe string back into a UUID object."""
    encoded_uuid += "=" * (4 - len(encoded_uuid) % 4)  # Add padding if needed
    decoded_uuid = base64.urlsafe_b64decode(encoded_uuid)
    uuid_obj = uuid.UUID(bytes=decoded_uuid)
    return uuid_obj
