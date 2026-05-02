"""Cria shared_files/test.iso com 500 MB de zeros para a demo."""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET = os.path.join(PROJECT_ROOT, "shared_files", "test.iso")
SIZE = 500 * 1024 * 1024  # 500 MB

os.makedirs(os.path.dirname(TARGET), exist_ok=True)

if os.path.exists(TARGET) and os.path.getsize(TARGET) == SIZE:
    print("[Demo] shared_files/test.iso ja existe (500 MB)")
    sys.exit(0)

print("[Demo] Gerando shared_files/test.iso (500 MB)...")
block = b"\x00" * (1024 * 1024)
with open(TARGET, "wb") as f:
    for _ in range(500):
        f.write(block)
print("[Demo] shared_files/test.iso pronto (500 MB)")
