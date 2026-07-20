# Implantação controlada da Lex — homologação

## Estado

Este documento é um runbook. Não representa deploy executado.

- Ambiente-alvo: homologação.
- Componentes: `lex-process-researcher` e `lex-api-gateway-runtime`.
- Produção: fora do escopo até aprovação A4 específica.
- Segredos: nunca no Git, compose ou chat.

## Pré-voo obrigatório

1. Confirmar a VPS e o projeto Docker de homologação.
2. Criar snapshot/backup da VPS ou do projeto existente.
3. Confirmar que a porta `${LEX_GATEWAY_PORT:-18090}` está livre.
4. Confirmar conectividade do gateway com o Search Core.
5. Definir no cofre:
   - `LEX_API_KEY`;
   - `DATAJUD_API_KEY`, quando não for usada descoberta oficial;
   - `LEX_UPSTREAM`.
6. Validar o compose:

```bash
docker compose --env-file .env.homolog -f docker-compose.homolog.yml config
```

7. Registrar os commits efetivos usados no build.

## Subida em homologação

```bash
docker compose   --env-file .env.homolog   -f docker-compose.homolog.yml   up -d --build
```

## Testes internos

```bash
docker compose -f docker-compose.homolog.yml ps

curl --fail --silent   http://127.0.0.1:${LEX_GATEWAY_PORT:-18090}/health

curl --fail --silent   -H "Authorization: Bearer [CREDENCIAL_DO_COFRE]"   http://127.0.0.1:${LEX_GATEWAY_PORT:-18090}/v1/datajud/health
```

A credencial deve ser inserida diretamente no ambiente seguro de teste, nunca salva em histórico de shell compartilhado.

## Critérios de aceite

- os dois containers estão `healthy`;
- `/health` retorna `status: ok`;
- `/v1/readiness` informa `process_upstream_configured: true`;
- `/v1/datajud/health` não retorna segredo;
- `human_review_required` é `true`;
- `no_invention_policy` é `true`;
- uma consulta com CNJ inválido é rejeitada ou retorna estado controlado;
- logs não contêm credenciais;
- rate limit responde `429` quando excedido;
- reinício de container não perde configuração.

## Rollback

```bash
docker compose -f docker-compose.homolog.yml down
```

Se houver uma versão anterior:

1. restaurar o compose/imagem anterior;
2. subir novamente;
3. executar `/health`;
4. registrar o motivo e a evidência do rollback.

Em caso de alteração de infraestrutura, preferir restauração do snapshot criado no pré-voo.

## Evidências mínimas

- ID do projeto Docker;
- snapshot/backup;
- commits efetivos;
- saída sanitizada de `docker compose ps`;
- respostas sanitizadas de health/readiness;
- data e hora;
- responsável pela aprovação;
- resultado do pós-teste.

## Promoção para produção

Exige autorização A4 específica com:

- alvo exato;
- versão/commits;
- janela de mudança;
- backup;
- plano de rollback;
- pós-teste;
- confirmação explícita de publicação.
