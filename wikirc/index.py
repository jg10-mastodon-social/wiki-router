from dataclasses import dataclass
from pathlib import Path


class LabelIndexError(Exception):
    """Raised when a label index cannot be parsed."""


@dataclass(frozen=True)
class LabelEntry:
    ref: str
    labels: tuple[str, ...]
    comment: str | None


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    line: int


_NAME_STOP = set(' \t\r\n;,.<>"#')
_LABEL = "label"
_COMMENT = "comment"


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    line = 1
    size = len(text)

    while i < size:
        char = text[i]

        if char in " \t\r":
            i += 1
        elif char == "\n":
            line += 1
            i += 1
        elif char == "#":
            while i < size and text[i] != "\n":
                i += 1
        elif char == "<":
            start_line = line
            end = text.find(">", i + 1)
            if end == -1:
                raise LabelIndexError(
                    f"line {start_line}: unterminated IRI reference"
                )
            value = text[i + 1 : end]
            line += value.count("\n")
            tokens.append(_Token("iri", value, start_line))
            i = end + 1
        elif char == '"':
            start_line = line
            value, i, line = _read_string(text, i, line)
            tokens.append(_Token("string", value, start_line))
        elif char in ";,.":
            tokens.append(_Token(char, char, line))
            i += 1
        elif char == "@":
            start = i
            while i < size and text[i] not in _NAME_STOP:
                i += 1
            tokens.append(_Token("directive", text[start:i], line))
        else:
            start = i
            while i < size and text[i] not in _NAME_STOP:
                i += 1
            if start == i:
                raise LabelIndexError(f"line {line}: unexpected character {char!r}")
            tokens.append(_Token("name", text[start:i], line))

    return tokens


def _read_string(text: str, start: int, line: int) -> tuple[str, int, int]:
    start_line = line
    chars: list[str] = []
    i = start + 1
    size = len(text)

    while True:
        if i >= size:
            raise LabelIndexError(
                f"line {start_line}: unterminated string literal"
            )
        char = text[i]
        if char == "\\":
            if i + 1 >= size:
                raise LabelIndexError(
                    f"line {start_line}: unterminated string literal"
                )
            escaped = text[i + 1]
            if escaped in ('"', "\\"):
                chars.append(escaped)
            else:
                chars.append("\\" + escaped)
            if escaped == "\n":
                line += 1
            i += 2
        elif char == '"':
            return "".join(chars), i + 1, line
        else:
            if char == "\n":
                line += 1
            chars.append(char)
            i += 1


def _classify(predicate: _Token) -> str | None:
    if predicate.value.endswith("#" + _LABEL):
        return _LABEL
    if predicate.value.endswith("#" + _COMMENT):
        return _COMMENT
    return None


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.prefixes: dict[str, str] = {}

    def peek(self) -> _Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def take(self, kind: str, expected: str) -> _Token:
        token = self.peek()
        if token is None:
            raise LabelIndexError(f"unexpected end of file: expected {expected}")
        if token.kind != kind:
            raise LabelIndexError(
                f"line {token.line}: expected {expected}, found {token.value!r}"
            )
        self.pos += 1
        return token

    def parse(self) -> list[LabelEntry]:
        entries: list[LabelEntry] = []
        while self.peek() is not None:
            token = self.peek()
            if token.kind == "directive" and token.value == "@prefix":
                self._prefix()
            elif token.kind == "directive":
                raise LabelIndexError(
                    f"line {token.line}: unsupported directive {token.value!r}"
                )
            else:
                entries.extend(self._statement())
        return entries

    def _prefix(self) -> None:
        self.take("directive", "the @prefix keyword")
        name = self.take("name", "a prefix name")
        if not name.value.endswith(":"):
            raise LabelIndexError(
                f"line {name.line}: expected a prefix name ending in ':', "
                f"found {name.value!r}"
            )
        namespace = self.take("iri", "a prefix IRI")
        self.take(".", "'.' after the prefix declaration")
        self.prefixes[name.value[:-1]] = namespace.value

    def _predicate(self) -> str | None:
        token = self.peek()
        if token is None:
            raise LabelIndexError("unexpected end of file: expected a predicate")
        if token.kind == "iri":
            self.pos += 1
            return _classify(token)
        if token.kind == "name":
            self.pos += 1
            prefix, sep, local = token.value.partition(":")
            if not sep or prefix not in self.prefixes:
                raise LabelIndexError(
                    f"line {token.line}: undefined prefix in predicate "
                    f"{token.value!r}"
                )
            return _classify(_Token("iri", self.prefixes[prefix] + local, token.line))
        raise LabelIndexError(
            f"line {token.line}: expected a predicate, found {token.value!r}"
        )

    def _objects(self) -> list[str]:
        values = [self.take("string", "a string literal").value]
        while self.peek() is not None and self.peek().kind == ",":
            self.pos += 1
            values.append(self.take("string", "a string literal").value)
        return values

    def _statement(self) -> list[LabelEntry]:
        subject = self.take("iri", "a subject IRI")
        labels: list[str] = []
        comments: list[str] = []

        while True:
            kind = self._predicate()
            values = self._objects()
            if kind == _LABEL:
                labels.extend(values)
            elif kind == _COMMENT:
                comments.extend(values)

            token = self.peek()
            if token is None:
                raise LabelIndexError(
                    "unexpected end of file: expected '.' to end the statement "
                    f"for <{subject.value}>"
                )
            if token.kind == ".":
                self.pos += 1
                break
            if token.kind == ";":
                self.pos += 1
                following = self.peek()
                if following is not None and following.kind == ".":
                    self.pos += 1
                    break
                continue
            raise LabelIndexError(
                f"line {token.line}: expected ';' or '.' in the statement for "
                f"<{subject.value}>, found {token.value!r}"
            )

        if not labels and not comments:
            return []
        return [
            LabelEntry(
                ref=subject.value,
                labels=tuple(labels),
                comment=comments[0] if comments else None,
            )
        ]


def parse_label_index(text: str) -> list[LabelEntry]:
    return _Parser(_tokenize(text)).parse()


def load_label_index(path: Path) -> list[LabelEntry]:
    return parse_label_index(Path(path).read_text(encoding="utf-8"))
