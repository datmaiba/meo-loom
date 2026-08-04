This profile assumes a standalone React SPA with no local backend service in the repo (it talks to a remote/gateway API). Two common local-execution shapes — pick the one that matches the project on first use and delete the other:

**A — commands run inside a long-lived dev container** (no `docker-compose.yml` in this repo; the container is started by separate hosting tooling):

```bash
docker exec <container-name> sh -c "cd /app && npx tsc -b"         # type check (build mode — `tsc --noEmit` on a Vite solution tsconfig checks ZERO files)
docker exec <container-name> sh -c "cd /app && npm test -- --run"  # unit tests
docker exec <container-name> sh -c "cd /app && npx eslint src/"    # lint
docker exec <container-name> sh -c "cd /app && npm run build"     # build
```

If the container is not running: say so and stop — do not fall back to host Node. Do not run `npm`/`npx`/`node` on the host for this project.

**B — commands run directly on the host** (project owns its own `docker-compose.yml`, or has no container requirement):

```bash
npx tsc -b        # build mode — `tsc --noEmit` on a Vite solution tsconfig checks ZERO files
npm test -- --run
npx eslint src/
npm run build     # the only gate that exercises the real browser module graph
```

Adjust container/service names and the exact scripts to this project's `package.json` on first use, and update this section once confirmed.
