All commands via docker compose — never host binaries:

```bash
docker compose exec api php artisan test          # Pest
docker compose exec api ./vendor/bin/pint         # PHP lint/format
docker compose exec web npx vitest run            # frontend tests
docker compose exec web npx tsc -b                # type check (build mode — `tsc --noEmit` on a Vite solution tsconfig checks ZERO files and stays green forever)
docker compose exec web npm run build             # tsc -b + vite build — the only gate that exercises the real browser module graph (vitest is blind to missing ESM exports)
docker compose exec api php artisan migrate
```

If a container is not running: say so and stop — do not fall back to host PHP/Node. Adjust service names to this project's `docker-compose.yml` on first use and update this section.
