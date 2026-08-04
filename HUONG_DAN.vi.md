# MeoLoom — Hướng dẫn tiếng Việt

Toolkit kỷ luật làm việc spec-driven cho AI coding agent. Cài 1 lệnh, agent có ngay vòng lặp làm việc trọn bộ: nghĩ trước khi code, plan trước khi build, verify trước khi báo xong, đúc kết bài học sau khi ship. MeoLoom là open platform: 1 engine host-neutral, các Domain Pack theo ngành, và registry sinh ra mọi bề mặt host-facing.

> Trạng thái: **MeoLoom 3.0 public release**. Repository này bắt đầu từ clean root đã audit; lịch sử maintenance private trước đó không nằm trong bản public.

## Kiến trúc (từ 2.0)

| Tầng | Vị trí | Sở hữu gì |
|---|---|---|
| **Work-loop engine** | `engine/work-loop/` | Máy phase host-neutral (LOAD → SELF-QUESTION → PLAN → BUILD → VERIFY → REVIEW → HARVEST). Không chứa kiến thức ngành. |
| **Domain Pack** | `domains/<id>/` | Một *loại công việc* nghĩa là gì, qua contract 6 slot: workflow · ground-truth · gates · reviewers · deliverables · loop-profile. Có sẵn: `software-dev` (chủ lực), `knowledge-work` (pack ngoài-dev đầu tiên). |
| **Registry + projection** | `registry/`, `scripts/render.py` | Descriptor là nguồn sự thật duy nhất. Trigger skill mỏng dưới `skills/` và scaffold greenfield đều được *sinh ra* (generated), CI byte-check bằng `render.py --check`. |

Project được scaffold mang contract canonical duy nhất: `AGENTS.md` gốc, revision **`MeoLoom 3.0`** (revision xanh duy nhất). `dat-kit 2.0` và `dat-kit 1.16.0` là nguồn migration được công nhận: checker fail-closed với `CONTRACT_MIGRATION_REQUIRED` kèm plan migration read-only, deterministic. File runtime (`CLAUDE.md`, `.cursor/rules/*.mdc`…) chỉ là pointer, không bao giờ chứa policy.

## Hỗ trợ host

Mọi claim về host đều có nguồn official (verified 2026-07-18, ghi trong `registry/adapters.json`): **Claude Code** `scaffold_active` (2 pointer file import `AGENTS.md`, hook SessionStart) · **Codex** `repo_only` (đọc `AGENTS.md` native, KHÔNG cần pointer — xem `adapters/codex/ADAPTER.md`) · **Cursor** `migration_ready` (`.cursorrules` deprecated → thay bằng `.cursor/rules/meo-loom.mdc` chỉ qua migration plan đã duyệt) · **Gemini CLI** `repo_only` (chưa chạy live). Smoke live trên host là gate của maintainer, checklist trong từng `ADAPTER.md`.

## Cài đặt

```
/plugin marketplace add datmaiba/meo-loom
/plugin install meo-loom@meo-loom
```

Dev/test local từ folder: `claude --plugin-dir /đường/dẫn/meo-loom`

**Codex:**

```bash
codex plugin marketplace add datmaiba/meo-loom
codex plugin add meo-loom@meo-loom
```

Chi tiết theo host (setup, giới hạn, migration): xem [`adapters/codex/ADAPTER.md`](adapters/codex/ADAPTER.md) (trước đây là `docs/codex.md`).

## Có gì bên trong

| Thành phần | Công dụng |
|---|---|
| `/meo-loom:project-init` | Scaffold project mới (hoặc `--here` cho repo sẵn có): `AGENTS.md` canonical `MeoLoom 3.0` + pointer adapters, skeleton `spec/00→08`, shared agent docs, lessons-learned + `CONTEXT.md` |
| `/meo-loom:build-loop` | Trigger sinh từ registry, load pack `software-dev` + engine. Vòng lặp build: load context → tự chất vấn theo spec → plan → **chờ duyệt** → build → chạy gates → review độc lập → đúc kết bài học. Autopilot: PREFLIGHT gom mọi câu hỏi thành 1 lần duyệt duy nhất. Delegated-build: session chính làm orchestrator, mỗi task 1 builder subagent mới + review 2 bước |
| `/meo-loom:knowledge-work` | Trigger cho pack `knowledge-work` — research, viết, phân tích: bám nguồn primary, gate citation/fidelity, fact-check độc lập. Trần Goal loop (gate chủ lực cần người đóng) |
| `/meo-loom:domain-builder` | Phỏng vấn người hành nghề thật và mã hoá kỷ luật của HỌ thành Domain Pack 6 slot, đăng ký qua registry. Bắt buộc gate-validity; trần Turn/Goal cho domain phỏng vấn |
| `/meo-loom:handoff` | Nén session đang dở thành file bàn giao trong `handoffs/` — session mới (hoặc máy khác) đọc là tiếp tục được ngay |
| `/meo-loom:scorecard` | Chấm điểm task: rubric 1-5 cố định, ước lượng giờ-tay (dán nhãn estimate), thời gian thật, gates — ghi vào `benchmarks/scorecard.jsonl`. Build-loop tự gọi cuối mỗi phase |
| 4 agents | `plan-reviewer`, `qa-agent`, `code-reviewer`, `security-reviewer` — builder không bao giờ tự chấm bài mình |
| SessionStart hook | Tự inject kỷ luật làm việc vào đầu mọi session (Claude Code) |
| `scripts/statusline.py` | Hiện token sau MỖI câu lệnh trên statusline Claude Code. Setup 1 lần: `python3 scripts/statusline.py --install` |

(Các skill khác: `diagnosing-bugs`, `improve-codebase-architecture`, `git-worktrees`, `fable-mode`/`fable-pro`, `guardian-builder`, `cookbook-lookup`, `terse-mode` — xem README.)

## Dùng hằng ngày

**Project mới:**

```
/meo-loom:project-init          → trả lời tên/mô tả/stack → có skeleton
(điền spec/ theo thứ tự 00 → 04, quan trọng nhất là non-goals và build phases)
/meo-loom:build-loop phase 0    → hoặc: "run build-loop autopilot from phase 0"
```

**Repo sẵn có:** `bash scripts/init.sh --here` (preflight read-only, không bao giờ ghi đè file đang có), rồi `/meo-loom:guardian-builder` để sinh rules riêng từ convention thật của repo.

## Nguyên tắc cốt lõi

- **Spec là luật** — agent tự trả lời câu hỏi từ spec (kèm citation), chỉ hỏi user cái spec không trả lời được.
- **1 điểm duyệt duy nhất** — PREFLIGHT gom hết quyết định lên đầu, ghi vào `spec/08-decisions.md`; autopilot chỉ dừng cho câu hỏi high-severity (secrets, xoá data, lệch spec, tốn tiền, public contract).
- **Review độc lập** — subagent tươi audit plan, tấn công feature bằng edge case, soi diff.
- **Bằng chứng thay lời hứa** — phase chưa xanh gates + demo chưa chạy = chưa xong; báo cáo ghi kết quả cụ thể ("pest 24/24 ✓"), cấm "mọi thứ đều ổn".
- **Sinh ra, không drift tay** — bề mặt host-facing là projection từ registry descriptor, CI byte-check; sửa tay file generated là lỗi build, không phải đóng góp.
- **Bài học cộng dồn** — mỗi lần bị sửa thành 1 entry lessons-learned mà session sau bắt buộc đọc.

## Bảo trì

### Quy trình update plugin (làm đúng thứ tự, mỗi lần sửa bất kỳ thứ gì)

1. Sửa file — KHÔNG sửa tay file generated; sửa registry descriptor rồi chạy `python scripts/render.py`
2. `python scripts/validate.py` — phải "all checks green"; `python scripts/render.py --check` phải exit 0
3. Bump `release_version` trong `registry/platform.json`; 3 version target mirror (`.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`) phải khớp — validator tự bắt. Chỉ sửa `.agents/plugins/marketplace.json` khi source metadata đổi
4. `git add -A && git commit && git push` — tab Actions trên GitHub phải xanh (job Ubuntu + Windows)
5. Trong Claude Code: `/plugin` → Marketplaces → update MeoLoom → tab Installed hiện version mới. Codex: reinstall từ marketplace đã cấu hình
6. Mở session MỚI — session đang chạy vẫn dùng bản cũ đã nạp lúc khởi động

**Nguyên tắc thứ tự**: sửa tool trước, dùng tool sau — thay đổi MeoLoom rẻ hơn phase build; đừng chạy phase dài trên tool có bug đã biết.

### Thêm stack profile mới

Tạo `templates/profiles/<tên>/` với 3 file `architecture.md`, `gates.md`, `traps.md` — chỉ thêm khi đã thực chiến stack đó, đừng viết chay.

## Adopt repo brownfield an toàn

`bash scripts/init.sh --here` cần Python và chạy preflight read-only trước mọi
`mkdir`, copy hay sửa file. Nếu có `AGENTS.md` cạnh tranh, pointer chứa policy,
contract legacy, symlink không an toàn, hoặc partial install không tương thích,
script trả diagnostic có tên và dừng mà không đổi cây thư mục. Project
`dat-kit 2.0` hoặc `dat-kit 1.16.0` sẽ nhận
`CONTRACT_MIGRATION_REQUIRED`; tạo plan migration
deterministic và read-only trước khi sửa:

```bash
python "<MEOLOOM_ROOT>/scripts/contract_check.py" --target . --migration-plan
```

Plan vẫn exit khác 0 khi còn drift và không tự sửa file. Review, duyệt plan,
rồi mới apply: policy tự thêm của project được merge có heading provenance vào
file project-owned (`docs/agent-working-rules.md`), không bao giờ bị byte-replace.
Chạy lại checker đến exit 0.

Cam kết không drift chỉ áp dụng cho installation đã pass checker. Plugin đã cài
và session đang mở vẫn giữ metadata cũ cho đến khi update/reinstall và mở session
mới.
