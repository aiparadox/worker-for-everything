"""``FileRef``: a field in an input schema that holds the id of an uploaded file.

On the wire it is a UUID string. It is a UUID subclass, so after validation the payload holds
``FileRef`` objects and finding every file id is a plain walk over the data: it works for a single
field, a list, an optional field and nested models. Its JSON schema carries ``x-file-ref`` so
``GET /v1/job-types`` can tell clients which fields are files. Whether a file belongs to the
organisation and exists is checked elsewhere (the file API), not here.
"""

import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema


class FileRef(uuid.UUID):
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            lambda value: cls(int=value.int),
            handler(uuid.UUID),
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(schema)
        json_schema["x-file-ref"] = True
        return json_schema


def find_file_refs(data: Any) -> tuple[FileRef, ...]:
    """Every ``FileRef`` in validated data, in order of first appearance, each once."""
    found: dict[FileRef, None] = {}

    def walk(value: Any) -> None:
        if isinstance(value, FileRef):
            found.setdefault(value, None)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                walk(getattr(value, name))
        elif isinstance(value, Mapping):
            walk_all(value.values())
        elif isinstance(value, list | tuple | set | frozenset):
            walk_all(value)

    def walk_all(values: Iterable[Any]) -> None:
        for item in values:
            walk(item)

    walk(data)
    return tuple(found)
