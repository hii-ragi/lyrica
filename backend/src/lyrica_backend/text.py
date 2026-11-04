"""Keep source lyrics and offsets separate from pronunciation used for alignment."""
import re
import unicodedata

_TIMESTAMP = re.compile(r"\[\d+:\d+(?:[.:]\d+)?\]")
_METADATA = re.compile(r"^\[(?:ar|al|ti|by|offset|re|ve|length):.*\]$", re.I)
_KANA = "ぁ-ゖァ-ヺーゝゞヽヾ"
_RUBY = re.compile(
    r"(?P<base>[々〆〇\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]+)"
    rf"(?:\((?P<half>[{_KANA}]+)\)|（(?P<full>[{_KANA}]+)）)"
)
_LATIN = re.compile(r"[a-zA-ZＡ-Ｚａ-ｚ]+")
_JAPANESE = re.compile(r"[ぁ-ゖァ-ヺ々〆〇\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]")


def ruby_text(text: str) -> str:
    """Replace only kanji + kana annotations; ordinary parentheses remain."""
    return _RUBY.sub(lambda match: match["half"] or match["full"], text)


def lyric_text(text: str) -> list[str]:
    if not isinstance(text, str):
        raise ValueError("歌詞はテキストで指定してください")
    return [clean for line in text.removeprefix("\ufeff").splitlines()
            if not _METADATA.match(line.strip())
            if (clean := _TIMESTAMP.sub("", line)).strip()]


def canonical(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    return "".join(c for c in text if unicodedata.category(c)[0] in "LN")


class Reader:
    def __init__(self):
        from sudachipy import dictionary, tokenizer
        self.tokenizer = dictionary.Dictionary(dict="core").create()
        self.mode = tokenizer.Tokenizer.SplitMode.A

    def _plain_tokens(self, text, offset):
        # Keep Latin spans intact even when Sudachi knows a Japanese loanword reading.
        def japanese(chunk, begin):
            return [{"surface": token.surface(),
                     "reading": token.reading_form() if _JAPANESE.search(token.surface()) else token.surface(),
                     "begin": begin + token.begin(), "end": begin + token.end()}
                    for token in self.tokenizer.tokenize(chunk, self.mode)]
        tokens, end = [], 0
        for match in _LATIN.finditer(text):
            tokens.extend(japanese(text[end:match.start()], offset + end))
            tokens.append({"surface": match[0], "reading": match[0],
                           "begin": offset + match.start(), "end": offset + match.end()})
            end = match.end()
        tokens.extend(japanese(text[end:], offset + end))
        return tokens

    def reading(self, text: str) -> tuple[str, list[dict]]:
        tokens, end = [], 0
        for match in _RUBY.finditer(text):
            tokens.extend(self._plain_tokens(text[end:match.start()], end))
            tokens.append({"surface": match[0], "reading": match["half"] or match["full"],
                           "begin": match.start(), "end": match.end(), "explicit": True})
            end = match.end()
        tokens.extend(self._plain_tokens(text[end:], end))
        return "".join(token["reading"] for token in tokens), tokens


def prepare_lines(lines: list[dict], reader: Reader) -> list[dict]:
    if not isinstance(lines, list) or not lines or len(lines) > 2000:
        raise ValueError("歌詞は1〜2000行で指定してください")
    prepared = []
    for index, line in enumerate(lines, 1):
        if not isinstance(line, dict) or not isinstance(line.get("text"), str):
            raise ValueError("歌詞の形式が不正です")
        text = line["text"]
        if not text.strip() or any(c in text for c in "\r\n\0") or len(text) > 1000:
            raise ValueError("各歌詞は空でない1行（1000文字以内）にしてください")
        source_line = line.get("source_line", index)
        if isinstance(source_line, bool) or not isinstance(source_line, int) or source_line < 1:
            raise ValueError("元の行番号は正の整数で指定してください")
        automatic, tokens = reader.reading(text)
        override = line.get("reading", "")
        if not isinstance(override, str):
            raise ValueError("読みはテキストで指定してください")
        reading = override.strip() or automatic
        normalized = canonical(reading)
        if not normalized:
            raise ValueError(f"読みを生成できません: {text}")
        alignment_text = ruby_text(text)
        if override.strip() and canonical(override) != canonical(automatic):
            alignment_text = override.strip()
        prepared.append({"text": text, "source_line": source_line, "reading": reading,
                         "normalized": normalized, "tokens": tokens, "alignment_text": alignment_text})
    return prepared
