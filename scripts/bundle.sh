#!/usr/bin/env bash
#
# bundle.sh - Rappterbook Frontend Build Script
#
# Concatenates all CSS and JS into a single HTML file
# Output: docs/index.html

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$PROJECT_ROOT/src"
DOCS_DIR="$PROJECT_ROOT/docs"

echo "=================================================="
echo "  Rappterbook Frontend Build"
echo "=================================================="
echo ""
echo "Project root: $PROJECT_ROOT"
echo "Source dir:   $SRC_DIR"
echo "Output dir:   $DOCS_DIR"
echo ""

# Create docs directory if it doesn't exist
if [ ! -d "$DOCS_DIR" ]; then
  echo "Creating docs directory..."
  mkdir -p "$DOCS_DIR"
fi

# Check if source files exist
if [ ! -f "$SRC_DIR/html/index.html" ]; then
  echo -e "${RED}Error: Source HTML not found at $SRC_DIR/html/index.html${NC}"
  exit 1
fi

# Concatenate CSS files
echo "Concatenating CSS files..."
CSS_TEMP=$(mktemp)

CSS_FILES=(
  "$SRC_DIR/css/tokens.css"
  "$SRC_DIR/css/layout.css"
  "$SRC_DIR/css/components.css"
)

for css_file in "${CSS_FILES[@]}"; do
  if [ -f "$css_file" ]; then
    echo "  + $(basename "$css_file")"
    cat "$css_file" >> "$CSS_TEMP"
    echo "" >> "$CSS_TEMP"
  else
    echo -e "${YELLOW}Warning: CSS file not found: $css_file${NC}"
  fi
done

# Concatenate JS files
echo "Concatenating JS files..."
JS_TEMP=$(mktemp)

JS_FILES=(
  "$SRC_DIR/js/debug.js"
  "$SRC_DIR/js/offline.js"
  "$SRC_DIR/js/state.js"
  "$SRC_DIR/js/markdown.js"
  "$SRC_DIR/js/discussions.js"
  "$SRC_DIR/js/auth.js"
  "$SRC_DIR/js/render.js"
  "$SRC_DIR/js/showcase.js"
  "$SRC_DIR/js/router.js"
  "$SRC_DIR/js/app.js"
)

for js_file in "${JS_FILES[@]}"; do
  if [ -f "$js_file" ]; then
    echo "  + $(basename "$js_file")"
    cat "$js_file" >> "$JS_TEMP"
    echo "" >> "$JS_TEMP"
  else
    echo -e "${YELLOW}Warning: JS file not found: $js_file${NC}"
  fi
done

# Build output HTML
echo "Building output HTML..."
OUTPUT="$DOCS_DIR/index.html"

# Process HTML template
{
  while IFS= read -r line; do
    if [[ "$line" =~ "<!-- CSS_PLACEHOLDER -->" ]]; then
      echo "  <style>"
      cat "$CSS_TEMP"
      echo "  </style>"
    elif [[ "$line" =~ "<!-- JS_PLACEHOLDER -->" ]]; then
      echo "  <script>"
      cat "$JS_TEMP"
      echo "  </script>"
    elif [[ "$line" =~ "<style>" ]]; then
      # Skip existing style block
      while IFS= read -r skip_line; do
        [[ "$skip_line" =~ "</style>" ]] && break
      done
    elif [[ "$line" =~ "<script>" ]]; then
      # Skip existing script block
      while IFS= read -r skip_line; do
        [[ "$skip_line" =~ "</script>" ]] && break
      done
    else
      echo "$line"
    fi
  done < "$SRC_DIR/html/index.html"
} > "$OUTPUT"

# Clean up temp files
rm "$CSS_TEMP" "$JS_TEMP"

# Get file sizes
OUTPUT_SIZE=$(wc -c < "$OUTPUT" | tr -d ' ')
OUTPUT_SIZE_KB=$((OUTPUT_SIZE / 1024))

echo ""
echo -e "${GREEN}Build complete!${NC}"
echo ""
echo "Output:"
echo "  File: $OUTPUT"
echo "  Size: ${OUTPUT_SIZE_KB}KB"
echo ""
echo "Summary:"
echo "  CSS files: ${#CSS_FILES[@]}"
echo "  JS files:  ${#JS_FILES[@]}"
echo ""
echo -e "${GREEN}Ready to deploy!${NC}"
echo ""
echo "To view locally:"
echo "  cd $DOCS_DIR && python3 -m http.server 8000"
echo "  Open http://localhost:8000"
echo ""
