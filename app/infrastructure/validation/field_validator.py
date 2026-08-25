import re
from datetime import datetime
from typing import Any

from app.infrastructure.logging import get_logger

logger = get_logger("field_validator")

FIELD_TYPES = frozenset(
    {
        "text",
        "textarea",
        "richtext",
        "number",
        "select",
        "multi_select",
        "boolean",
        "date",
        "datetime",
        "url",
        "email",
        "color",
        "image",
        "gallery",
        "json",
    }
)

_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _validate_text_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(f"Field '{field['key']}': text value must be a string")
        return
    min_len = field.get("min_length")
    max_len = field.get("max_length")
    if min_len is not None and len(value) < min_len:
        errors.append(
            f"Field '{field['key']}': text value shorter than min_length ({min_len})"
        )
    if max_len is not None and len(value) > max_len:
        errors.append(
            f"Field '{field['key']}': text value longer than max_length ({max_len})"
        )
    pattern = field.get("pattern")
    if pattern and not re.search(pattern, value):
        errors.append(
            f"Field '{field['key']}': text value does not match pattern '{pattern}'"
        )


def _validate_number_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if isinstance(value, str):
        try:
            value = float(value) if "." in value else int(value)
            field["value"] = value
        except (ValueError, TypeError):
            errors.append(f"Field '{field['key']}': number value must be numeric")
            return
    if not isinstance(value, (int, float)):
        errors.append(f"Field '{field['key']}': number value must be numeric")
        return
    min_val = field.get("min")
    max_val = field.get("max")
    if min_val is not None and value < min_val:
        errors.append(
            f"Field '{field['key']}': number value {value} below min ({min_val})"
        )
    if max_val is not None and value > max_val:
        errors.append(
            f"Field '{field['key']}': number value {value} above max ({max_val})"
        )
    decimal_places = field.get("decimal_places")
    if decimal_places is not None:
        str_val = str(value)
        if "." in str_val:
            decimals = len(str_val.split(".")[1])
            if decimals > decimal_places:
                errors.append(
                    f"Field '{field['key']}': number has {decimals} decimal places, max is {decimal_places}"
                )


def _validate_select_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    options = field.get("options", [])
    if not options:
        errors.append(f"Field '{field['key']}': select requires at least 1 option")
        return
    if value not in options:
        errors.append(
            f"Field '{field['key']}': value '{value}' not in options {options}"
        )


def _validate_multi_select_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, list):
        errors.append(f"Field '{field['key']}': multi_select value must be a list")
        return
    options = field.get("options", [])
    if not options:
        errors.append(
            f"Field '{field['key']}': multi_select requires at least 1 option"
        )
        return
    invalid = [v for v in value if v not in options]
    if invalid:
        errors.append(
            f"Field '{field['key']}': invalid values {invalid} not in options {options}"
        )
    max_sel = field.get("max_selections")
    if max_sel is not None and len(value) > max_sel:
        errors.append(
            f"Field '{field['key']}': {len(value)} selections exceeds max ({max_sel})"
        )


def _validate_url_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, str) or not _URL_RE.match(value):
        errors.append(f"Field '{field['key']}': invalid URL format")


def _validate_email_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, str) or not _EMAIL_RE.match(value):
        errors.append(f"Field '{field['key']}': invalid email format")


def _validate_color_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, str) or not _COLOR_RE.match(value):
        errors.append(f"Field '{field['key']}': invalid hex color format")


def _validate_image_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(
            f"Field '{field['key']}': image value must be a string (URL/path)"
        )
        return
    allowed = field.get("allowed_types")
    if allowed and isinstance(value, str):
        ext = value.rsplit(".", 1)[-1].lower() if "." in value else ""
        if ext not in allowed:
            errors.append(
                f"Field '{field['key']}': image type '{ext}' not in allowed {allowed}"
            )


def _validate_gallery_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, list):
        errors.append(f"Field '{field['key']}': gallery value must be a list")
        return
    max_images = field.get("max_images")
    if max_images is not None and len(value) > max_images:
        errors.append(
            f"Field '{field['key']}': {len(value)} images exceeds max ({max_images})"
        )


def _validate_boolean_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if isinstance(value, str):
        lower = value.lower()
        if lower in ("true", "1", "yes"):
            field["value"] = True
            return
        if lower in ("false", "0", "no"):
            field["value"] = False
            return
    if not isinstance(value, bool):
        errors.append(f"Field '{field['key']}': boolean value must be true or false")


def _validate_date_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(f"Field '{field['key']}': date value must be a string")
        return
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        min_date = field.get("min_date")
        max_date = field.get("max_date")
        if min_date and parsed < datetime.strptime(min_date, "%Y-%m-%d"):
            errors.append(
                f"Field '{field['key']}': date {value} is before min_date ({min_date})"
            )
        if max_date and parsed > datetime.strptime(max_date, "%Y-%m-%d"):
            errors.append(
                f"Field '{field['key']}': date {value} is after max_date ({max_date})"
            )
    except ValueError:
        errors.append(
            f"Field '{field['key']}': invalid date format, expected YYYY-MM-DD"
        )


def _validate_datetime_value(field: dict, errors: list[str]) -> None:
    value = field.get("value")
    if value is None:
        return
    if not isinstance(value, str):
        errors.append(f"Field '{field['key']}': datetime value must be a string")
        return
    for _fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(
                value.replace("+00:00", "Z").rstrip("Z") + "Z", "%Y-%m-%dT%H:%M:%SZ"
            )
            min_date = field.get("min_date")
            max_date = field.get("max_date")
            if min_date:
                min_dt = datetime.strptime(min_date, "%Y-%m-%d")
                if parsed < min_dt:
                    errors.append(
                        f"Field '{field['key']}': datetime {value} is before min_date ({min_date})"
                    )
            if max_date:
                max_dt = datetime.strptime(max_date, "%Y-%m-%d")
                if parsed > max_dt:
                    errors.append(
                        f"Field '{field['key']}': datetime {value} is after max_date ({max_date})"
                    )
            return
        except ValueError:
            continue
    errors.append(f"Field '{field['key']}': invalid datetime format, expected ISO 8601")


def _validate_json_value(field: dict, errors: list[str]) -> None:
    import json as _json

    value = field.get("value")
    if value is None:
        return
    if isinstance(value, str):
        try:
            parsed = _json.loads(value)
            value = parsed
        except _json.JSONDecodeError:
            errors.append(f"Field '{field['key']}': invalid JSON string")
            return
    schema = field.get("schema") or field.get("schema_")
    if schema and isinstance(value, dict):
        for req_key in schema.get("required", []):
            if req_key not in value:
                errors.append(
                    f"Field '{field['key']}': missing required JSON key '{req_key}'"
                )


_VALUE_VALIDATORS = {
    "text": _validate_text_value,
    "textarea": _validate_text_value,
    "richtext": _validate_text_value,
    "number": _validate_number_value,
    "select": _validate_select_value,
    "multi_select": _validate_multi_select_value,
    "boolean": _validate_boolean_value,
    "date": _validate_date_value,
    "datetime": _validate_datetime_value,
    "url": _validate_url_value,
    "email": _validate_email_value,
    "color": _validate_color_value,
    "image": _validate_image_value,
    "gallery": _validate_gallery_value,
    "json": _validate_json_value,
}


def validate_field(field: dict[str, Any], check_required: bool = True) -> list[str]:
    errors: list[str] = []
    key = field.get("key")
    if not key or not isinstance(key, str):
        errors.append("Field missing non-empty 'key'")
        return errors

    field_type = field.get("type")
    if not field_type:
        errors.append(f"Field '{key}' missing 'type'")
        return errors
    if field_type not in FIELD_TYPES:
        errors.append(f"Field '{key}' has invalid type '{field_type}'")
        return errors

    if check_required:
        required = field.get("required", False)
        value = field.get("value")
        if required and value is None:
            errors.append(f"Field '{key}' is required but value is null")

    validator = _VALUE_VALIDATORS.get(field_type)
    if validator:
        validator(field, errors)

    return errors


def validate_fields(
    fields: list[dict[str, Any]], check_required: bool = True
) -> list[str]:
    errors: list[str] = []
    seen_keys: set = set()
    for field in fields:
        key = field.get("key", "")
        if key in seen_keys:
            errors.append(f"Duplicate field key '{key}'")
        seen_keys.add(key)
        errors.extend(validate_field(field, check_required=check_required))
    return errors


def validate_groups(groups: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_keys: set = set()
    for group in groups:
        key = group.get("key")
        if not key or not isinstance(key, str):
            errors.append("Group missing non-empty 'key'")
            continue
        if key in seen_keys:
            errors.append(f"Duplicate group key '{key}'")
        seen_keys.add(key)

        group_fields = group.get("fields", [])
        if not group_fields:
            errors.append(f"Group '{key}' has no fields")
            continue

        field_keys = {f.get("key") for f in group_fields if f.get("key")}
        errors.extend(validate_fields(group_fields, check_required=False))

        entries = group.get("entries", [])
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"Group '{key}' entry {i} must be an object")
                continue
            entry_keys = set(entry.keys())
            unexpected = entry_keys - field_keys
            if unexpected:
                errors.append(
                    f"Group '{key}' entry {i} has keys {unexpected} not in field definitions"
                )

        min_entries = group.get("min_entries")
        max_entries = group.get("max_entries")
        if min_entries is not None and len(entries) < min_entries:
            errors.append(
                f"Group '{key}' has {len(entries)} entries, minimum is {min_entries}"
            )
        if max_entries is not None and len(entries) > max_entries:
            errors.append(
                f"Group '{key}' has {len(entries)} entries, maximum is {max_entries}"
            )

    return errors
