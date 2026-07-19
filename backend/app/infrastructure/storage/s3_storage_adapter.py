"""
S3StorageAdapter — FileStorage over an S3-compatible object store.

Why this exists
---------------
Free hosting tiers give an EPHEMERAL filesystem: every redeploy, restart and
instance replacement wipes it. `LocalStorageAdapter` is correct locally and
silently catastrophic there — uploaded PAN/Aadhaar scans, photos, signatures
and generated KYC PDFs would vanish while the database still referenced them,
turning every document into `document_not_found`.

This adapter stores the same bytes in an S3-compatible bucket (Supabase
Storage in production, but any S3 API works — MinIO, R2, S3 itself) so they
survive the instance. It implements the SAME `FileStorage` port with the SAME
category/filename addressing, so no service or route changes.

Security
--------
The bucket MUST be private. Nothing here ever generates a public URL or a
presigned link: bytes are read server-side and returned through the
application's existing authenticated, ownership-checked endpoints. That keeps
one authorization path for KYC documents rather than two, and means a leaked
object key is not itself a leak of the document.

Object keys mirror the local layout (`pdf/<uuid>.pdf`, `images/<uuid>.jpg`),
so the two adapters address the same logical file and switching backends does
not invalidate stored filenames already recorded in the database.
"""

import logging

from app.domain.enums import DocumentCategory
from app.domain.repositories import FileStorage

try:  # Optional dependency — absent locally where the local adapter is used.
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

# Same prefixes the local adapter uses as directories, so an object key is
# byte-for-byte the local relative path.
_CATEGORY_PREFIXES: dict[DocumentCategory, str] = {
    DocumentCategory.PDF: "pdf",
    DocumentCategory.IMAGE: "images",
}


class S3StorageAdapter(FileStorage):
    """FileStorage implementation backed by a PRIVATE S3-compatible bucket."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
    ) -> None:
        if boto3 is None:  # pragma: no cover
            raise RuntimeError("boto3 is not installed (pip install boto3).")
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            # Supabase and most S3-compatible gateways require SigV4 and
            # path-style addressing; virtual-host style resolves to a
            # nonexistent subdomain against them.
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        # Never log credentials or the endpoint's query string.
        logger.info("S3StorageAdapter bound to bucket %r", bucket)

    # ------------------------------------------------------------------ #
    # FileStorage port
    # ------------------------------------------------------------------ #

    def save(self, category: DocumentCategory, stored_filename: str, content: bytes) -> str:
        key = self._key(category, stored_filename)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=content)
        logger.info("Stored %d bytes at s3://%s/%s", len(content), self._bucket, key)
        return key

    def read(self, category: DocumentCategory, stored_filename: str) -> bytes:
        key = self._key(category, stored_filename)
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as exc:  # pragma: no cover - network dependent
            # Match LocalStorageAdapter, which raises FileNotFoundError for a
            # missing file, so callers keep one failure mode across backends.
            if self._is_missing(exc):
                raise FileNotFoundError(key) from exc
            raise

    def delete(self, category: DocumentCategory, stored_filename: str) -> bool:
        key = self._key(category, stored_filename)
        if not self.exists(category, stored_filename):
            return False
        self._client.delete_object(Bucket=self._bucket, Key=key)
        logger.info("Deleted stored object s3://%s/%s", self._bucket, key)
        return True

    def exists(self, category: DocumentCategory, stored_filename: str) -> bool:
        try:
            self._client.head_object(
                Bucket=self._bucket, Key=self._key(category, stored_filename)
            )
            return True
        except ClientError as exc:  # pragma: no cover - network dependent
            if self._is_missing(exc):
                return False
            raise

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_missing(exc: "ClientError") -> bool:
        """True when the error means 'no such object', not a real failure."""
        code = exc.response.get("Error", {}).get("Code", "")
        return code in {"404", "NoSuchKey", "NotFound"}

    def _key(self, category: DocumentCategory, stored_filename: str) -> str:
        """Build the object key, refusing anything that could escape its prefix."""
        # Stored filenames are uuid-based by construction. This mirrors the
        # local adapter's traversal guard: a key containing a slash or a
        # relative segment could otherwise address another prefix entirely.
        if (
            "/" in stored_filename
            or "\\" in stored_filename
            or stored_filename in {"", ".", ".."}
        ):
            raise ValueError(f"Illegal stored filename: {stored_filename!r}")
        return f"{_CATEGORY_PREFIXES[category]}/{stored_filename}"
