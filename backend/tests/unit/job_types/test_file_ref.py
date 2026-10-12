"""``FileRef``: a UUID on the wire that marks a file field."""

import uuid

import pytest
from pydantic import BaseModel, Field, ValidationError

from qfe.job_types import FileRef, find_file_refs


class Nested(BaseModel):
    attachments: list[FileRef]


class Holder(BaseModel):
    single: FileRef
    many: list[FileRef] = Field(default_factory=list)
    maybe: FileRef | None = None
    nested: Nested | None = None
    by_name: dict[str, FileRef] = Field(default_factory=dict)


A, B, C, D, E = (str(uuid.uuid4()) for _ in range(5))


def test_it_accepts_a_uuid_string_and_gives_a_file_ref() -> None:
    holder = Holder(single=A)
    assert isinstance(holder.single, FileRef)
    assert str(holder.single) == A


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "123", "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"])
def test_it_rejects_other_strings(bad: str) -> None:
    with pytest.raises(ValidationError):
        Holder(single=bad)


def test_it_serialises_back_to_a_plain_string() -> None:
    dumped = Holder(single=A, many=[B]).model_dump(mode="json")
    assert dumped["single"] == A
    assert dumped["many"] == [B]
    assert all(isinstance(value, str) for value in (dumped["single"], *dumped["many"]))


def test_the_json_schema_marks_file_fields() -> None:
    schema = Holder.model_json_schema()
    single = schema["properties"]["single"]
    assert single["format"] == "uuid"
    assert single["x-file-ref"] is True
    assert schema["properties"]["many"]["items"]["x-file-ref"] is True


def test_every_file_id_is_found_wherever_it_sits() -> None:
    holder = Holder.model_validate(
        {
            "single": A,
            "many": [B, C],
            "maybe": D,
            "nested": {"attachments": [E]},
            "by_name": {"x": B},
        }
    )
    found = {str(ref) for ref in find_file_refs(holder)}
    assert found == {A, B, C, D, E}


def test_each_id_is_reported_once_in_order_of_first_appearance() -> None:
    holder = Holder.model_validate({"single": A, "many": [B, A, B], "maybe": B})
    assert [str(ref) for ref in find_file_refs(holder)] == [A, B]


def test_an_absent_optional_field_adds_nothing() -> None:
    assert [str(ref) for ref in find_file_refs(Holder.model_validate({"single": A}))] == [A]


def test_plain_uuids_are_not_file_refs() -> None:
    class Plain(BaseModel):
        id: uuid.UUID

    assert find_file_refs(Plain(id=uuid.uuid4())) == ()
