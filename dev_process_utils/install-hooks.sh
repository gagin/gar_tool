#!/bin/bash

# Get the directory of the script
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Get the current working directory
CURRENT_DIR="$(pwd)"

# Get the parent directory of the script's directory
MAIN_DIR="$(dirname "$SCRIPT_DIR")"

# Check if the current directory is the main directory
if [ "$CURRENT_DIR" != "$MAIN_DIR" ]; then
  echo "Error: This script must be run from the main directory."
  echo "Please navigate to the main directory and run the script again."
  echo "Run command: cd $MAIN_DIR && sh dev_process_utils/install-hooks.sh"
  exit 1
fi

# Copy the pre-commit hook
cp "$SCRIPT_DIR/pre-commit" .git/hooks/pre-commit

# Make it executable
chmod +x .git/hooks/pre-commit

echo "Pre-commit hook installed."