import socket
import json

from src.common.protocol import TRACKER_CONNECT_HOST, TRACKER_PORT, recv_json


def send_message(msg):
    """Envia mensagem JSON ao tracker e retorna a resposta."""
    s = socket.socket()
    try:
        s.connect((TRACKER_CONNECT_HOST, TRACKER_PORT))
        s.sendall((json.dumps(msg) + "\n").encode())
        return recv_json(s)
    finally:
        s.close()


def test_full_flow(tracker_server):
    """
    Testa fluxo completo: REGISTER, LOOKUP por nome, HEARTBEAT, UNREGISTER.
    As mensagens NÃO enviam 'peer_ip' – o tracker obtém o IP da conexão.
    """
    # REGISTER (apenas porta e dados do arquivo)
    res = send_message({
        "action": "REGISTER",
        "port": 6000,
        "files": ["integration_file.iso"],
        "size": 1000,
        "sha256": "abc"
    })
    assert res["status"] == "OK"

    # LOOKUP por nome
    res = send_message({
        "action": "LOOKUP",
        "filename": "integration_file"
    })
    assert res["status"] == "FOUND"
    assert res["file_info"]["name"] == "integration_file.iso"
    assert res["peers"] == [
        {
            "ip": "127.0.0.1",
            "port": 6000,
            "chunks_available": [0],
        }
    ]

    # HEARTBEAT (apenas porta)
    res = send_message({
        "action": "HEARTBEAT",
        "port": 6000
    })
    assert res["status"] == "OK"

    # UNREGISTER (apenas porta)
    res = send_message({
        "action": "UNREGISTER",
        "port": 6000
    })
    assert res["status"] == "OK"


def test_lookup_by_sha256(tracker_server):
    """
    Testa busca por SHA256 (nova funcionalidade).
    """
    # Registra um peer com hash específico
    send_message({
        "action": "REGISTER",
        "port": 6001,
        "files": ["test.iso"],
        "size": 2000,
        "sha256": "deadbeef"
    })

    # Busca por nome ainda funciona
    res = send_message({"action": "LOOKUP", "filename": "test"})
    assert res["status"] == "FOUND"

    # Busca exata por hash – deve encontrar
    res = send_message({"action": "LOOKUP", "sha256": "deadbeef"})
    assert res["status"] == "FOUND"
    assert res["file_info"]["sha256"] == "deadbeef"
    assert len(res["peers"]) == 1

    # Busca por hash inexistente
    res = send_message({"action": "LOOKUP", "sha256": "cafebabe"})
    assert res["status"] == "NOT_FOUND"


def test_list_peers_returns_active_snapshot(tracker_server):
    send_message({
        "action": "REGISTER",
        "port": 6010,
        "files": ["alpha.iso"],
        "size": 100,
        "sha256": "hash-alpha"
    })
    send_message({
        "action": "REGISTER",
        "port": 6011,
        "files": ["beta.iso"],
        "size": 200,
        "sha256": "hash-beta"
    })

    res = send_message({"action": "LIST_PEERS"})
    assert res["status"] == "OK"
    assert res["peer_count"] == 2
    assert [peer["port"] for peer in res["peers"]] == [6010, 6011]
    assert res["peers"][0]["files"] == ["alpha.iso"]
    assert res["peers"][1]["files"] == ["beta.iso"]


def test_update_chunks(tracker_server):
    """
    Testa a atualização de chunks disponíveis de um peer.
    """
    # Registra peer com arquivo de 2 chunks (tamanho > CHUNK_SIZE, mas aqui
    # definimos tamanho 2*CHUNK_SIZE bytes para ter 2 chunks)
    chunk_size = 1024 * 1024
    send_message({
        "action": "REGISTER",
        "port": 6002,
        "files": ["partial.iso"],
        "size": 2 * chunk_size,
        "sha256": "123456"
    })

    # Atualiza chunks (apenas o chunk 0 disponível)
    res = send_message({
        "action": "UPDATE_CHUNKS",
        "port": 6002,
        "filename": "partial.iso",
        "chunks_available": [0]
    })
    assert res["status"] == "OK"

    # Verifica no lookup que os chunks foram atualizados
    res = send_message({
        "action": "LOOKUP",
        "filename": "partial"
    })
    assert res["status"] == "FOUND"
    peer = res["peers"][0]
    assert peer["port"] == 6002
    assert peer["chunks_available"] == [0]   # só o chunk 0


def test_register_ignores_provided_ip(tracker_server):
    """
    Testa que o tracker **ignora** qualquer 'peer_ip' enviado
    e usa o IP real da conexão (127.0.0.1).
    """
    # Tenta registrar com IP falso
    res = send_message({
        "action": "REGISTER",
        "peer_ip": "192.168.1.100",  # será ignorado
        "port": 6003,
        "files": ["fake.iso"],
        "size": 500,
        "sha256": "fakehash"
    })
    assert res["status"] == "OK"

    # No lookup, o IP deve ser 127.0.0.1 (não o falso)
    res = send_message({"action": "LOOKUP", "filename": "fake"})
    assert res["status"] == "FOUND"
    assert res["peers"][0]["ip"] == "127.0.0.1"
