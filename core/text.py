"""Unicode tokens shared by offline research and supervisor ranking."""
import unicodedata


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in unicodedata.normalize('NFC', text).casefold():
        category = unicodedata.category(char)
        if category[0] in {'L', 'N'} or ((category[0] == 'M' or char in {'\u200c','\u200d'}) and current):
            current.append(char)
        elif current:
            tokens.append(''.join(current))
            current.clear()
    if current:
        tokens.append(''.join(current))
    return tokens


def safe_multiline(text: str, maximum: int | None = None) -> str:
    """Render line breaks and script joiners, never terminal/bidi controls."""
    value=text if maximum is None else text[:maximum]
    return ''.join(char if char in {'\n','\t','\u200c','\u200d'} or not unicodedata.category(char).startswith('C') else ' '
                   for char in value)
