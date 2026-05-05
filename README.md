# P2P-IsoDistrib - Sistema de Distribuição de Arquivos ISO via Rede P2P Híbrida

**Disciplina:** Sistemas Distribuídos

**Tema Sorteado:** Tema 7 - Distribuição de Arquivos .iso

**Integrantes:**
- Evelim Bacury Rocha - Arquiteta / Tracker
- Márcio Éric Lamêgo Valente - Peer Core / CLI / GUI
- José Santo Moura Neto - Download Paralelo / SHA256
- Gabriel Moriz da Silva - Docker / Testes / Relatório

---

## Definição do Tema 7 (ISOs)

- **Tipo de Arquivo:** `.iso` (Imagens de disco de sistemas operacionais, bootáveis).
- **Contexto de Uso:** Laboratório de informática ou Install Fests. Baixar uma ISO de 4 GB+ da internet uma única vez e distribuí-la rapidamente via rede local (LAN), evitando gargalos no link externo.
- **Metadados Específicos:**
    - `name`: Nome do arquivo (ex: `ubuntu-24.04-desktop-amd64.iso`).
    - `size`: Tamanho total em bytes.
    - `sha256`: **Checksum SHA256** (Obrigatório). Garante que a ISO não foi corrompida ou adulterada durante a transferência fragmentada.
- **Extensão Obrigatória (Grupo de 4 pessoas):**
    - **Download Paralelo (Swarm Download):** O cliente baixa diferentes chunks da ISO de diferentes peers simultaneamente, remonta ao final e valida o hash.

---

## Arquitetura do Sistema

O sistema segue uma arquitetura P2P Híbrida:
1. **Tracker (Servidor Central):** Mantém registro dos peers ativos e o mapeamento de quem possui qual chunk de qual arquivo. **Não armazena os arquivos.**
2. **Peers (Clientes):** Registram os arquivos ISO que possuem, consultam o Tracker para localizar fontes e baixam chunks diretamente uns dos outros via TCP.

```
[Tracker] <-- (JSON/Heartbeat) --> [Peer A]
    ^  |
    |  (Consulta "Quem tem ubuntu.iso?")
    |  v
[Peer C] <---- (Transferencia Chunks TCP) ----> [Peer B]
```

---

## Protocolo de Comunicação

A comunicação segue o padrão definido em `src/common/protocol.py`. Utilize SEMPRE as constantes desse arquivo.

| Tipo | Porta | Formato | Descrição |
| :--- | :--- | :--- | :--- |
| **Tracker** | `5000` | JSON via TCP | Registro, Heartbeat, Consulta (LOOKUP) |
| **Peer** | `6000`+ | Binário | Transferência de chunks de arquivos |

### Comandos do Tracker (JSON)

1. **REGISTER** (Peer → Tracker)
    ```json
    {"action": "REGISTER", "port": 6000, "files": ["ubuntu.iso"], "size": 4980736000, "sha256": "a1b2c3d4e5f6..."}
    ```
2. **HEARTBEAT** (Peer → Tracker a cada 30s)
    ```json
    {"action": "HEARTBEAT", "port": 6000}
    ```
3. **LOOKUP** (Peer → Tracker)
    ```json
    {"action": "LOOKUP", "filename": "ubuntu.iso"}
    ```
    Resposta do Tracker:
    ```json
    {
        "status": "FOUND",
        "file_info": {"name": "ubuntu.iso", "size": 4980736000, "sha256": "a1b2c3d4e5f6..."},
        "peers": [
            {"ip": "192.168.1.10", "port": 6000, "chunks_available": [0, 1, 2]},
            {"ip": "192.168.1.20", "port": 6001, "chunks_available": [3, 4, 5]}
        ]
    }
    ```
4. **UPDATE_CHUNKS** (Peer → Tracker)
    ```json
    {"action": "UPDATE_CHUNKS", "port": 6000, "filename": "ubuntu.iso", "chunks_available": [0, 1, 2]}
    ```
5. **UNREGISTER** (Peer → Tracker)
    ```json
    {"action": "UNREGISTER", "port": 6000}
    ```

### Transferência Peer-to-Peer (Binário)

**GET_CHUNK** (Peer A → Peer B)
- Requisição JSON: `{"action": "GET_CHUNK", "filename": "ubuntu.iso", "chunk_index": 5}\n`
- Resposta: cabeçalho binário `!IIQ` (chunk_index, total_chunks, data_length) + dados do chunk

---

## Comandos da CLI

Após iniciar o `client.py`, o usuário tem acesso aos seguintes comandos:

| Comando | Descrição |
| :--- | :--- |
| `publish <arquivo.iso>` | Calcula SHA256, registra no Tracker e passa a servir chunks |
| `search <palavra\|sha256:hash>` | Busca arquivos disponíveis na rede pelo nome ou hash |
| `download <nome>` | Baixa o arquivo em paralelo de múltiplos peers com verificação SHA256 |
| `list_local` | Lista os arquivos `.iso` disponíveis em `shared_files/` |
| `exit` | Remove o peer do Tracker e encerra o programa |

## Interface Gráfica (Tkinter)

Além da CLI, o peer também pode ser usado por uma interface gráfica feita com
Tkinter. O Tkinter faz parte da biblioteca padrão, mas o Python precisa ter o
suporte nativo Tcl/Tk instalado.

Documentacao completa da GUI: `docs/interface-grafica-tkinter.md`.

No macOS com Python do Homebrew, instale o pacote Tk da mesma versão do Python e
crie a venv usando esse interpretador:

```bash
brew install python-tk@3.14
python3.14 -m tkinter

python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m tkinter
```

Em Linux, instale o pacote do sistema antes de criar a venv:

```bash
# Debian/Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch/Manjaro
sudo pacman -S tk
```

No Windows, use o instalador oficial do Python e mantenha a opção **tcl/tk and
IDLE** habilitada. Se a venv foi criada antes de instalar o suporte ao Tk,
recrie a venv.

Para testar:

```bash
python -m tkinter
```

> Não instale `tkinter` via `pip`. Se aparecer
> `ModuleNotFoundError: No module named '_tkinter'`, instale o suporte Tcl/Tk no
> Python do sistema e recrie a venv.

### Rodar a GUI

```bash
.venv/bin/python -m src.gui.main
```

A GUI possui abas para:

- **Conexão:** porta do peer, status do tracker, controle iniciar/parar e estado do servidor de upload.
- **Arquivos Locais:** listagem de arquivos `.iso` em `shared_files/`, SHA256 e publicação no tracker.
- **Buscar:** busca por nome ou `sha256:<hash>`, com tabela de peers e chunks disponíveis.
- **Downloads:** barra de progresso, velocidade, chunks concluídos e status de verificação.
- **Logs:** mensagens emitidas pela camada de aplicação, sem depender da leitura do terminal.

### Organização modular da interface

A CLI e a GUI usam a mesma camada de sessão em `src/app/peer_session.py`.
Essa classe concentra o ciclo de vida do peer: iniciar upload server, conectar
ao tracker, manter heartbeat, publicar, buscar, baixar e encerrar. Assim,
`src/peer/client.py` continua sendo apenas uma interface de terminal, enquanto
`src/gui/main_window.py` é apenas uma interface gráfica sobre o mesmo núcleo.

Os modelos compartilhados ficam em `src/app/models.py`, e eventos de log,
status e progresso são emitidos por `src/app/events.py`. O download paralelo em
`src/peer/file_manager.py` aceita callbacks `on_progress` e `on_log`, permitindo
que a GUI atualize barras de progresso e logs sem capturar `print()`.

---

## O que foi implementado

### Tracker (`src/tracker/tracker.py`)

- Ações suportadas: `REGISTER`, `HEARTBEAT`, `LOOKUP`, `UNREGISTER` e `UPDATE_CHUNKS`.
- Armazena peers ativos, arquivos publicados, tamanho, SHA256 e chunks disponíveis.
- Usa o IP real da conexão para registrar o peer e evitar spoofing.
- Remove automaticamente peers que não enviam heartbeat por mais de 60 segundos.
- Console de administração com comandos `list` e `exit`.

### Peer / CLI (`src/peer/client.py` e `src/app/peer_session.py`)

- `publish <arquivo.iso>`: calcula SHA256, registra no tracker e torna o arquivo disponível para upload.
- `search <palavra|sha256:hash>`: busca por nome ou hash exato.
- `download <nome>`: baixa o arquivo em paralelo de múltiplos peers, monta o resultado e verifica o hash SHA256.
- `list_local`: lista arquivos `.iso` em `shared_files/` com nome, tamanho e hash.
- `help`: mostra comandos disponíveis.
- `exit`: encerra o peer e remove o registro do tracker.
- `PeerSession` organiza a sessão comum entre CLI e GUI, incluindo servidor de upload, conexão com tracker, heartbeat, publicação, busca, download e parada.

### Transferência de chunks (`src/peer/file_manager.py`)

- Upload server TCP responde `GET_CHUNK` com JSON de requisição seguido de cabeçalho binário `!IIQ` e dados do chunk.
- Localiza arquivos primeiramente em `shared_files/`; como fallback, também aceita arquivos em `downloads/`.
- Download paralelo em chunks de 1 MiB com até 4 downloads concorrentes.
- Seleção de peers baseada na carga atual, com retry em até 3 peers diferentes por chunk.
- Progresso é emitido para terminal ou para a GUI via callbacks.
- Os chunks são montados em `downloads/`, o hash SHA256 é verificado e o arquivo é removido em caso de mismatch.
- Após download bem sucedido, o peer se registra automaticamente como seeder do novo arquivo.

### Protocolo e robustez (`src/common/protocol.py`)

- Comunicação JSON fim de linha entre peer e tracker.
- Transferência de chunk com cabeçalho binário e recepção de tamanho exato.
- Heartbeat a cada 30 segundos para manter o peer ativo no tracker.
- Limites de tamanho de JSON e timeouts para evitar falhas silenciosas.

### Demonstração e testes

- `demo.bat` automatiza tracker e peers de teste com publicação e download paralelo.
- `scripts/create_test_iso.py`: gera `shared_files/test.iso` de 500 MB para validação.
- `scripts/demo_peer.py`: wrapper para execução automática de peers no demo.
- `scripts/demo_progress.py`: demonstra a barra de progresso em loop local.
- `scripts/verify.py`: verifica SHA256 entre `shared_files/test.iso` e `downloads/test.iso`.
- Testes automatizados em `tests/` cobrem tracker, protocolo, gerenciamento de arquivos e download paralelo.

---

## Configuração do Ambiente

### Pré-requisitos

- Python 3.10+ (testado com Python 3.12)
- Windows 10/11, Linux ou macOS

### 1. Clonar o repositório

```bash
git clone <url-do-repositorio>
cd P2P-IsoDistrib
```

### 2. Criar a virtual environment

```bash
python -m venv .venv
```

### 3. Instalar dependências

**Windows (MSYS2 / Git Bash):**
```bash
.venv/bin/pip install -r requirements.txt
```

**Windows (PowerShell / CMD nativo):**
```powershell
.venv\Scripts\pip install -r requirements.txt
```

**Linux / macOS:**
```bash
.venv/bin/pip install -r requirements.txt
```

> **Observação:** O projeto usa caminhos no estilo `.venv/bin/python` nos exemplos abaixo (compatível com MSYS2/Git Bash e Linux/macOS). No PowerShell/CMD nativo do Windows, substitua `/` por `\` e `bin` por `Scripts`.

### 4. Executar manualmente

**Terminal 1 — Tracker:**
```bash
.venv/bin/python -m src.tracker.tracker
```

**Terminal 2 — Peer (porta 6000):**
```bash
.venv/bin/python -m src.peer.client --port 6000
```

**Terminal 3 — Peer (porta 6001):**
```bash
.venv/bin/python -m src.peer.client --port 6001
```

---

## Demo Automática (Windows)

O arquivo `demo.bat` abre automaticamente 4 terminais e executa o experimento completo:

```
Tracker | Peer 6000 (publica) | Peer 6001 (publica) | Peer 6002 (baixa)
```

```
.\demo.bat
```

O script:
1. Gera `shared_files/test.iso` com **500 MB** (na primeira execução; reutiliza nas seguintes)
2. Limpa `downloads/` de execuções anteriores
3. Sobe o Tracker
4. Peers 6000 e 6001 publicam automaticamente (calculam SHA256 + registram)
5. Peer 6002 aguarda 5 s, faz o download em paralelo e exibe a barra de progresso ao vivo
6. Se não encontrar peers na primeira tentativa, retenta automaticamente até 10 vezes

> **Observação — arquivo de teste simulado:**
> O `test.iso` gerado pelo demo é preenchido com zeros (`\x00`), **não é uma ISO real**.
> Serve exclusivamente para validar o protocolo de transferência e a integridade SHA256.
> Para testar com uma imagem real, substitua `shared_files/test.iso` por qualquer `.iso`
> (ex: `ubuntu-24.04-desktop-amd64.iso`) e ajuste o nome nos comandos de `publish` e `download`.

**Barra de progresso no terminal do Peer 6002:**
```
[Download] test.iso: [########--------]  52% (260/500) - 4 peers active - 198.40 MB/s
```

**Após o download, verificar integridade:**
```bash
.venv/bin/python scripts/verify.py
```

---

## Scripts Utilitários

| Script | Descrição |
| :--- | :--- |
| `scripts/verify.py` | Compara SHA256 de `shared_files/test.iso` com `downloads/test.iso` |
| `scripts/demo_peer.py` | Wrapper interno do demo.bat: injeta comando automático no peer |
| `scripts/create_test_iso.py` | Gera `shared_files/test.iso` com 500 MB de zeros para teste (mock, não é ISO real) |
| `scripts/demo_progress.py` | Demo standalone da barra de progresso com 500 MB em loopback |

---

## Testes Automatizados

```bash
.venv/bin/pytest tests/ -v
```

| Arquivo | Cobertura | Testes |
| :--- | :--- | :--- |
| `test_tracker_unit.py` | Lógica interna do tracker (register, lookup, heartbeat, timeout, unregister) | 8 |
| `test_tracker_integration.py` | Tracker com sockets TCP reais | 4 |
| `test_peer_logic.py` | format_size, format_chunks, SHA256, fluxo de rede | 5 |
| `test_protocol.py` | send/recv JSON fragmentado, cabeçalho binário de chunk | 3 |
| `test_file_manager_unit.py` | format_size, _recv_data, handle_upload_request (incluindo fallback downloads/) | 11 |
| `test_file_manager_integration.py` | download_single_chunk, download_file_parallel, retry mid-transfer, 100 MB | 17 |
| `test_download_cli.py` | Comando `download` na CLI — erros, sucesso, registro como seeder | 9 |
| Carga / Churn / Extremos / Lookup | Múltiplos peers simultâneos, alta carga, lookup sob pressão | 13 |

**Resultado esperado:** `70 passed`

---

## Docker *(em desenvolvimento)*

Suporte a Docker está previsto para simular a rede com 1 Tracker e múltiplos Peers isolados:

```bash
docker-compose up --build
```

---

## Relatório e Entrega

- Código: Organizado nas pastas `src/tracker`, `src/peer`, `src/common`
- Documentação técnica:
    - `docs/protocolo-e-tracker.md`
    - `docs/peer-client-e-network.md`
- Relatório: `docs/Relatorio.pdf` (2-3 páginas com arquitetura e testes)
- Vídeo: Link do YouTube demonstrando a transferência de uma ISO entre 3 peers
