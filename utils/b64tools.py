import base64
import uuid


def b64_encode_uuid(uuid_str: str) -> str:
    uuid_bytes = uuid.UUID(uuid_str).bytes
    encoded_uuid = base64.urlsafe_b64encode(uuid_bytes).decode()
    return encoded_uuid


def b64_encode_uuid_strip(uuid_str: str) -> str:
    return b64_encode_uuid(uuid_str).rstrip("=")


def b64_decode_uuid(encoded_uuid: str) -> uuid.UUID:
    encoded_uuid += "=" * (4 - len(encoded_uuid) % 4)  # Add padding if needed
    decoded_uuid = base64.urlsafe_b64decode(encoded_uuid)
    uuid_obj = uuid.UUID(bytes=decoded_uuid)
    return uuid_obj
