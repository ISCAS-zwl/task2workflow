#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test node integration
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

print("Testing node module imports...")

try:
    from node import NodeFactory, LLMNode, ToolNode, ParamGuardNode, NodeExecutionContext
    print("✓ Node module imports successful")
except Exception as e:
    print(f"✗ Node module import failed: {e}")
    sys.exit(1)

try:
    from src.workflow_types import WorkflowState
    print("✓ WorkflowState import successful")
except Exception as e:
    print(f"✗ WorkflowState import failed: {e}")
    sys.exit(1)

try:
    supported_types = NodeFactory.get_supported_types()
    print(f"✓ NodeFactory supports: {supported_types}")
except Exception as e:
    print(f"✗ NodeFactory test failed: {e}")
    sys.exit(1)

print("\n✓ All basic tests passed!")
print("\nNote: Full integration test requires:")
print("  - pip install -r requirements.txt")
print("  - Properly configured .env file")
print("  - Running: python start_server.py")
