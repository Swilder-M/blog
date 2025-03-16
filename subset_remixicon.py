#!/usr/bin/env python3
"""
This script creates a subset of RemixIcon font with only the needed icons.
"""
import os
import subprocess
from fontTools.ttLib import TTFont

# Ensure the output directory exists
os.makedirs('static/fonts', exist_ok=True)

# Define the unicode ranges for the specific icons we need
# These are the unicode characters that correspond to each icon
icons_unicodes = [
    0xef3e,  # menu-line
    0xf181,  # stack-line
    0xea78,  # arrow-up-s-line
    0xef18,  # map-pin-time-line
    0xf09e,  # rss-fill
    0xedca,  # github-fill
    0xf3e6,  # twitter-x-fill
]

# Convert to strings that fonttools can use
unicode_strings = [f'U+{hex(code)[2:].upper()}' for code in icons_unicodes]
unicode_arg = ','.join(unicode_strings)

# Use fonttools to subset the font
input_font = 'static/fonts/remixicon.ttf'
output_font = 'static/fonts/custom-remixicon.woff2'

try:
    # Check if the input font exists
    if not os.path.exists(input_font):
        print(f"Error: {input_font} not found.")
        exit(1)
        
    # Create the subset font
    cmd = f"pyftsubset {input_font} --unicodes={unicode_arg} --flavor=woff2 --output-file={output_font}"
    print(f"Running: {cmd}")
    subprocess.run(cmd, shell=True, check=True)
    
    # Calculate file size reduction
    original_size = os.path.getsize('static/fonts/remixicon.woff2')
    new_size = os.path.getsize(output_font)
    reduction = (1 - new_size / original_size) * 100
    
    print(f"\nSuccess! Font file size reduced from {original_size:,} bytes to {new_size:,} bytes")
    print(f"That's a {reduction:.1f}% reduction!")
    print(f"\nNow use the custom-remixicon.css file with this new font.")

except Exception as e:
    print(f"Error: {str(e)}")
    print("\nManual alternative: Go to remixicon.com and create a custom webfont with only the icons you need.") 