#!/usr/bin/env python3
"""
Count words and analyze text statistics.
"""

text = "I love working with modern workflow systems! They make automation so much easier."
words = text.split()
word_count = len(words)
char_count = len(text)

result = {
    "text": text,
    "word_count": word_count,
    "character_count": char_count,
    "average_word_length": round(char_count / word_count, 2) if word_count > 0 else 0
}

print(f"Text analysis: {word_count} words, {char_count} characters")