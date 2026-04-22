# P2P-IsoDistrib - Sistema de Distribuição de Arquivos ISO via Rede P2P Híbrida

**Disciplina:** Sistemas Distribuídos

**Tema Sorteado:** Tema 7 - Distribuição de Arquivos .iso

**Integrantes:**
- Evelim Bacury Rocha - Arquiteta / Tracker
- Márcio Éric Lamêgo Valente - Peer Core / CLI
- José Santo Moura Neto - Download Paralelo / SHA256
- Gabriel Moriz da Silva - Docker / Testes / Relatório



## 📋 Definição do Tema 7 (ISOs)

- **Tipo de Arquivo:** `.iso` (Imagens de disco de sistemas operacionais, bootáveis).
- **Contexto de Uso:** Laboratório de informática ou Install Fests. Baixar uma ISO de 4GB+ da internet uma única vez e distribuí-la rapidamente via rede local (LAN), evitando gargalos no link externo.
- **Metadados Específicos:**
    - `name`: Nome do arquivo (ex: `ubuntu-24.04-desktop-amd64.iso`).
    - `size`: Tamanho total em bytes.
    - `sha256`: **Checksum SHA256** (Obrigatório). Garante que a ISO não foi corrompida ou adulterada durante a transferência fragmentada.
- **Extensão Obrigatória (Grupo de 4 pessoas):**
    - **Download Paralelo (Swarm Download):** O cliente deve ser capaz de baixar diferentes pedaços (chunks) da ISO de diferentes peers simultaneamente, juntá-los ao final e validar o hash.



## 🏗️ Arquitetura do Sistema

O sistema segue uma arquitetura P2P Híbrida:
1.  **Tracker (Servidor Central):** Mantém registro dos peers ativos e o mapeamento de quem possui qual chunk de qual arquivo. **Não armazena os arquivos.**
2.  **Peers (Clientes):** Registram os arquivos ISO que possuem, consultam o Tracker para localizar fontes e baixam chunks diretamente uns dos outros via TCP.

```
[Tracker] <-- (JSON/Heartbeat) --> [Peer A]
^ |
| (Consulta "Quem tem ubuntu.iso?") |
| v
[Peer C] <---- (Transferência Chunks TCP) ----> [Peer B]
```

---

## 📡 Protocolo de Comunicação

A comunicação segue o padrão definido em `src/common/protocol.py`. Utilize SEMPRE as constantes desse arquivo.

| Tipo | Porta | Formato | Descrição |
| :--- | :--- | :--- | :--- |
| **Tracker** | `5000` | JSON via TCP | Registro, Heartbeat, Consulta (LOOKUP) |
| **Peer** | `6000`+ | Binário | Transferência de chunks de arquivos |

### Comandos do Tracker (JSON)

1.  **REGISTER** (Cliente -> Tracker)
    ```json
    {"action": "REGISTER", "peer_ip": "127.0.0.1", "port": 6000, "files": ["ubuntu.iso"]}
    ```
2. HEARTBEAT (Cliente -> Tracker a cada 30s)
    ```json
    {"action": "HEARTBEAT", "peer_ip": "127.0.0.1", "port": 6000}
    ```
3. LOOKUP (Cliente -> Tracker)
    ```json
    {"action": "LOOKUP", "filename": "ubuntu.iso"}
    ```

Resposta Esperada do Tracker:
```json
    {
        "status": "FOUND",
        "file_info": {
            "name": "ubuntu.iso",
            "size": 4980736000,
            "sha256": "a1b2c3d4e5f6..."
        },
        "peers": [
            {"ip": "192.168.1.10", "port": 6000, "chunks_available": [0, 1, 2]},
            {"ip": "192.168.1.20", "port": 6001, "chunks_available": [3, 4, 5]}
        ]
    }
```

### Comandos Peer-to-Peer (Binário)

- GET_CHUNK (Cliente A -> Cliente B)
    - Envia: `{"action": "GET_CHUNK", "filename": "ubuntu.iso", "chunk_index": 0}\n`
    - Recebe: `<4 bytes tamanho (int)><dados binários do chunk>`


## 🚀 Comandos do Cliente (CLI)

Após iniciar o `client.py`, o usuário terá acesso aos seguintes comandos:

- `publish <caminho_do_arquivo.iso>`: Calcula SHA256, divide em chunks e registra no Tracker.
- `search <palavra>`: Busca arquivos disponíveis na rede.
- `download <nome_do_recurso>`: Inicia o download paralelo (swarm) usando todos os peers disponíveis.
- `list_local`: Lista os arquivos .iso disponíveis no diretório `shared_files/`.
- `exit`: Remove o peer do Tracker e encerra o programa.

---

## 🔧 Configuração do Ambiente (Desenvolvimento)

1. Instalar Dependências:
    ```bash
    pip install -r requirements.txt
    ```
2. Executar o Tracker:
    ```bash
    python src/tracker/tracker.py
    ```

3. Executar o Cliente (em outro terminal):
    ```bash
    python src/peer/client.py
    ```

_Nota: Para testes locais, cada cliente precisa de uma porta diferente. Altere no código ou use argumentos de linha de comando._

---
## 🐳 Testes com Docker
Para simular a rede com 1 Tracker e 3 Peers isolados:
```bash
docker-compose up --build    
```

Isso iniciará o ambiente e exibirá os logs de heartbeat e transferência.

---

## 📝 Relatório e Entrega

- Código: Organizado nas pastas src/tracker, src/peer, src/common.
- Relatório: Localizado em docs/Relatorio.pdf (2-3 páginas explicando arquitetura e testes, com tabelas e gráficos de exemplificação).
- Vídeo: Link do YouTube (não listado) demonstrando a transferência de uma ISO pequena (ex: FreeDOS) entre 3 peers.
