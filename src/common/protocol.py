import json
import struct

# ==============================================================================
# CONFIGURAÇÕES DE REDE
# ==============================================================================
TRACKER_HOST = '127.0.0.1'  # Endereço do servidor central (localhost para testes)
TRACKER_PORT = 5000         # Porta onde o Tracker escuta

# O Peer usará uma porta base ou dinâmica. Para testes, podemos usar 6000+.
PEER_BASE_PORT = 6000

# Tamanho do buffer para recebimento de dados
BUFFER_SIZE = 4096

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
        # Serializa o dicionário para string JSON e adiciona quebra de linha
        message = json.dumps(data) + '\n'
        sock.sendall(message.encode('utf-8'))
        return True
    except Exception as e:
        print(f"[Protocol Error] Falha ao enviar JSON: {e}")
        return False

def recv_json(sock):
    """
    Recebe uma string JSON terminada em newline e converte para dicionário Python.
    """
    try:
        data = sock.recv(BUFFER_SIZE)
        if not data:
            return None
        # Decodifica e carrega o JSON
        return json.loads(data.decode('utf-8').strip())
    except json.JSONDecodeError:
        print("[Protocol Error] Resposta inválida do servidor (não é JSON).")
        return None
    except Exception as e:
        print(f"[Protocol Error] Erro ao receber dados: {e}")
        return None

def send_chunk_header(sock, chunk_index, total_chunks, data_length):
    """
    Envia o cabeçalho binário antes de enviar um pedaço do arquivo.
    Formato: <I (index)><I (total)><Q (length)>
    Isso ajuda o receptor a saber o que esperar e onde encaixar.
    """
    # 'I' = unsigned int (4 bytes), 'Q' = unsigned long long (8 bytes)
    header = struct.pack('!IIQ', chunk_index, total_chunks, data_length)
    sock.sendall(header)

def recv_chunk_header(sock):
    """
    Recebe e decodifica o cabeçalho binário de um chunk.
    Retorna: (chunk_index, total_chunks, data_length) ou None em caso de erro.
    """
    header_size = struct.calcsize('!IIQ') # 4 + 4 + 8 = 16 bytes
    try:
        header_data = sock.recv(header_size)
        if len(header_data) < header_size:
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

# ==============================================================================
# AÇÕES PEER-TO-PEER
# ==============================================================================
ACTION_GET_CHUNK = "GET_CHUNK"