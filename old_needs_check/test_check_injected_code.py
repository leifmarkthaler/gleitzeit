#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.easy import t

# Create a simple chain
generate = t("generate", "python/v1:execute").with_(code="""
result = {'number': 42}
""")

process = t("process", "python/v1:execute").input(generate).with_(code="""
print(f'Type of generate: {type(generate)}')
print(f'Value of generate: {generate}')
result = generate.get('number', 0) * 2
""")

# Print the injected code
task_dict = process.to_dict()
print("=" * 80)
print("INJECTED CODE:")
print("=" * 80)
print(task_dict['params']['code'])
print("=" * 80)
