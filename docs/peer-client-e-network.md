# Peer, Cliente CLI e Camada de Rede do P2P-IsoDistrib

Este documento descreve o estado atual da implementação do peer após a criação da CLI e das funções de comunicação com o tracker. Ele complementa `docs/protocolo-e-tracker.md` e registra o que já está pronto, como validar, quais contratos devem ser preservados e quais pontos desbloqueiam as próximas etapas do desenvolvimento.

## Visão geral

O peer atual possui duas responsabilidades implementadas:

- `src/peer/network.py`: encapsula a comunicação TCP com o tracker, cálculo de SHA256 e envio das ações `REGISTER`, `HEARTBEAT`, `LOOKUP`, `UNREGISTER` e `UPDATE_CHUNKS`.
- `src/peer/client.py`: oferece uma CLI interativa para publicar ISOs, buscar arquivos no tracker, listar arquivos locais e encerrar o peer com unregister.

Ainda não há transferência peer-to-peer de chunks. O cliente registra e descobre fontes pelo tracker, mas o servidor P2P de chunks, o download paralelo e a remontagem do arquivo ainda são etapas futuras.

## Arquivos principais

- `src/peer/client.py`
- `src/peer/network.py`
- `src/peer/file_manager.py`
- `src/common/protocol.py`
- `tests/test_peer_logic.py`
- `tests/conftest.py`

## Implementação da rede (`src/peer/network.py`)

### Conexão com o tracker

`connect_to_tracker()` cria um socket TCP e tenta conectar em `(TRACKER_HOST, TRACKER_PORT)`. Em caso de falha, fecha o socket, exibe uma mensagem amigável e retorna `None`.

Essa função usa os valores importados de `src.common.protocol`, então mudanças de host ou porta devem ser feitas no protocolo comum ou via monkeypatch direto no módulo `src.peer.network` durante testes.

### Ciclo de requisição ao tracker

Todas as operações passam por `_request_tracker(tracker_sock, message)`, que abre uma conexão TCP curta com o tracker, envia a mensagem com `send_json()`, recebe a resposta com `recv_json()` e fecha o socket ao final.

A função ainda recebe `tracker_sock` por compatibilidade com a CLI e os testes, mas a comunicação efetiva usa uma conexão nova por requisição. Essa decisão evita problemas com conexões ociosas fechadas pelo tracker após timeout.

O lock global continua protegendo o par envio/recebimento para impedir que comandos da CLI e heartbeat executem requisições simultâneas.

### Registro (`send_register`)

Responsabilidades:

- aceitar tanto a assinatura atual `(sock, port, filepath)` quanto a assinatura antiga `(sock, peer_ip, port, filepath)`;
- ignorar qualquer `peer_ip`, pois o tracker identifica o IP real pela conexão;
- validar existência do arquivo;
- aceitar apenas extensão `.iso`, sem diferenciar maiúsculas e minúsculas;
- calcular `sha256` lendo o arquivo em blocos de 4096 bytes;
- enviar `REGISTER` com `port`, `files`, `size` e `sha256`;
- retornar `True` apenas quando o tracker responder `OK`.

Mensagem enviada:

```python
{
    "action": ACTION_REGISTER,
    "port": port,
    "files": [filename],
    "size": size,
    "sha256": sha256,
}
```

### Heartbeat (`send_heartbeat`)

Envia:

```python
{
    "action": ACTION_HEARTBEAT,
    "port": port,
}
```

Retorna `False` quando não há resposta ou quando o tracker responde `ERROR`. Respostas como `OK`, `WARNING` e `RATE_LIMITED` não são tratadas como queda de conexão.

### Lookup (`send_lookup`)

Aceita busca por nome ou por hash:

```python
send_lookup(sock, filename="ubuntu")
send_lookup(sock, sha256="abc123")
```

Se `sha256` for informado, ele tem prioridade sobre `filename`. Quando o tracker responde `FOUND`, a função retorna o dicionário completo da resposta. Em `NOT_FOUND` ou erro, exibe mensagem e retorna `None`.

### Unregister (`send_unregister`)

Envia:

```python
{
    "action": ACTION_UNREGISTER,
    "port": port,
}
```

Retorna `True` somente quando o tracker confirma `OK`.

### Atualização de chunks (`send_update_chunks`)

Envia:

```python
{
    "action": ACTION_UPDATE_CHUNKS,
    "port": port,
    "filename": filename,
    "chunks_available": chunks_available,
}
```

Essa função já está pronta para ser usada pelo futuro módulo de download. A ideia é que um peer informe ao tracker quais chunks já possui depois de baixar parcialmente um arquivo.

## Implementação da CLI (`src/peer/client.py`)

### Inicialização

O cliente aceita `--port`, com padrão `PEER_BASE_PORT`. Ao iniciar, cria as pastas `shared_files/` e `downloads/`, exibe o banner local e tenta conectar ao tracker.

Exemplo:

```bash
python3 src/peer/client.py --port 6001
```

Se o tracker estiver indisponível, o usuário pode continuar em modo offline ou sair.

### Heartbeat

O cliente inicia uma thread daemon que chama `send_heartbeat()` a cada `HEARTBEAT_INTERVAL`. Após três falhas consecutivas, exibe:

```text
[Warning] Tracker unreachable
```

O heartbeat usa a mesma camada de rede dos comandos da CLI. Cada batimento abre uma conexão curta com o tracker, envia `HEARTBEAT` e fecha a conexão.

### Comando `publish`

Uso:

```text
publish shared_files/test.iso
```

Validações:

- exige caminho;
- verifica se o arquivo existe;
- aceita apenas `.iso`;
- alerta se o arquivo não estiver dentro de `shared_files/`;
- registra o arquivo no tracker com tamanho e SHA256.

### Comando `search`

Uso por nome:

```text
search ubuntu
```

Uso por hash:

```text
search sha256:abc123
```

Quando há resultado, a CLI mostra nome, tamanho, SHA256 e lista de peers com os chunks disponíveis.

### Comando `list_local`

Lista arquivos `.iso` dentro de `shared_files/`, exibindo nome, tamanho formatado e SHA256 calculado no momento.

Se não houver ISOs:

```text
[Local] No .iso files found in shared_files/
```

### Comando `exit`

Executa `UNREGISTER`, interrompe o heartbeat, fecha o socket do tracker e encerra o processo.

## Testes

O arquivo `tests/test_peer_logic.py` cobre:

- formatação de tamanho (`format_size`);
- compactação visual de ranges de chunks (`format_chunks`);
- cálculo de SHA256;
- falha controlada de conexão com tracker;
- fluxo completo do peer contra tracker real: register, heartbeat, lookup por nome, lookup por SHA256, update chunks e unregister.

Validação executada:

```bash
venv/bin/python -m pytest -q
```

Resultado:

```text
26 passed in 54.96s
```

Quando executado dentro de sandbox restrito, os testes que sobem o tracker podem falhar com `Operation not permitted` ao tentar abrir socket. Nesse caso, a suíte precisa ser rodada em ambiente com permissão de bind TCP local.

## Contratos que devem ser preservados

- O peer não deve enviar `peer_ip` ao tracker.
- Toda mensagem para o tracker deve usar as constantes de `src.common.protocol`.
- Cada operação de controle deve tolerar conexão anterior expirada e abrir uma nova conexão com o tracker.
- Arquivos publicados devem ser `.iso` e possuir SHA256.
- `send_lookup()` deve priorizar `sha256` quando `filename` e `sha256` forem informados.
- `send_update_chunks()` deve continuar exposta para integração com o futuro módulo de download.
- A CLI deve continuar funcionando com `python3 src/peer/client.py --port <porta>`.
- O unregister deve ser chamado no encerramento normal da CLI.

## Próximas etapas recomendadas

### 1. Implementar `src/peer/file_manager.py`

Responsabilidades sugeridas:

- validar extensão `.iso`;
- calcular SHA256;
- calcular `total_chunks`;
- ler um chunk por índice;
- gravar chunks baixados em arquivo temporário;
- remontar a ISO final;
- validar SHA256 após download;
- mover arquivo validado para `downloads/`.

Funções sugeridas:

```python
calculate_file_sha256(filepath)
get_file_metadata(filepath)
get_total_chunks(size)
read_chunk(filepath, chunk_index)
write_chunk(temp_path, chunk_index, data)
validate_download(filepath, expected_sha256)
```

### 2. Implementar servidor P2P de chunks

Cada peer precisa escutar em sua própria porta e responder `GET_CHUNK` para outros peers.

Fluxo esperado:

1. Receber JSON com `ACTION_GET_CHUNK`, `filename` e `chunk_index`.
2. Localizar o arquivo em `shared_files/`.
3. Ler o chunk solicitado.
4. Enviar cabeçalho binário com `send_chunk_header()`.
5. Enviar bytes do chunk.

Essa parte deve ficar preferencialmente em `src/peer/network.py` ou em um módulo dedicado se crescer muito.

### 3. Implementar download paralelo

O download deve:

- chamar `send_lookup()` para descobrir peers;
- distribuir chunks entre peers disponíveis;
- baixar chunks em threads;
- gravar chunks em arquivo temporário;
- chamar `send_update_chunks()` conforme chunks forem baixados;
- validar SHA256 final;
- mover o arquivo validado para `downloads/`.

### 4. Adicionar comando `download`

Uso esperado:

```text
download ubuntu.iso
```

O comando deve buscar o arquivo no tracker, iniciar o swarm download e exibir progresso.

### 5. Melhorar resiliência do tracker socket

Hoje, se a conexão com o tracker cair, as funções retornam falha, mas não há reconexão automática. Uma evolução útil seria manter uma rotina de reconnect para heartbeat, publish, search e unregister.

### 6. Separar saída de terminal de lógica testável

As funções atuais imprimem mensagens diretamente. Para testes maiores, pode valer retornar estruturas de erro e deixar a CLI decidir como exibir mensagens.

## Limitações atuais

- Não há servidor peer-to-peer escutando a porta do peer.
- Não há implementação de `GET_CHUNK`.
- Não há download paralelo.
- Não há persistência de cache de SHA256 local.
- Não há reconexão automática com tracker.
- Não há autenticação ou assinatura de peers.
- O cliente ainda não publica automaticamente todos os arquivos de `shared_files/` ao iniciar.

## Conclusão

A base do peer já permite interagir com o tracker de forma funcional: publicar ISOs, buscar arquivos, enviar heartbeat, atualizar chunks e sair corretamente. O próximo avanço natural é implementar o gerenciamento de chunks e o servidor peer-to-peer, usando `send_update_chunks()` como ponte entre o download parcial e o tracker.
