"""
Demonstra a barra de progresso do download paralelo em tempo real.

Cria um arquivo de 500 MB (zeros, geração rápida), sobe 2 servidores de upload
na mesma máquina e executa download_file_parallel para mostrar a barra ao vivo.

Uso:
    .venv/bin/python scripts/demo_progress.py
"""
import hashlib
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.peer.file_manager import download_file_parallel, start_upload_server
from src.common.protocol import CHUNK_SIZE, SHARED_FOLDER, DOWNLOAD_FOLDER

SIZE_MB   = 500
SIZE_B    = SIZE_MB * CHUNK_SIZE       # 500 MB exatos (500 chunks de 1 MB)
FILENAME  = "demo_progress.iso"
SRC_PATH  = os.path.join(SHARED_FOLDER, FILENAME)
DEST_PATH = os.path.join(DOWNLOAD_FOLDER, FILENAME)
PORT1, PORT2 = 7200, 7201

os.makedirs(SHARED_FOLDER,  exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Remove download anterior
if os.path.exists(DEST_PATH):
    os.remove(DEST_PATH)

# Gera arquivo fonte com zeros (rápido)
if not os.path.exists(SRC_PATH) or os.path.getsize(SRC_PATH) != SIZE_B:
    print(f"[Demo] Gerando {SIZE_MB} MB de arquivo de teste (zeros)...")
    block = b"\x00" * (8 * 1024 * 1024)   # bloco de 8 MB para escrita rápida
    with open(SRC_PATH, "wb") as f:
        for _ in range(SIZE_MB // 8):
            f.write(block)
        remaining = SIZE_MB % 8
        if remaining:
            f.write(b"\x00" * (remaining * CHUNK_SIZE))
    print(f"[Demo] {FILENAME} pronto ({SIZE_MB} MB)")

print("[Demo] Calculando SHA256 do arquivo fonte...")
h = hashlib.sha256()
with open(SRC_PATH, "rb") as f:
    for block in iter(lambda: f.read(65536), b""):
        h.update(block)
sha256 = h.hexdigest()
print(f"[Demo] SHA256: {sha256[:24]}...")

total_chunks = SIZE_MB    # 1 chunk por MB

# Sobe 2 servidores de upload independentes
s1 = start_upload_server(PORT1)
s2 = start_upload_server(PORT2)

print(f"\n[Demo] 2 peers locais: :{PORT1} (chunks pares) e :{PORT2} (chunks ímpares)")
print(f"[Demo] {total_chunks} chunks × 1 MB = {SIZE_MB} MB\n")

file_info = {
    "name":   FILENAME,
    "size":   SIZE_B,
    "sha256": sha256,
}
peers = [
    {"ip": "127.0.0.1", "port": PORT1,
     "chunks_available": list(range(0, total_chunks, 2))},   # 0, 2, 4 …
    {"ip": "127.0.0.1", "port": PORT2,
     "chunks_available": list(range(1, total_chunks, 2))},   # 1, 3, 5 …
]

result = download_file_parallel(file_info, peers)

print()
if result:
    size_mb = os.path.getsize(result) / (1024 * 1024)
    print(f"[Demo] ✓ Arquivo salvo: {result}  ({size_mb:.1f} MB)")
else:
    print("[Demo] ✗ Falha no download!")
    sys.exit(1)

s1.close()
s2.close()
