import re

class PIIRedactor:
    """
    A lightweight, regex-based utility for redacting Personally Identifiable Information (PII).
    It masks sensitive patterns (emails, phone numbers, SSNs, credit cards, IPs) with placeholder tags.
    """
    
    # Regex Patterns for common PII
    PATTERNS = {
        "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "PHONE": r"\b(?:\+?\d{1,3}[-. (]*)?(?:\d{3}[-. )]*)?\d{3}[-. ]*\d{4}(?: *x\d+)?\b",
        "SSN": r"\b(?!000|666)[0-8][0-9]{2}-(?!00)[0-9]{2}-(?!0000)[0-9]{4}\b",
        "CREDIT_CARD": r"\b(?:\d[ -]*?){13,16}\b",
        "IPV4": r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"
    }

    @classmethod
    def redact(cls, text: str) -> str:
        """
        Redacts all configured PII patterns from the input text.
        
        Args:
            text (str): The raw input string containing potential PII.
            
        Returns:
            str: The sanitized string with PII replaced by [TAG] placeholders.
        """
        if not text:
            return text
            
        sanitized_text = text
        
        for pii_type, pattern in cls.PATTERNS.items():
            replacement = f"[{pii_type}]"
            # Apply regex substitution; ignoring case for email/etc if needed
            sanitized_text = re.sub(pattern, replacement, sanitized_text)
            
        return sanitized_text
