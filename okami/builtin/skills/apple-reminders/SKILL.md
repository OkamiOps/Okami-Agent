---
name: apple-reminders
description: Gerencia Apple Reminders pelo terminal via CLI `remindctl` — criar, listar, completar, prazos e alarmes (macOS).
triggers: [apple reminders, reminders.app, me lembra disso, cria um lembrete, lista de lembretes, remindctl, lembrete no icloud]
intent_examples:
  - "cria um lembrete pra ligar pro dentista amanhã"
  - "o que eu tenho pendente nos Reminders hoje"
  - "marca o lembrete 87354 como concluído"
  - "lista os lembretes atrasados"
platforms: [darwin]
metadata:
  hermes:
    tags: [reminders, tasks, todo, apple, macos, icloud]
    category: productivity
    requires_toolsets: [terminal]
---
# Apple Reminders (remindctl CLI)

Gerencia o Reminders.app do macOS pelo terminal usando `remindctl` — as tarefas sincronizam entre
todos os dispositivos Apple via iCloud. Só funciona em macOS com o Reminders.app.

## Dependência

- **macOS** com Reminders.app.
- Instalação: `brew install steipete/tap/remindctl`.
- Permissão do app: checar com `remindctl status`; pedir com `remindctl authorize`.
- Confira que o binário existe antes de usar: `which remindctl`. Se faltar permissão ou instalação,
  avise o usuário do passo necessário em vez de tentar contornar.

## Quando usar

- Usuário menciona "lembrete" ou "Reminders" explicitamente.
- Criar tarefa pessoal com prazo que precisa aparecer no iPhone/iPad também.
- Gerenciar listas do Apple Reminders.

## Quando NÃO usar

- Alerta agendado do próprio agente → use a tool de cronjob do Okami.
- Evento de calendário → Apple Calendar ou Google Calendar, não Reminders.
- Gestão de tarefas de projeto → GitHub Issues, Notion etc.
- Se o usuário disser "me lembra" mas quiser um aviso do próprio agente (não um lembrete que
  sincroniza pro celular), pergunte antes de escolher qual dos dois usar.

## Referência rápida

### Ver lembretes

```bash
remindctl                    # lembretes de hoje
remindctl today               # hoje
remindctl tomorrow            # amanhã
remindctl week                 # essa semana
remindctl overdue              # atrasados
remindctl all                  # tudo
remindctl 2026-01-04            # data específica
```

### Gerenciar listas

```bash
remindctl list                       # lista todas as listas
remindctl list Trabalho              # mostra uma lista específica
remindctl list Projetos --create     # cria lista
remindctl list Trabalho --delete     # apaga lista
```

### Criar lembretes

```bash
remindctl add "Comprar leite"
remindctl add --title "Ligar pra mãe" --list Pessoal --due tomorrow
remindctl add --title "Preparar reunião" --due "2026-02-15 09:00"
```

### Prazo vs alarme

`--due` e `--alarm` são campos diferentes:

- `--due` é o prazo do lembrete.
- `--alarm` é o disparo da notificação. Lembretes com hora costumam herdar um alarme no próprio
  prazo, mas passe `--alarm` explicitamente quando o usuário pedir um aviso antecipado.

Exemplo — prazo às 14h com aviso 30 min antes:

```bash
remindctl add --title "Cabeleireiro" --due "2026-05-15 14:00" --alarm "2026-05-15 13:30"
```

Editar um lembrete existente:

```bash
remindctl edit 87354 --due "2026-05-15 14:00" --alarm "2026-05-15 13:30"
```

A UI do Reminders pode agrupar pelo horário do alarme (é quando a notificação dispara) — não
assuma que o prazo mudou; confira com JSON:

```bash
remindctl today --json
```

Formato esperado: `dueDate` é o prazo real, `alarmDate` é o horário da notificação.

### Completar / apagar

```bash
remindctl complete 1 2 3          # completa por ID
remindctl delete 4A83 --force     # apaga por ID
```

### Formatos de saída

```bash
remindctl today --json       # JSON pra parsing
remindctl today --plain      # formato TSV
remindctl today --quiet      # só contagem
```

## Formatos de data aceitos

Em `--due` e filtros de data: `today`, `tomorrow`, `yesterday`, `YYYY-MM-DD`,
`YYYY-MM-DD HH:mm`, ISO 8601 (`2026-01-04T12:34:56Z`).

## Regras

1. Quando o usuário disser "me lembra", esclareça: Apple Reminders (sincroniza pro celular) vs
   alerta de cronjob do próprio agente.
2. Sempre confirme conteúdo e prazo antes de criar o lembrete.
3. Use `--json` pra parsing programático em vez de tentar ler a saída de texto solta.
