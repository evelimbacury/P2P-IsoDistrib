"""
Wrapper para demonstração: sobe o peer com um comando automático no primeiro prompt.

Para comandos 'download', aguarda 5 s antes de disparar (dá tempo aos publicadores
registrarem no tracker) e retentar automaticamente se não encontrar peers.

Uso interno pelo demo.bat:
    python scripts/demo_peer.py --port 6000 --auto publish shared_files/test.iso
    python scripts/demo_peer.py --port 6002 --auto download test.iso
"""
import builtins
import os
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Extrai "--auto <comando>" do argv antes de repassar pro client
_auto_cmd = None
if "--auto" in sys.argv:
    idx = sys.argv.index("--auto")
    _auto_cmd = " ".join(sys.argv[idx + 1:])
    sys.argv = sys.argv[:idx]

_original_input = builtins.input
_fired = False
_retries = 0
_MAX_RETRIES = 10


def _patched_input(prompt=""):
    global _fired, _retries
    sys.stdout.write(prompt)
    sys.stdout.flush()

    if not (_auto_cmd and "peer>" in prompt):
        return _original_input()

    is_download = _auto_cmd.startswith("download ")

    if not _fired:
        _fired = True
        # Comandos de download aguardam mais para garantir que os publicadores
        # já computaram o SHA256 e registraram no tracker.
        delay = 5.0 if is_download else 0.3
        time.sleep(delay)
        print(_auto_cmd)
        return _auto_cmd

    if is_download and _retries < _MAX_RETRIES:
        # Verifica se o arquivo já foi baixado com sucesso
        filename = _auto_cmd.split(" ", 1)[1]
        dest = os.path.join(PROJECT_ROOT, "downloads", filename)
        if os.path.exists(dest):
            # Download concluído — deixa o peer em modo interativo
            return _original_input()

        _retries += 1
        print(f"[Demo] Nenhum peer disponivel. Tentativa {_retries}/{_MAX_RETRIES} em 3s...")
        time.sleep(3)
        print(_auto_cmd)
        return _auto_cmd

    return _original_input()


if _auto_cmd:
    builtins.input = _patched_input

from src.peer.client import main
sys.exit(main())
