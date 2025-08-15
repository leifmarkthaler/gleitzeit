#!/usr/bin/env python3
"""
Read and process a text file
"""

import os

# Get file path from context
file_path = context.get('file_path', '')

if not file_path:
    result = {
        'error': 'No file path provided',
        'content': None
    }
else:
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Basic statistics
        lines = content.split('\n')
        words = content.split()
        
        result = {
            'content': content,
            'file_path': file_path,
            'file_size': os.path.getsize(file_path),
            'line_count': len(lines),
            'word_count': len(words),
            'char_count': len(content),
            'first_line': lines[0] if lines else '',
            'success': True
        }
        
        print(f"Successfully read file: {file_path}")
        print(f"  Lines: {result['line_count']}")
        print(f"  Words: {result['word_count']}")
        print(f"  Characters: {result['char_count']}")
        
    except FileNotFoundError:
        result = {
            'error': f'File not found: {file_path}',
            'content': None,
            'success': False
        }
        print(f"Error: File not found - {file_path}")
        
    except Exception as e:
        result = {
            'error': f'Error reading file: {str(e)}',
            'content': None,
            'success': False
        }
        print(f"Error reading file: {e}")