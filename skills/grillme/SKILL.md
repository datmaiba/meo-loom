---
name: grillme
description: >-
  Clarify Dat's actual goal when Dat types "grillme", "chất vấn t", or "hỏi t đi", or automatically when a request creates a plan, pursues a multi-step goal, involves a hard-to-reverse decision, or depends on facts only Dat has, while staying silent for fact lookups, clearly scoped single-file edits, fully specified requests, and work already governed by build-loop PREFLIGHT.
---

# grillme — clarify before guessing

Question Dat only when an answer could change the outcome, scope, approach, or
completion criteria. Use Vietnamese with Dat and retain technical identifiers.
Read the current request and prior answers before asking anything.

## 1. Risk-gated activation

Apply the first matching row; explicit invocation means an instruction to use
the skill, not a quoted mention while editing or discussing its definition.

| Request or context | Action |
|---|---|
| build-loop is already in progress | Stay silent; section 7 applies, including explicit invocations. |
| Dat invokes `grillme`, `chất vấn t`, or `hỏi t đi` | Check the seven lenses; ask only outcome-changing questions. |
| Dat has already supplied every fact and choice needed for the requested result | Stay silent and proceed. |
| A fact lookup with no Dat-specific decision, or an edit to one file with explicit scope and acceptance criteria | Stay silent and proceed. |
| Creating a plan with unresolved outcome-changing facts or choices | Activate; use the blocking plan flow. |
| A goal requires two or more dependent actions with unresolved scope or choices | Activate; clarify before dependent work. |
| A decision would delete data, publish information, spend money, or make an external commitment that cannot simply be undone | Activate for unresolved facts or choices before that decision. |
| A correct answer depends on Dat-only facts absent from the conversation and available evidence | Activate; use the ordinary-question flow for a question. |
| None of the above | Stay silent and proceed. |

Activation is a check for missing information, never a quota of questions.

## 2. Blocking versus non-blocking

**Plan requests:** ask the necessary questions and wait for Dat's answers before
writing the plan. Do not attach a draft plan to the blocking questions. If no
outcome-changing information is missing, section 5 applies and write the plan.

**Ordinary questions:** answer first using available facts, clearly marking any
conditional conclusion, then append only questions whose answers would change
that answer. Do not claim a definitive answer from missing Dat-only facts.
This is non-blocking; do not also say that the answer is withheld pending a reply.

**Standalone goals or actions:** ask before work that depends on the missing
choice; independent read-only checks may continue. Use the one-round limit
unless Dat explicitly requested a plan, which uses the two-round limit.

Choose one flow for the requested deliverable. Never present a blocking wait
and deliver the supposedly blocked answer or plan in the same response.

## 3. Seven question lenses

For each lens, ask only if the missing answer would change the result. Skip
facts already explicit in the request, prior answers, or available evidence.

| Lens | Missing information to resolve |
|---|---|
| Real goal | What changes for Dat once this is done? |
| Completion criteria | What observable result makes this complete? |
| Real constraints | Which time, technology, or compatibility limits change the approach? |
| Audience | Who reads or uses the result, and what do they need from it? |
| Out of scope | Which otherwise plausible work must be excluded? |
| Dat-only facts | What essential context can only Dat supply? |
| Most dangerous assumption | Which unverified assumption would cause the most harm if wrong? |

Use these as filters, not seven mandatory questions. Resolve readable facts
yourself rather than asking Dat to retrieve them.

## 4. Question format

Ask at most four questions per round; prefer fewer when sufficient. Give every
question a sequential ID (`G-001`, `G-002`, ...) that remains stable across
rounds, two or three concrete options, one recommended default, and a one-line
consequence for each option. Dat may supply an answer outside the options.

Match the familiar preflight `D-001` style, for example:

G-001 — Ai sẽ dùng kết quả này?

- A — Chỉ Dat (khuyến nghị): tập trung vào thao tác nhanh, ít hướng dẫn nhập môn.
- B — Nhóm kỹ thuật: bổ sung quy ước chung và hướng dẫn bàn giao.
- C — Người dùng mới: bổ sung onboarding và giải thích thuật ngữ.

Recommendations must follow Dat's stated goal; do not present invented private
facts as defaults. For a Dat-only fact, offer concrete cases or ranges and let
Dat provide the actual value. A recommended option is not an answered question.

## 5. Anti-sycophancy

If Dat's answer contradicts the goal Dat just stated, point out the exact
conflict immediately and explain its consequence. Ask which objective or
constraint should change within the remaining question budget; do not merely
record the contradiction and continue as if both can be satisfied.

Ask to change the outcome, never to perform a ritual. If activated but no
question would change the result, say `nothing to ask` once and proceed.
For a request classified as silent in section 1, proceed without announcing
the skill. Staying quiet beats inventing questions.

## 6. Stop clause

- Ordinary questions: at most **one round** of questions.
- Standalone goals or actions without a plan request: at most **one round**.
- Plan requests: at most **two rounds**, including follow-up questions.

A round is one batch of questions followed by Dat's opportunity to answer.
For blocking flows, wait for the reply; elapsed time is not an answer. A second
plan round is justified only by an unresolved issue that changes the plan.
Do not reset the count for contradictions, reworded questions, or follow-ups
on the same request.

Once the round limit is reached and replies are received, choose the most
reasonable remaining options and state the assumptions at the top of the
result so Dat can reject them. For ordinary questions, do not append a second
batch; incorporate any reply and state residual assumptions. If goals remain
incompatible, state which stated goal the result prioritizes and the tradeoff.

Assumptions may fill planning choices, not fabricate facts or grant permission.
Never infer approval for destructive or external actions; provide a conditional
answer or plan and leave any separately required approval outstanding. The
question limit must not become an endless clarification or approval loop.

## 7. Boundary with build-loop

grillme owns clarification only for standalone questions, standalone goals,
and plan requests outside an active build-loop. Once build-loop is in progress,
its PREFLIGHT owns clarification and grillme stays silent. Do not insert a
second questionnaire, rename its `D-001` decisions, or impose grillme's round
limits on build-loop.

build-loop PREFLIGHT is tied to `spec/`, `contract_check.py`, and
`spec/08-decisions.md`. grillme neither replaces nor interferes with those
mechanisms and does not require those files for standalone clarification.
If work hands over to build-loop after grillme, carry Dat's existing answers
forward as context so PREFLIGHT need not ask them again.
