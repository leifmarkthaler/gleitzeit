#!/usr/bin/env python3
"""
Generate a random prompt for haiku generation.
"""

import random

topics = ['automation', 'efficiency', 'innovation', 'technology']
topic = random.choice(topics)

result = {
    'topic': topic,
    'prompt': f'Write a haiku about {topic}'
}

print(f"Generated prompt: {result['prompt']}")