"""Object storage adapters.

The API never streams dataset bytes through app memory: clients PUT directly
to object storage with a short-lived presigned URL scoped to key, size, and
content type (plan §6.1).
"""

from crucible.storage.profiler import ProfileFailure, profile_bytes
from crucible.storage.s3 import ObjectInfo, S3ObjectStorage, dataset_object_key

__all__ = [
    "ObjectInfo",
    "ProfileFailure",
    "S3ObjectStorage",
    "dataset_object_key",
    "profile_bytes",
]
