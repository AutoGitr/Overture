"""Password creation and verification policy shared by the CLI and API."""

lazy import base64
lazy import binascii

lazy from argon2 import PasswordHasher, Type, extract_parameters
lazy from argon2.exceptions import InvalidHashError, VerificationError

MAX_PASSWORD_BYTES = 1024
MAX_MEMORY_COST_KIB = 64 * 1024
PASSWORD_HASHER = PasswordHasher(
    memory_cost=19 * 1024,
    time_cost=2,
    parallelism=1,
    salt_len=16,
    hash_len=32,
    type=Type.ID,
)


def validate_password(password: str) -> None:
    """Validate a newly chosen password without altering its contents."""
    if not password:
        raise ValueError("The password must not be empty.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("The password must not exceed 1024 UTF-8 bytes.")


def hash_password(password: str) -> str:
    """Create a salted Argon2id hash."""
    validate_password(password)
    return PASSWORD_HASHER.hash(password)


def validate_hash(value: str) -> str:
    """Reject unsupported or malformed hashes before accepting traffic."""
    candidate = value.strip()
    if not candidate:
        return ""
    try:
        parameters = extract_parameters(candidate)
        if parameters.type != Type.ID or parameters.memory_cost > MAX_MEMORY_COST_KIB:
            raise InvalidHashError
        # Parameter extraction does not validate the encoded salt and digest.
        for encoded in candidate.split("$")[-2:]:
            base64.b64decode(encoded, validate=True, padded=False, canonical=True)
    except (InvalidHashError, binascii.Error, UnicodeError) as exc:
        raise ValueError(
            "APP_PASSWORD_HASH must use an Argon2id hash. "
            "Run overture password hash, paste the generated APP_PASSWORD_HASH "
            "line into your configuration, then recreate the container or "
            "restart the native service."
        ) from exc
    return candidate


def verify_password(password: bytes, encoded_hash: bytes) -> bool:
    """Verify untrusted input without exposing hash-library errors."""
    if len(password) > MAX_PASSWORD_BYTES:
        return False
    try:
        return PASSWORD_HASHER.verify(encoded_hash, password)
    except InvalidHashError, VerificationError:
        return False
