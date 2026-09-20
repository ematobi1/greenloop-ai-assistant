import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_templates"
NAME_PATTERN = re.compile(r"^[a-z][a-z_]*$")
VERSION_PATTERN = re.compile(r"^v[0-9]+$")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class PromptManager:
    def __init__(self, active_version: str = "v1", directory: Path = PROMPT_DIR):
        if not VERSION_PATTERN.match(active_version):
            raise ValueError("prompt version must look like v1")
        self._directory = directory
        self.active_version = active_version

    def get(self, name: str, version: str | None = None) -> Prompt:
        version = version or self.active_version
        if not NAME_PATTERN.match(name) or not VERSION_PATTERN.match(version):
            raise ValueError("invalid prompt name or version")
        path = self._directory / f"{name}.{version}.txt"
        if not path.is_file():
            raise ValueError(f"prompt {name} {version} does not exist")
        return Prompt(name, version, path.read_text(encoding="utf-8").strip())

    def versions(self, name: str) -> list[str]:
        if not NAME_PATTERN.match(name):
            raise ValueError("invalid prompt name")
        found = [path.name.split(".")[1] for path in self._directory.glob(f"{name}.v*.txt")]
        return sorted(found, key=lambda version: int(version[1:]))

    def render(self, name: str, **values: str) -> str:
        return Template(self.get(name).text).substitute(values)

    def chat_system(self, preferences: str | None = None) -> str:
        system = self.get("chat_system").text
        if not preferences:
            return system
        return f"{system}\n\n{self.render('preferences', preferences=preferences)}"
