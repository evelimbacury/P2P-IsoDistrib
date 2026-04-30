import json
import struct
import socket
import logging
import threading

logger = logging.getLogger("P2P-IsoDistrib.Protocol")

# ==============================================================================
# CONFIGURAÇÕES DE REDE
# ==============================================================================
TRACKER_BIND_HOST = '0.0.0.0'   # Endereço usado pelo tracker para bind()
TRACKER_CONNECT_HOST = '127.0.0.1'  # Endereço que clientes usam para se conectar localmente
TRACKER_HOST = TRACKER_CONNECT_HOST  # Compatibilidade com código legado
TRACKER_PORT = 5000                 # Porta onde o Tracker escuta

# O Peer usará uma porta base ou dinâmica. Para testes, podemos usar 6000+.
PEER_BASE_PORT = 6000

# Tamanho do buffer para recebimento de dados
BUFFER_SIZE = 4096
MAX_JSON_SIZE = 1 * 1024 * 1024  # 1 MB máximo para JSON (anti-DoS)

_json_recv_buffers = {}
_json_recv_lock = threading.Lock()

# ==============================================================================
# CONFIGURAÇÕES DO ARQUIVO ISO
# ==============================================================================
# Tamanho de cada pedaço (chunk) para download paralelo.
# 1 MB (1024 * 1024 bytes) é um bom equilíbrio para ISOs grandes.
CHUNK_SIZE = 1024 * 1024  

# Extensões de arquivo que o sistema aceita (Case Insensitive)
ALLOWED_EXTENSIONS = ['.iso']

# Pasta padrão onde os arquivos compartilhados ficam no Peer
SHARED_FOLDER = "shared_files"

# Pasta de destino para os downloads
DOWNLOAD_FOLDER = "downloads"

# ==============================================================================
# PROTOCOLO DE HEARTBEAT
# ==============================================================================
HEARTBEAT_INTERVAL = 30  # segundos (enviar sinal para o tracker)
PEER_TIMEOUT = 60        # segundos (tempo sem heartbeat para remover peer morto)

# ==============================================================================
# FUNÇÕES AUXILIARES DE COMUNICAÇÃO 
# ==============================================================================
def send_json(sock, data):
    """
    Envia um dicionário Python como string JSON terminada em newline.
    Padrão utilizado em TODAS as comunicações com o Tracker.
    """
    try:
        message = json.dumps(data) + '\n'
        sock.sendall(message.encode('utf-8'))
        return True
    except Exception as e:
        logger.warning(f"[Protocol Error] Falha ao enviar JSON: {e}")
        return False


def _socket_buffer_key(sock):
    """Gera uma chave estável para o buffer de leitura associado ao socket."""
    fileno = sock.fileno()
    return fileno if fileno >= 0 else id(sock)


def _clear_recv_buffer(sock):
    """Remove qualquer buffer pendente associado ao socket (uso interno)."""
    with _json_recv_lock:
        _json_recv_buffers.pop(_socket_buffer_key(sock), None)


def clear_recv_buffer(sock):
    """Limpa o buffer de recebimento JSON do socket (chamada pública)."""
    _clear_recv_buffer(sock)


def _recv_exact(sock, expected_bytes, timeout=10):
    """
    Lê exatamente a quantidade de bytes esperada, com timeout.
    Retorna None se a conexão encerrar ou ocorrer timeout.
    """
    old_timeout = sock.gettimeout()
    sock.settimeout(timeout)
    try:
        received = bytearray()
        while len(received) < expected_bytes:
            chunk = sock.recv(expected_bytes - len(received))
            if not chunk:
                return None
            received.extend(chunk)
        return bytes(received)
    except socket.timeout:
        logger.debug("[Protocol Error] Timeout ao receber dados binários (chunk)")
        return None
    finally:
        sock.settimeout(old_timeout)


def recv_json(sock, timeout=5):
    """
    Recebe uma string JSON terminada em newline e converte para dicionário Python.
    
    Args:
        sock: Socket para receber dados
        timeout: Timeout em segundos (padrão: 5s)
    
    Returns:
        dict: Dados JSON decodificados ou None em caso de erro
    """
    key = _socket_buffer_key(sock)

    try:
        old_timeout = sock.gettimeout()
        sock.settimeout(timeout)

        with _json_recv_lock:
            buffer = _json_recv_buffers.get(key, b"")

        try:
            while True:
                newline_pos = buffer.find(b"\n")
                if newline_pos != -1:
                    raw_line = buffer[:newline_pos]
                    buffer = buffer[newline_pos + 1:]

                    with _json_recv_lock:
                        if buffer:
                            _json_recv_buffers[key] = buffer
                        else:
                            _json_recv_buffers.pop(key, None)

                    if not raw_line.strip():
                        continue

                    # Proteção contra estouro de buffer (DoS)
                    if len(raw_line) > MAX_JSON_SIZE:
                        logger.warning("[Protocol Error] JSON excede limite máximo (%d bytes)", MAX_JSON_SIZE)
                        _clear_recv_buffer(sock)
                        return None

                    return json.loads(raw_line.decode('utf-8'))

                data = sock.recv(BUFFER_SIZE)
                if not data:
                    _clear_recv_buffer(sock)
                    if buffer.strip():
                        logger.warning("[Protocol Error] Conexão encerrada com JSON incompleto no buffer.")
                    return None

                buffer += data
                # Limite total do buffer acumulado
                if len(buffer) > MAX_JSON_SIZE:
                    logger.warning("[Protocol Error] Buffer de recebimento JSON excedeu %d bytes", MAX_JSON_SIZE)
                    _clear_recv_buffer(sock)
                    return None

                with _json_recv_lock:
                    _json_recv_buffers[key] = buffer
        finally:
            sock.settimeout(old_timeout)
    except socket.timeout:
        logger.debug("[Protocol Error] Timeout ao receber JSON (cliente lento ou parado)")
        return None
    except json.JSONDecodeError:
        logger.warning("[Protocol Error] Resposta inválida do servidor (não é JSON).")
        _clear_recv_buffer(sock)
        return None
    except Exception as e:
        logger.warning(f"[Protocol Error] Erro ao receber dados: {e}")
        _clear_recv_buffer(sock)
        return None

def send_chunk_header(sock, chunk_index, total_chunks, data_length):
    """
    Envia o cabeçalho binário antes de enviar um pedaço do arquivo.
    Formato: <I (index)><I (total)><Q (length)>
    Isso ajuda o receptor a saber o que esperar e onde encaixar.
    """
    header = struct.pack('!IIQ', chunk_index, total_chunks, data_length)
    sock.sendall(header)

def recv_chunk_header(sock):
    """
    Recebe e decodifica o cabeçalho binário de um chunk.
    Retorna: (chunk_index, total_chunks, data_length) ou None em caso de erro.
    """
    header_size = struct.calcsize('!IIQ')  # 4 + 4 + 8 = 16 bytes
    try:
        header_data = _recv_exact(sock, header_size, timeout=sock.gettimeout() or 10)
        if header_data is None:
            return None
        return struct.unpack('!IIQ', header_data)
    except Exception:
        return None

# ==============================================================================
# AÇÕES DO TRACKER (Strings constantes para evitar typos)
# ==============================================================================
ACTION_REGISTER = "REGISTER"
ACTION_HEARTBEAT = "HEARTBEAT"
ACTION_LOOKUP = "LOOKUP"
ACTION_UNREGISTER = "UNREGISTER"
ACTION_UPDATE_CHUNKS = "UPDATE_CHUNKS"

# ==============================================================================
# AÇÕES PEER-TO-PEER
# ==============================================================================
ACTION_GET_CHUNK = "GET_CHUNK"