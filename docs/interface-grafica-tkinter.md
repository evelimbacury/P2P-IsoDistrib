# Interface Grafica Tkinter

Este documento descreve a GUI do peer do P2P-IsoDistrib. A interface grafica
nao substitui o tracker: ela representa uma instancia de peer/cliente. Para
testar a rede, execute um tracker e abra uma ou mais janelas da GUI usando
portas diferentes.

## Execucao

Suba o tracker em um terminal:

```bash
.venv/bin/python -m src.tracker.tracker
```

Abra uma instancia da GUI:

```bash
.venv/bin/python -m src.gui.main
```

Para testar multiplos peers na mesma maquina, abra varias janelas da GUI e use
uma porta diferente em cada uma, por exemplo `6000`, `6001` e `6002`.

## Abas

### Conexao

Permite configurar a porta do peer, iniciar/parar a instancia, ver o estado da
conexao com o tracker e confirmar se o servidor de upload esta ativo.

### Arquivos Locais

Lista os arquivos `.iso` encontrados em `shared_files/`, calcula SHA256 e
permite publicar arquivos no tracker. Tambem e possivel escolher uma ISO fora
de `shared_files/`. Nesse caso a GUI mostra um aviso visual e registra a
mensagem nos logs.

Arquivos publicados fora de `shared_files/` sao servidos pelo caminho original
enquanto a instancia atual do peer estiver aberta. Para manter o comportamento
mais simples entre reinicios, copie a ISO para `shared_files/`.

### Buscar

Busca arquivos no tracker por nome ou por `sha256:<hash>`. A tabela mostra o
arquivo encontrado, tamanho, hash, peer e chunks disponiveis.

### Downloads

Mostra o download em andamento, incluindo status, chunks concluidos,
velocidade e barra de progresso.

### Logs

Exibe mensagens da camada de aplicacao e do fluxo de upload/download. Essa aba
ajuda a diagnosticar problemas como tracker indisponivel, arquivo nao
encontrado no peer remoto ou falha de verificacao SHA256.

## Arquitetura

A GUI usa `src.app.peer_session.PeerSession`, a mesma camada de aplicacao usada
pela CLI. Essa classe concentra o ciclo de vida do peer: iniciar servidor de
upload, conectar ao tracker, enviar heartbeat, publicar, buscar, baixar e
encerrar.

O download paralelo em `src.peer.file_manager` emite eventos de progresso e
logs por callbacks. Assim, a GUI atualiza a barra de progresso e a aba de logs
sem depender de captura de `print()`.

## Tkinter

O Tkinter faz parte da biblioteca padrao, mas o Python precisa ter suporte
nativo Tcl/Tk. Teste com:

```bash
python -m tkinter
```

No macOS com Homebrew, instale o pacote Tk da mesma versao do Python usado para
criar a venv. Exemplo com Python 3.14:

```bash
brew install python-tk@3.14
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m tkinter
```

No Linux, instale o pacote do sistema antes de criar a venv:

```bash
# Debian/Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch/Manjaro
sudo pacman -S tk
```

No Windows, use o instalador oficial do Python com a opcao `tcl/tk and IDLE`
habilitada.

