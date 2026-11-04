"""Keep displayed lyrics separate from pronunciation used for alignment."""
import re
import unicodedata

_TIMESTAMP = re.compile(r"\[\d+:\d+(?:[.:]\d+)?\]")
_METADATA = re.compile(r"^\[(?:ar|al|ti|by|offset|re|ve|length):.*\]$", re.I)


def lyric_text(text: str) -> list[str]:
    if not isinstance(text, str):
        raise ValueError("歌詞はテキストで指定してください")
    return [clean for line in text.replace("\ufeff", "").splitlines()
            if not _METADATA.match(line.strip())
            if (clean := _TIMESTAMP.sub("", line).strip())]


def canonical(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    return "".join(c for c in text if unicodedata.category(c)[0] in "LN")


class Reader:
    def __init__(self):
        from sudachipy import dictionary, tokenizer
        self.tokenizer = dictionary.Dictionary(dict="core").create()
        self.mode = tokenizer.Tokenizer.SplitMode.A

    def reading(self, text: str) -> tuple[str, list[dict]]:
        tokens = [{"surface": token.surface(), "reading": token.reading_form(),
                   "begin": token.begin(), "end": token.end()}
                  for token in self.tokenizer.tokenize(text, self.mode)]
        return "".join(token["reading"] for token in tokens), tokens


def prepare_lines(lines: list[dict], reader: Reader) -> list[dict]:
    if not isinstance(lines, list) or not lines or len(lines) > 2000:
        raise ValueError("歌詞は1〜2000行で指定してください")
    prepared = []
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("text"), str):
            raise ValueError("歌詞の形式が不正です")
        text = line["text"].strip()
        if not text or any(c in text for c in "\r\n\0") or len(text) > 1000:
            raise ValueError("各歌詞は空でない1行（1000文字以内）にしてください")
        reading, tokens = reader.reading(text)
        automatic = reading
        override = line.get("reading", "")
        if not isinstance(override, str):
            raise ValueError("読みはテキストで指定してください")
        reading = override.strip() or reading
        normalized = canonical(reading)
        if not normalized:
            raise ValueError(f"読みを生成できません: {text}")
        prepared.append({"text": text, "reading": reading, "normalized": normalized, "tokens": tokens,
                         "alignment_text": override.strip() if override.strip() and canonical(override) != canonical(automatic) else text})
    return prepared
