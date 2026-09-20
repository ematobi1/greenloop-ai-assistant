import re

from app.ai.providers.base import ChatMessage

RESERVED_TAG = re.compile(r"<(/?)(turn|conversation|untrusted|user_preferences)", re.IGNORECASE)


def escape_markup(text: str) -> str:
    return RESERVED_TAG.sub(lambda match: f"&lt;{match.group(1)}{match.group(2)}", text)


def render_transcript(messages: list[ChatMessage]) -> str:
    turns = "\n".join(
        f'<turn role="{message.role}">\n{escape_markup(message.content)}\n</turn>'
        for message in messages
    )
    return f"<conversation>\n{turns}\n</conversation>"
