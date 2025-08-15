#!/usr/bin/env python3
"""
Process vision description to extract keywords and metadata
"""

import re

# Get the description from context
description = context.get('description', '')

# Extract color words
color_pattern = r'\b(red|blue|green|yellow|orange|purple|pink|black|white|gray|brown)\b'
colors = re.findall(color_pattern, description.lower())

# Extract shape words
shape_pattern = r'\b(square|rectangle|circle|triangle|line|dot|pattern|grid)\b'
shapes = re.findall(shape_pattern, description.lower())

# Count words
words = description.split()
word_count = len(words)

# Create result
result = {
    'colors_found': list(set(colors)),  # unique colors
    'shapes_found': list(set(shapes)),  # unique shapes
    'word_count': word_count,
    'keywords': list(set(colors + shapes))[:5]  # top 5 keywords
}

print(f"Found {len(result['colors_found'])} colors: {', '.join(result['colors_found'])}")
print(f"Found {len(result['shapes_found'])} shapes: {', '.join(result['shapes_found'])}")
print(f"Description has {word_count} words")