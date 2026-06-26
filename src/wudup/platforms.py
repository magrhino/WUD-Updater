"""Container platform parsing helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


_PLATFORM_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$", re.ASCII)


@dataclass(frozen=True)
class ImagePlatform:
    os: str
    architecture: str
    variant: str = ""

    @property
    def value(self) -> str:
        if self.variant:
            return f"{self.os}/{self.architecture}/{self.variant}"
        return f"{self.os}/{self.architecture}"


def parse_platform(value: str) -> ImagePlatform | None:
    parts = tuple(part.strip() for part in value.strip().split("/"))
    if len(parts) not in {2, 3}:
        return None
    if len(parts) == 3 and not parts[2]:
        return None
    return platform_from_parts(
        parts[0],
        parts[1],
        parts[2] if len(parts) == 3 else "",
    )


def platform_from_parts(
    os_value: str,
    architecture: str,
    variant: str = "",
) -> ImagePlatform | None:
    os_value = os_value.strip().lower()
    architecture = architecture.strip().lower()
    variant = variant.strip().lower()
    if not _valid_platform_component(os_value):
        return None
    if not _valid_platform_component(architecture):
        return None
    if variant and not _valid_platform_component(variant):
        return None
    if os_value == "unknown" or architecture == "unknown":
        return None
    return ImagePlatform(
        os=os_value,
        architecture=architecture,
        variant=variant,
    )


def platform_value(platform: ImagePlatform | None) -> str:
    return platform.value if platform is not None else ""


def _valid_platform_component(value: str) -> bool:
    return bool(value and _PLATFORM_COMPONENT_RE.fullmatch(value))
