"""
Configuração global de fixtures para testes.
Gerencia limpeza de estado compartilhado e threads.
"""
import os
import sys
import pytest
import time
import threading
import socket
from src.tracker import tracker
import src.common.protocol as protocol_module
from src.common.protocol import TRACKER_CONNECT_HOST, TRACKER_PORT


@pytest.fixture(autouse=True)
def reset_tracker_state():
    """
    Fixture automática que reseta o estado do tracker antes e depois de cada teste.
    
    Garante:
    - Limpeza de peers e logs de heartbeat
    - Reset do stop_event para que novos trackers possam iniciar
    - Espera por threads ativas de limpeza
    """
    # Setup: Limpa estado anterior
    tracker.peers_dict.clear()
    tracker.heartbeat_log_counter.clear()
    tracker.peer_last_heartbeat_time.clear()
    tracker.active_connections = 0
    with protocol_module._json_recv_lock:
        protocol_module._json_recv_buffers.clear()
    if tracker.stop_event.is_set():
        tracker.stop_event.clear()
    
    yield
    
    # Teardown: Limpa estado após teste
    tracker.stop_event.set()
    tracker.peers_dict.clear()
    tracker.heartbeat_log_counter.clear()
    tracker.peer_last_heartbeat_time.clear()
    tracker.active_connections = 0
    with protocol_module._json_recv_lock:
        protocol_module._json_recv_buffers.clear()
    # Aguarda um pouco para threads finalizarem
    time.sleep(0.1)
    
    # Reset para próximo teste
    tracker.stop_event.clear()


@pytest.fixture(scope="session", autouse=True)
def cleanup_hanging_threads():
    """
    Fixture de sessão que aguarda threads ativas ao final de todos os testes.
    Evita que threads vaze para fora da sessão de testes.
    """
    yield
    
    # Ao final de todos os testes, aguarda threads ativas
    time.sleep(1)
    
    # Força parada de todos os trackers
    tracker.stop_event.set()
    
    # Lista threads ativas (exceto thread principal)
    active_threads = [t for t in threading.enumerate() if t.daemon and t != threading.current_thread()]
    
    if active_threads:
        print(f"\n[Test Cleanup] Aguardando {len(active_threads)} threads ativas...")
        for t in active_threads:
            if t.is_alive():
                t.join(timeout=2)


@pytest.fixture
def tracker_server():
    """
    Sobe um tracker real para testes que exercitam socket/TCP.
    Redireciona stdin para /dev/null para evitar que o console bloqueie.
    """
    # Salva stdin original
    original_stdin = sys.stdin
    try:
        # Redireciona stdin para evitar leitura do console
        sys.stdin = open(os.devnull, 'r')
    except Exception:
        pass

    thread = threading.Thread(target=tracker.main, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while time.time() < deadline:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect((TRACKER_CONNECT_HOST, TRACKER_PORT))
            break
        except OSError:
            time.sleep(0.05)
        finally:
            probe.close()
    else:
        tracker.stop_event.set()
        thread.join(timeout=2)
        sys.stdin = original_stdin
        pytest.fail("Tracker não iniciou a tempo para o teste")

    yield thread

    tracker.stop_event.set()
    thread.join(timeout=2)

    try:
        sys.stdin.close()
    except Exception:
        pass
    sys.stdin = original_stdin