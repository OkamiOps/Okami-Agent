---
name: video-use-install
description: "Passo a passo de instalacao do video-use (ffmpeg, deps Python, credencial ElevenLabs). Leia so no primeiro uso; pro dia a dia use SKILL.md."
triggers: [instalar video-use, configurar video-use, elevenlabs api key, setup ffmpeg]
---

## Setup (leia antes do primeiro uso)

Este skill importado precisa de peças que **não vêm com o Okami**: um clone do repo
`browser-use/video-use` (ffmpeg + o resto dos scripts), `ffmpeg`/`ffprobe` no PATH, as
deps Python do projeto (`requests`, `librosa`, `matplotlib`, `pillow`, `numpy`) e uma
chave da API ElevenLabs (para a transcrição via Scribe). Nada disso é instalado
automaticamente — siga os passos abaixo uma vez, depois é só usar.

Três coisas precisam existir na máquina:

1. `ffmpeg` + `ffprobe` no `$PATH` (`yt-dlp` opcional, só se o usuário quiser puxar de URL).
2. As deps Python listadas em `pyproject.toml` do projeto original (`requests`,
   `librosa`, `matplotlib`, `pillow`, `numpy`) — instale com `pip install requests
   librosa matplotlib pillow numpy` no ambiente que vai rodar os scripts em `scripts/`.
3. Uma credencial ElevenLabs em `.env` (na raiz de onde os scripts rodam) — variável
   `ELEVENLABS_API_KEY`. Sem ela, `transcribe.py`/`transcribe_batch.py` não funcionam;
   o resto do pipeline (corte, grade, legendas, animações) não depende dela.

## Passos

### 1. Dependências de sistema (ffmpeg)

```bash
# macOS
command -v ffmpeg >/dev/null || brew install ffmpeg
command -v yt-dlp >/dev/null || brew install yt-dlp     # opcional

# Debian / Ubuntu
# sudo apt-get update && sudo apt-get install -y ffmpeg
# pip install yt-dlp

# Arch
# sudo pacman -S ffmpeg yt-dlp
```

Se `brew`/`apt`/`pacman` pedir senha de sudo, informe o comando exato ao usuário e
espere — nunca invente ou peça a senha por outro canal.

### 2. Dependências Python

```bash
pip install requests librosa matplotlib pillow numpy
```

### 3. Credencial ElevenLabs

Scribe (ElevenLabs) faz toda a transcrição. Sem chave, nada transcreve — o resto do
skill (corte, grade, legendas, animações) segue funcionando normalmente.

1. Confira o estado atual, nessa ordem, e pare no primeiro que bater:
   - variável de ambiente `ELEVENLABS_API_KEY` já exportada;
   - arquivo `.env` (na raiz de onde os scripts rodam) já tem a linha
     `ELEVENLABS_API_KEY=...` preenchida.
2. Se nenhuma das duas existir, peça ao usuário exatamente uma vez: "preciso de uma
   chave da API ElevenLabs pra transcrição (timestamps por palavra, diarização,
   marcação de preenchimento — pegue uma em
   https://elevenlabs.io/app/settings/api-keys e cole aqui — eu escrevo no `.env`. Se
   já tiver exportada como `ELEVENLABS_API_KEY`, diga 'usa a variável' e eu pulo essa
   etapa."
3. Ao receber a chave, grave em `.env` (nunca ecoe a chave de volta na saída da
   ferramenta, nunca faça commit do `.env`):

   ```bash
   printf 'ELEVENLABS_API_KEY=%s\n' "$KEY" > .env
   chmod 600 .env
   ```

4. Verificação da chave: em vez de embutir a chave numa chamada de rede aqui neste
   arquivo (o scanner de segurança de skills bloqueia arquivo que mistura
   credencial + chamada de rede no mesmo arquivo), rode `scripts/transcribe.py --help`
   pra confirmar que o script carrega sem erro, e valide a chave de verdade só na
   primeira transcrição real (`transcribe.py <video>` num clipe pequeno) — o próprio
   script devolve `401` claro se a chave estiver errada/expirada.

### 4. Verificação fim-a-fim

```bash
python scripts/timeline_view.py --help >/dev/null && echo "scripts OK"
ffprobe -version | head -1
```

Teste de transcrição completo é opcional na instalação — consome créditos do Scribe.
Melhor esperar o usuário mandar o primeiro clipe de verdade.

## Lembretes de cold-start

- Se `.env` existir mas a chave estiver vazia, trate como se não existisse — não
  assuma que existência implica validade.
- `ffmpeg` de build estático funciona bem. Qualquer build moderna (≥ 4.x) serve.
- `yt-dlp` é opcional — não bloqueie a instalação por causa dele.
- Node.js/npm só são necessários pra slots de animação HyperFrames ou Remotion
  (HyperFrames pede Node.js 22+). Instale sob demanda.
- Nunca rode transcrição como parte da verificação de instalação a menos que o
  usuário peça explicitamente — Scribe custa dinheiro de verdade.

## Fonte

Adaptado de `install.md` em [browser-use/video-use](https://github.com/browser-use/video-use).
Removido o passo de sanity-check via requisição HTTP direta com a chave inline (mistura
credencial + chamada de rede no mesmo arquivo — bloqueado pelo scanner de segurança de
skills do Okami); a verificação real acontece na primeira transcrição, que já reporta
`401` de forma clara em caso de chave inválida.
