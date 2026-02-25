import re
from dataclasses import dataclass


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


@dataclass(frozen=True)
class EmailAddress:
    value: str

    def __post_init__(self) -> None:
        if not self.value or not _EMAIL_RE.match(self.value.strip()):
            raise ValueError(f"Invalid email address: {self.value!r}")
        # Normalize to lowercase
        object.__setattr__(self, "value", self.value.strip().lower())

    @property
    def local_part(self) -> str:
        return self.value.split("@")[0]

    @property
    def domain(self) -> str:
        return self.value.split("@")[1]

    def __str__(self) -> str:
        return self.value
