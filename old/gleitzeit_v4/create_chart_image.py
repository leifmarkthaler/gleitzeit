#!/usr/bin/env python3
"""
Create a simple chart image for vision workflows
"""

from PIL import Image, ImageDraw
import os

# Create a simple bar chart image
width, height = 400, 300
img = Image.new('RGB', (width, height), 'white')
draw = ImageDraw.Draw(img)

# Draw title area
draw.rectangle([0, 0, width, 30], fill='#333333')
draw.text((width//2 - 50, 8), "Sales Chart 2024", fill='white')

# Draw axes
draw.line([40, 250, 380, 250], fill='black', width=2)  # X-axis
draw.line([40, 40, 40, 250], fill='black', width=2)    # Y-axis

# Draw bars
bar_data = [
    ('Q1', 120, '#FF6B6B'),
    ('Q2', 180, '#4ECDC4'),
    ('Q3', 150, '#45B7D1'),
    ('Q4', 200, '#96CEB4')
]

bar_width = 60
spacing = 20
x_start = 60

for i, (label, value, color) in enumerate(bar_data):
    x = x_start + i * (bar_width + spacing)
    bar_height = int((value / 200) * 180)  # Scale to chart height
    y = 250 - bar_height
    
    # Draw bar
    draw.rectangle([x, y, x + bar_width, 250], fill=color)
    
    # Draw label
    draw.text((x + bar_width//2 - 10, 255), label, fill='black')
    
    # Draw value on top of bar
    draw.text((x + bar_width//2 - 15, y - 20), str(value), fill='black')

# Add Y-axis labels
for i in range(0, 201, 50):
    y_pos = 250 - int((i / 200) * 180)
    draw.text((10, y_pos - 5), str(i), fill='black')

# Save the image
os.makedirs('examples/images', exist_ok=True)
img.save('examples/images/sales_chart.png')
print("Created chart image: examples/images/sales_chart.png")