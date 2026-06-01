#!/usr/bin/env python3
"""
tree_code.py - Muestra estructura de árbol + contenido de archivos
Uso: python tree_code.py <ruta> <extensión> <max_profundidad>
Ej:  python tree_code.py backend/app/models py 2
"""
import os, sys
from pathlib import Path

def print_tree_with_code(root_path, extension="py", max_depth=3, prefix="", is_last=True, current_depth=0):
    if current_depth > max_depth:
        return
    
    try:
        items = sorted([p for p in Path(root_path).iterdir() 
                       if p.name not in {'__pycache__', '.git', 'node_modules', '.venv', 'venv'} 
                       and (p.suffix == f".{extension}" or p.is_dir())],
                      key=lambda x: (not x.is_file(), x.name.lower()))
    except PermissionError:
        return
    
    for i, item in enumerate(items):
        connector = "└── " if i == len(items) - 1 else "├── "
        print(f"{prefix}{connector}{item.name}")
        
        if item.is_file():
            # Mostrar contenido con sangría
            try:
                with open(item, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        print(f"{prefix}{'    ' if is_last else '│   '}{line.rstrip()}")
                print(f"{prefix}{'    ' if is_last else '│   '}")
            except Exception as e:
                print(f"{prefix}│   [Error leyendo archivo: {e}]")
        elif item.is_dir():
            new_prefix = prefix + ("    " if is_last else "│   ")
            print_tree_with_code(item, extension, max_depth, new_prefix, 
                               i == len(items) - 1, current_depth + 1)

if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    ext = sys.argv[2] if len(sys.argv) > 2 else "py"
    depth = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    
    print(f"📁 {root} (*.{ext}, profundidad máx: {depth})")
    print("─" * 80)
    print_tree_with_code(root, ext, depth)