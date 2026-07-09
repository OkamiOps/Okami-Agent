# Notion Workers (avançado, requer `ntn`)

Workers são programas TypeScript hospedados pelo Notion. Um worker pode expor qualquer combinação
de:
- **Syncs** — puxam dado de API externa pra um database do Notion numa agenda (default 30 min).
- **Tools** — aparecem como tool chamável dentro de Custom Agents do Notion.
- **Webhooks** — recebem evento HTTP de serviço externo (GitHub, Stripe etc.) e agem no Notion.

**Requisitos de plano/plataforma:**
- A CLI funciona em qualquer plano. **Fazer deploy de Worker exige plano Business ou Enterprise.**
- `ntn` é só mac/Linux — usuário Windows precisa de WSL2 ou esperar suporte nativo.

## Worker mínimo

```bash
ntn workers new meu-worker      # scaffold
cd meu-worker
# edita src/index.ts
ntn workers deploy --name meu-worker
```

`src/index.ts`:
```typescript
import { Worker } from "@notionhq/workers";

const worker = new Worker();
export default worker;

worker.tool("greet", {
  title: "Cumprimenta um usuário",
  description: "Devolve uma saudação amigável",
  inputSchema: { type: "object", properties: { name: { type: "string" } }, required: ["name"] },
  execute: async ({ name }) => `Olá, ${name}!`,
});
```

Segredos de um worker (ex.: assinatura de webhook) ficam com o próprio `ntn workers` — configure
a variável dentro do próprio comando de ambiente do worker (`ntn workers`, subcomando de
configuração — veja `ntn workers --help` na máquina de destino pro nome exato). Nunca escreva o
valor num arquivo desta skill nem cole em uma mensagem de commit.

## Comandos de ciclo de vida do Worker

```bash
ntn workers deploy
ntn workers list
ntn workers exec <capability-key> -d '{"name": "mundo"}'
ntn workers sync trigger <key>            # roda um sync agora
ntn workers sync pause <key>
ntn workers runs list                     # invocações recentes
ntn workers runs logs <run-id>
ntn workers webhooks list
```

Ao construir um Worker: `ntn workers new`, escreva o código em `src/index.ts`, configure a
variável de ambiente do worker pelo próprio `ntn workers` (veja `--help`), faça deploy.
Documentação completa em https://developers.notion.com/workers.
