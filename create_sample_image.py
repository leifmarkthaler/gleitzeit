#!/usr/bin/env python3
"""
Create a sample image for testing vision workflows.
"""

from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

def create_sample_image(filename="sample_image.png"):
    """Create a sample image with shapes and text"""
    width, height = 800, 600
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)

    # Draw some shapes
    # Blue rectangle
    draw.rectangle([50, 50, 250, 200], fill='blue', outline='black', width=3)
    draw.text((100, 120), "BLUE BOX", fill='white')

    # Red circle
    draw.ellipse([300, 100, 500, 300], fill='red', outline='black', width=3)
    draw.text((350, 190), "RED CIRCLE", fill='white')

    # Green triangle
    triangle = [(600, 250), (700, 100), (750, 250)]
    draw.polygon(triangle, fill='green', outline='black', width=3)
    draw.text((650, 180), "GREEN", fill='white')

    # Yellow star (simplified)
    star_points = [
        (150, 350), (175, 425), (100, 375),
        (200, 375), (125, 425)
    ]
    draw.polygon(star_points, fill='yellow', outline='black', width=2)

    # Add text at bottom
    draw.text((50, 500), "Sample Vision Test Image", fill='black')
    draw.text((50, 530), f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", fill='gray')

    # Draw a simple chart
    draw.rectangle([550, 350, 750, 550], outline='black', width=2)
    bars = [
        (570, 480, 610, 530, 'orange', '25'),
        (620, 430, 660, 530, 'purple', '50'),
        (670, 380, 710, 530, 'cyan', '75')
    ]
    for x1, y1, x2, y2, color, label in bars:
        draw.rectangle([x1, y1, x2, y2], fill=color)
        draw.text((x1+5, y2+5), label, fill='black')

    draw.text((600, 355), "BAR CHART", fill='black')

    # Save image
    image.save(filename)
    print(f"Created sample image: {filename}")
    return filename

if __name__ == "__main__":
    try:
        create_sample_image()
    except ImportError:
        print("Installing Pillow...")
        import subprocess
        subprocess.check_call(['pip', 'install', 'Pillow'])
        create_sample_image()