-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Copyright (C) 2026 Newbiegrader contributors
-- Minimal pre-2026-10 schema used by the CI upgrade test.
-- It intentionally omits traceability columns so schema.sql must add them
-- without losing the existing history row. This file is never run against
-- production; the queue-sql CI job creates a disposable database for it.
create table submissions (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  problem text not null,
  language text not null,
  filename text,
  verdict text not null,
  accepted boolean not null default false,
  passed int not null default 0,
  total int not null default 0,
  score int not null default 0,
  counts jsonb not null default '{}',
  results jsonb not null default '[]',
  code text not null default '',
  detail text not null default ''
);

insert into submissions(problem, language, verdict, accepted, passed, total,
                        score, results, code)
values ('legacy_problem', 'python', 'AC', true, 1, 1, 100, '[]', 'print(1)');

create table profiles (
  user_email text primary key,
  display_name text not null default '',
  default_language text not null default ''
);

create table reports (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  problem text not null,
  kind text not null default 'other',
  message text not null default '',
  user_email text not null default '',
  name text not null default '',
  status text not null default 'open'
);

create table users (
  email text primary key,
  name text not null default '',
  password_hash text not null default '',
  created_at timestamptz not null default now()
);
