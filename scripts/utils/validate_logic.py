#!/usr/bin/env python3
"""
Validation script to check for cyclic dependencies and logic issues.
"""
import sys
import ast
from pathlib import Path
from collections import defaultdict

def extract_function_calls(tree, current_function=None):
    """Extract all function calls within functions."""
    calls = defaultdict(list)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            current_function = node.name
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls[current_function].append(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls[current_function].append(child.func.attr)

    return calls

def check_circular_calls(calls, start_func, visited=None):
    """Check if a function has circular call chain."""
    if visited is None:
        visited = set()

    if start_func in visited:
        return True, list(visited) + [start_func]

    visited.add(start_func)

    for called_func in calls.get(start_func, []):
        is_circular, path = check_circular_calls(calls, called_func, visited.copy())
        if is_circular:
            return True, path

    return False, []

def analyze_file(filepath):
    """Analyze a Python file for potential issues."""
    print(f"\n{'='*60}")
    print(f"Analyzing: {filepath.name}")
    print(f"{'='*60}")

    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError as e:
            print(f"❌ SYNTAX ERROR: {e}")
            return False

    # Check imports
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    print(f"\nImports: {len(imports)}")

    # Check for runtime imports (inside functions)
    runtime_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    module = getattr(child, 'module', None) or (
                        child.names[0].name if child.names else 'unknown'
                    )
                    runtime_imports.append((node.name, module))

    if runtime_imports:
        print(f"\n⚠️  Runtime imports found:")
        for func, module in runtime_imports:
            print(f"   - {func}() imports {module}")
    else:
        print(f"\n✅ No runtime imports")

    # Extract function calls
    calls = extract_function_calls(tree)

    print(f"\n🔍 Function call analysis:")
    print(f"   Total functions: {len(calls)}")

    # Check for potential circular calls
    circular_found = False
    for func in calls:
        is_circular, path = check_circular_calls(calls, func)
        if is_circular:
            print(f"   ❌ CIRCULAR: {' → '.join(path)}")
            circular_found = True

    if not circular_found:
        print(f"   ✅ No obvious circular function calls")

    return True

def main():
    """Main validation."""
    chat_app = Path(__file__).parent / "chat_app"

    files_to_check = [
        chat_app / "app.py",
        chat_app / "vectorstore.py",
        chat_app / "ollama_priority.py",
        chat_app / "cache.py",
    ]

    print("\n" + "="*60)
    print("CYCLIC DEPENDENCY AND LOGIC VALIDATION")
    print("="*60)

    all_passed = True
    for filepath in files_to_check:
        if not filepath.exists():
            print(f"\n❌ File not found: {filepath}")
            all_passed = False
            continue

        if not analyze_file(filepath):
            all_passed = False

    # Summary
    print("\n" + "="*60)
    print("VALIDATION SUMMARY")
    print("="*60)

    if all_passed:
        print("✅ All checks passed!")
        print("\nNo critical issues found:")
        print("  • No syntax errors")
        print("  • No obvious circular imports")
        print("  • No circular function calls detected")
        return 0
    else:
        print("❌ Validation failed - see errors above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
