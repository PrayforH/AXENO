"""MinIO-backed artifact byte store with atomic promotion."""

import asyncio
import hashlib
from io import BytesIO
from uuid import uuid4

from minio import Minio
from minio.commonconfig import CopySource
from minio.error import S3Error

from harness.core.errors import NotFoundError, StorageCapacityError
from harness.core.ports import StoredObject


class MinioArtifactStore:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket

    async def put(self, tenant_id: str, artifact_id: str, content: bytes) -> StoredObject:
        final_key = f"{tenant_id}/{artifact_id}"
        temporary_key = f".tmp/{tenant_id}/{artifact_id}-{uuid4().hex}"

        def upload() -> None:
            try:
                self._client.put_object(
                    self._bucket,
                    temporary_key,
                    BytesIO(content),
                    len(content),
                    content_type="application/octet-stream",
                )
                self._client.copy_object(
                    self._bucket,
                    final_key,
                    CopySource(self._bucket, temporary_key),
                )
            except S3Error as error:
                if error.code in {
                    "XMinioStorageFull",
                    "StorageFull",
                    "InsufficientStorage",
                }:
                    raise StorageCapacityError(
                        "attachment storage is full; free Colima storage and retry"
                    ) from error
                raise
            finally:
                # Promotion is atomic from the caller's perspective; a failed
                # copy must not leave temporary uploads accumulating forever.
                try:
                    self._client.remove_object(self._bucket, temporary_key)
                except S3Error:
                    pass

        await asyncio.to_thread(upload)
        return StoredObject(
            object_key=final_key,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    async def get(self, tenant_id: str, artifact_id: str) -> bytes:
        key = f"{tenant_id}/{artifact_id}"

        def download() -> bytes:
            try:
                response = self._client.get_object(self._bucket, key)
                try:
                    return response.read()
                finally:
                    response.close()
                    response.release_conn()
            except S3Error as error:
                if error.code in {"NoSuchKey", "NoSuchObject"}:
                    raise NotFoundError(f"artifact not found: {artifact_id}") from error
                raise

        return await asyncio.to_thread(download)

    async def delete(self, tenant_id: str, artifact_id: str) -> None:
        key = f"{tenant_id}/{artifact_id}"
        await asyncio.to_thread(self._client.remove_object, self._bucket, key)
