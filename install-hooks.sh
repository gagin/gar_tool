#!/bin/bash

# Copy the pre-commit hook
cp pre-commit .git/hooks/pre-commit

# Make it executable
chmod +x .git/hooks/pre-commit

echo "Pre-commit hook installed."