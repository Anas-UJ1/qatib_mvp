"""
Tiny shared language-detection helper.
"""

import re

_ARABIC_RE = re.compile(r"[؀-ۿ]")


def is_arabic_text(text: str, threshold: float = 0.3) -> bool:
    """True if Arabic-script characters make up a significant share of the
    text's letters.

    A bare "does any Arabic character appear" check misfires on
    predominantly-English text that merely contains a few Arabic proper
    nouns or parenthetical translations (e.g. "SAMA (مؤسسة النقد العربي
    السعودي)") -- system prompts ask the LLM to answer entirely in one
    language, so the overall letter ratio is a much more reliable signal.
    """
    if not text:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    arabic_count = sum(1 for c in letters if _ARABIC_RE.match(c))
    return (arabic_count / len(letters)) >= threshold
