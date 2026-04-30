# Protocolo e Tracker do P2P-IsoDistrib (versão revisada)

Este documento descreve a implementação final do protocolo de comunicação e do tracker central do projeto após as correções de segurança, robustez e ajustes nos testes. Todas as funcionalidades estão implementadas e a suíte de testes completa é aprovada.

## Visão geral

O projeto possui dois módulos principais já implementados:

- Protocolo comum em `src/common/protocol.py` – constantes de rede, heartbeat, tamanho de chunk, helpers de serialização e desserialização com proteções contra DoS.
- Tracker em `src/tracker/tracker.py` – servidor central que gerencia registro de peers, responde buscas com integridade de arquivo, processa heartbeats, remove peers inativos e oferece atualização parcial de chunks.

A comunicação de controle usa TCP com mensagens JSON delimitadas por `\n`, e a transferência P2P de dados emprega um cabeçalho binário fixo.

## Arquivos principais

- `src/common/protocol.py`
- `src/tracker/tracker.py`
- `tests/conftest.py`
- `tests/test_tracker_unit.py`
- `tests/test_tracker_integration.py`
- `tests/test_concurrent_peers.py`
- `tests/test_load.py`
- `tests/test_extreme.py`
- `tests/test_lookup.py`
- `tests/test_churn.py`
- `tests/test_timeout.py`
- `tests/utils/peer_simulator.py`

## Implementação do protocolo (`src/common/protocol.py`)

### Constantes de rede

```python
TRACKER_BIND_HOST = '0.0.0.0'    # interface de escuta do tracker  
TRACKER_CONNECT_HOST = '127.0.0.1' # endereço para clientes locais  
TRACKER_HOST = TRACKER_CONNECT_HOST  # mantido para compatibilidade  
TRACKER_PORT = 5000  
PEER_BASE_PORT = 6000  
BUFFER_SIZE = 4096
```

Nota de segurança: O tracker utiliza apenas o endereço de origem da conexão (`addr[0]`) para identificar o peer, ignorando qualquer IP enviado no JSON. Isso impede spoofing de IP.

### Constantes de arquivo

- `CHUNK_SIZE = 1024 * 1024` (1 MB)
- `ALLOWED_EXTENSIONS = ['.iso']`
- `SHARED_FOLDER = "shared_files"`
- `DOWNLOAD_FOLDER = "downloads"`

### Heartbeat e timeout

- `HEARTBEAT_INTERVAL = 30` segundos
- `PEER_TIMEOUT = 60` segundos
- O tracker remove peers que não enviam heartbeat dentro desse período.

### Funções JSON com proteções

- `send_json(sock, data)` – envia dicionário serializado com `\n`.

- `recv_json(sock, timeout=5)` – lê incrementalmente até encontrar `\n`, com timeout configurável, limite máximo de mensagem (`MAX_JSON_SIZE = 1 MB`) para prevenir ataques de memória, buffer global por socket (`_json_recv_buffers`) protegido por lock e limpeza garantida ao fechar a conexão (chamada `clear_recv_buffer` no finally).

- As funções de buffer são `_clear_recv_buffer(sock)` (interna) e `clear_recv_buffer(sock)` (pública, usada pelo tracker na desconexão). Isso elimina vazamento de estado entre conexões e evita que buffers residuais contaminem novas sessões.

### Cabeçalho binário de chunks com timeout

- `send_chunk_header(sock, chunk_index, total_chunks, data_length)` – formato `!IIQ` (16 bytes).

- `recv_chunk_header(sock)` – recebe os 16 bytes de forma exata, utilizando `_recv_exact` com timeout herdado do socket (padrão 10s se não definido).

- A função `_recv_exact` é robusta contra travamentos, aplicando timeout e retornando `None` em caso de falha.

### Ações disponíveis (constantes)

`ACTION_REGISTER = "REGISTER"`  
`ACTION_HEARTBEAT = "HEARTBEAT"`  
`ACTION_LOOKUP = "LOOKUP"`  
`ACTION_UNREGISTER = "UNREGISTER"`  
`ACTION_UPDATE_CHUNKS = "UPDATE_CHUNKS"`  
`ACTION_GET_CHUNK = "GET_CHUNK"`

## Implementação do tracker (`src/tracker/tracker.py`)

### Responsabilidades

Aceitar múltiplas conexões TCP, registrar peers e seus arquivos (exigindo hash SHA256), manter liveness via heartbeat com rate limiting, responder buscas por nome ou hash exato, retornar apenas peers que compartilham o mesmo hash (integridade), remover peers mortos (timeout) ou via `UNREGISTER` e suportar atualização parcial de chunks disponíveis.

### Estrutura de dados

```python
peers_dict = { 
  "IP:PORTA": { 
    "ip": "127.0.0.1", 
    "port": 6000, 
    "files": { 
      "ubuntu.iso": { 
        "size": 4980736000, 
        "sha256": "abc123...", 
        "total_chunks": 4750, 
        "chunks_available": None 
      } }, 
      "last_heartbeat": 1714857600.123, 
      "heartbeat_count": 12 
    } }
```

### Segurança de IP

Todas as ações (`REGISTER`, `HEARTBEAT`, `UNREGISTER`, `UPDATE_CHUNKS`) obtêm o IP exclusivamente da tupla `addr` (endereço real da conexão). Campos `peer_ip` no JSON são ignorados.

### Registro (`REGISTER`)

Exemplo de mensagem (enviada pelo peer):

```python
{ 
  "action": "REGISTER", 
  "port": 6000, 
  "files": ["ubuntu.iso"], 
  "size": 4980736000, 
  "sha256": "abc123..." 
}
```

O handler valida porta e lista de arquivos, exige `sha256` não vazio, cria ou atualiza a entrada no dicionário, define `chunks_available = None` (possui todos) para arquivos com tamanho maior que zero e atualiza `last_heartbeat`.

### Heartbeat (`HEARTBEAT`)

Mensagem:

```python
{ 
  "action": "HEARTBEAT", 
  "port": 6000 
}
```

Aplica rate limiting de 1 heartbeat por segundo por peer, incrementa o contador, atualiza `last_heartbeat` e responde `RATE_LIMITED` se necessário.

### Lookup com integridade (`LOOKUP`)

Aceita dois modos de busca: 
- por nome (`{"action": "LOOKUP", "filename": "ubuntu"}`) 
- ou por hash (`{"action": "LOOKUP", "sha256": "abc123..."}`), sendo o hash prioritário se ambos forem enviados.

O comportamento consiste em busca case-insensitive por substring no nome, mas agrupando apenas peers que possuem o mesmo hash. Se a busca for por hash, a correspondência é exata. O tracker ignora peers cujo hash difere do primeiro hash encontrado durante a busca, evitando a mesclagem de arquivos diferentes com nomes similares e garantindo integridade.

Resposta de sucesso:

```python
{ "status": "FOUND", "file_info": { "name": "ubuntu.iso", "size": 4980736000, "sha256": "abc123..." }, "peers": [ { "ip": "127.0.0.1", "port": 6000, "chunks_available": [0, 1, ..., 4749] } ] }
```

`chunks_available` é materializado a partir de `None` quando necessário, retornando a lista completa de índices.

### Unregister (`UNREGISTER`)

```python
{ "action": "UNREGISTER", "port": 6000 }
```

Remove o peer e todos os seus registros auxiliares, como contador de heartbeat e rate limit.

### Atualização de chunks (`UPDATE_CHUNKS`)

```python
{ "action": "UPDATE_CHUNKS", "port": 6000, "filename": "ubuntu.iso", "chunks_available": [0, 2, 5] }
```

Permite que um peer informe quais pedaços já possui (modo parcial). A lista é deduplicada e ordenada antes de ser armazenada.

### Limpeza de timeouts

Uma thread daemon executa `_do_cleanup()` a cada 10 segundos, removendo peers cujo último heartbeat exceda `PEER_TIMEOUT` (60s). A limpeza também remove contadores auxiliares, evitando vazamento de memória.

### Servidor TCP

`SO_REUSEADDR` está ativado, o limite de conexões simultâneas é `MAX_CONNECTIONS = 1000`, o contador é protegido por lock e o loop de aceitação usa timeout de 1 segundo para verificar evento de parada.

### Logging

O logger é centralizado em `"P2P-IsoDistrib"` com saída para console e arquivo `tracker.log`. Heartbeats são logados apenas a cada 5 ocorrências para evitar poluição.

### Console interativo

O tracker oferece comandos `list` e `exit` via console quando `sys.stdin` é um TTY. Em ambientes não interativos, como containers, testes ou systemd, o console é desabilitado automaticamente.

## Testes

### Fixtures de teste

`conftest.py` reseta completamente o estado global do tracker e os buffers JSON do protocolo (`_json_recv_buffers`) antes e depois de cada teste. A fixture `tracker_server` redireciona `sys.stdin` para `/dev/null` para evitar bloqueios do console durante os testes e garante que threads daemon sejam finalizadas ao fim da sessão.

### Testes unitários

`test_tracker_unit.py` testa todos os handlers isoladamente, utilizando tuplas `addr` reais. Inclui validação de campos obrigatórios, heartbeat em peer não registrado, lookup vazio e remoção por timeout.

### Testes de integração

`test_tracker_integration.py` exercita o fluxo completo via socket real, incluindo busca por hash e atualização de chunks.

### Testes de carga e concorrência

`test_concurrent_peers.py`, `test_load.py`, `test_extreme.py` e `test_lookup.py` utilizam o `peer_simulator` com hash fixo (`"shared_hash"`) para garantir que o lookup retorne todos os peers e validar integridade da resposta.

### Simulador de peers

`peer_simulator.py` foi ajustado para não enviar `peer_ip`, aceitar um argumento opcional `sha256` (permitindo testes com hash comum) e enviar heartbeat e unregister sem IP.

Resultado final: todos os 21 testes da suíte são executados com sucesso, com zero falhas e apenas um warning irrelevante relacionado ao cache do pytest.

## Limitações e riscos para ambiente real

Embora robusto para laboratório, ainda há pontos a considerar em produção.

- O endereço do tracker (`127.0.0.1`) funciona apenas localmente, sendo necessário um IP público ou hostname em rede real.
- O payload de lookup pode se tornar pesado para arquivos grandes e muitos peers, especialmente pela materialização de `chunks_available`.
- Não há autenticação, permitindo que qualquer cliente registre peers, o que não é adequado para redes abertas.
- O framing TCP depende de `\n`; mensagens sem delimitador podem manter buffers ativos até o limite.
- O modelo atual usa uma thread por conexão, o que pode não escalar bem, sendo recomendável considerar `asyncio` ou `select`.

## Conclusão

O sistema P2P-IsoDistrib possui um protocolo bem definido e um tracker central funcional, com proteção contra spoofing de IP e garantia de integridade de arquivos nas buscas. Há suporte a atualização parcial de chunks e uma suíte de testes abrangente que cobre cenários de concorrência e estresse. A base está sólida para evolução futura, incluindo implementação do peer e download paralelo.