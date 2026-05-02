"""
Verifica integridade do arquivo baixado comparando SHA256 com o original.
"""
import hashlib
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


original = os.path.join(PROJECT_ROOT, "shared_files", "test.iso")
downloaded = os.path.join(PROJECT_ROOT, "downloads", "test.iso")

if not os.path.exists(original):
    print("[Erro] shared_files/test.iso não encontrado.")
    sys.exit(1)

if not os.path.exists(downloaded):
    print("[Erro] downloads/test.iso não encontrado. O download foi concluído?")
    sys.exit(1)

orig_size = os.path.getsize(original)
down_size = os.path.getsize(downloaded)

print(f"Original:   {orig_size:,} bytes")
print(f"Download:   {down_size:,} bytes")

if orig_size != down_size:
    print("[FALHOU] Tamanhos diferentes!")
    sys.exit(1)

print()
print("Calculando SHA256...")
h_orig = sha256(original)
h_down = sha256(downloaded)

print(f"Original:  {h_orig}")
print(f"Download:  {h_down}")
print()

if h_orig == h_down:
    print("[OK] Arquivos idênticos. Integridade confirmada!")
else:
    print("[FALHOU] SHA256 diverge. Arquivo corrompido!")
    sys.exit(1)
