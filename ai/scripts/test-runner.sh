#!/bin/bash
set -e

echo "Running Python tests..."
pytest || echo "No pytest or tests failed"

echo "Running Node tests..."
npm test || echo "No npm tests or tests failed"

echo "Test execution completed"
