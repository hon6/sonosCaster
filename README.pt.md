# Sonos Caster

[English](README.md) | [简体中文](README.zh.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | **Português** | [Русский](README.ru.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Encaminhe o áudio do sistema Windows para uma caixa de som Sonos em tempo real.
Tudo o que o PC estiver tocando (navegador, vídeo, música, jogos) sai pela
Sonos. O modo de baixa latência mede **~0,2 s** de ponta a ponta.

Um HUD flutuante em formato de cápsula, no estilo macOS, fica em um canto da tela —
clique para ligar/desligar, passe o mouse para expandir e acessar o seletor de dispositivos, volume e configurações.

> Originalmente o projeto mirava AirPlay; as Sonos modernas usam AirPlay 2 com
> criptografia obrigatória, que projetos open-source não conseguem transmitir.
> Mudamos para o caminho UPnP nativo da Sonos: contorna a criptografia e ainda
> sai com latência menor.

---

## Como funciona

```
PC system audio (WASAPI loopback)
   → ffmpeg-less raw PCM with a 4 GB WAV header (low-latency)  *or*  ffmpeg MP3
   → local HTTP audio stream at http://<lan-ip>:8009/stream.wav
   → SoCo tells Sonos to play that URL (auto-resolves current group coordinator)
```

- **Descoberta**: `soco` (zeroconf), memorizada pelo **UID** estável — sobrevive a reinícios do roteador.
- **Captura**: `soundcard` (WASAPI loopback — o que o PC está de fato tocando).
- **Streaming**: PCM bruto com um truque de cabeçalho WAV de 4 GB = nenhum buffering do encoder. Há também um caminho via MP3 com ffmpeg para uso com banda baixa.
- **Controle**: `soco.play_uri` com resolução dinâmica do coordenador e retry, de modo que grupos surround (por exemplo, Playbase + 2× Play:One) continuam funcionando quando o coordenador muda.

---

## Latência

| Modo | Medido | Bom para |
|------|--------|----------|
| **Baixa latência (WAV / PCM bruto)** | **~0,2 s** | Vídeo, música, jogos casuais |
| MP3 | ~4 s | Apenas música / podcasts (banda mais baixa) |

O padrão é o caminho de baixa latência. O piso de 0,2 s é o próprio buffer de
sincronização multi-room da Sonos — já no limite do firmware. O modo WAV fica
em torno de 1,4 Mbps, tranquilo em qualquer WiFi doméstico.

---

## Instalação (dev / rodando a partir do código-fonte)

Requer **Python 3.9+** e **ffmpeg** no PATH.

```powershell
# 1. ffmpeg (one-time)
winget install Gyan.FFmpeg

# 2. Clone + enter
git clone git@github.com:hon6/sonosCaster.git
cd sonosCaster

# 3. Virtualenv + deps
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 4. Run
.venv\Scripts\python.exe main.py
```

Ou clique duas vezes em `run.bat`.

---

## Gerar um .exe standalone

O PyInstaller empacota Python + ffmpeg em um único executável de 60 MB que
roda em qualquer PC Windows sem precisar instalar nada.

```powershell
# Drop ffmpeg.exe into bundle/ first (not tracked in git — too large):
#   download from https://www.gyan.dev/ffmpeg/builds/  ->  bundle/ffmpeg.exe

.venv\Scripts\python.exe build.py
# -> dist/SonosCaster.exe
```

---

## Uso

1. A cápsula aparece no canto da tela. Clique no botão de liga/desliga — a descoberta e o encaminhamento começam.
2. Passe o mouse sobre a cápsula para expandir: seletor de dispositivos, volume, configurações e fechar.
3. A cápsula lembra a posição em que foi deixada; arraste clicando e segurando. Perto da
   borda direita da tela ela expande para a **esquerda**, em vez da direita.
4. Na primeira execução, pode aparecer um pedido de administrador para adicionar uma regra de firewall para a porta 8009
   (para que a Sonos consiga puxar o stream). Autorize uma vez.

---

## Solução de problemas

**Nenhuma Sonos encontrada** — o PC e a Sonos precisam estar na mesma LAN / WiFi, sem isolamento de AP.

**Conectou mas não sai som** — confirme que (a) o PC está realmente tocando alguma coisa
agora (o loopback só captura áudio ao vivo), (b) o dispositivo de saída padrão corresponde
ao que está tocando (configurações → fonte de áudio), (c) o firewall libera a porta 8009.

**Erros de grupo surround / "must be called on the coordinator"** — o retry embutido
cuida disso; se não recuperar, desligue e ligue uma vez.

**A Sonos reiniciou, o IP mudou** — funciona automaticamente; os dispositivos são rastreados
pelo UID estável, não pelo IP.

**Quer latência ainda menor** — 0,2 s é o buffer da própria Sonos. Para baixar mais,
é preciso outro transporte (transmissor BT de baixa latência, saída com fio).

---

## Estrutura do projeto

```
.
├── main.py                  # Ponto de entrada
├── run.bat                  # Atalho de um clique
├── build.py                 # Construtor do .exe via PyInstaller
├── requirements.txt
├── LICENSE
├── README.md
├── bundle/
│   └── ffmpeg.exe           # (você baixa — não está no git)
└── sonos_caster/
    ├── capsule.py           # UI da cápsula flutuante (Tkinter + renderização via PIL)
    ├── sonos_caster.py      # Descoberta, resolução do coordenador, play_uri, watchdog
    ├── http_stream.py       # Stream HTTP local de áudio + caminhos WAV/MP3
    ├── capture.py           # WASAPI loopback
    ├── render.py            # Primitivas de UI com anti-aliasing via PIL
    ├── icon.py              # Ícone do app (um "S" no estilo Sonos)
    ├── ffmpeg_util.py       # Localizador do ffmpeg (PATH / bundle do PyInstaller)
    ├── firewall.py          # Helper para a regra de entrada na porta 8009
    ├── sysvolume.py         # Get/set do volume mestre para abaixar enquanto encaminha
    ├── config.py            # Persistência das configurações
    ├── autostart.py         # Helper de registro para iniciar com o Windows
    └── diagnostics.py       # Relatório de diagnóstico embutido (dentro do app)
```

---

## Licença

MIT — veja [LICENSE](LICENSE).

Copyright © 2026 MRHong.
