-- Supabase schema for Newbiegrader submission history.
-- Run once in Supabase Dashboard -> SQL Editor -> New query.
-- Backend uses the service_role key, so no public policies are created
-- (RLS enabled with zero policies = only service_role can access).

create table if not exists submissions (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  problem text not null,
  language text not null,
  filename text,
  name text not null default '',
  verdict text not null,                 -- AC / REJECTED / CE
  accepted boolean not null default false,
  passed int not null default 0,
  total int not null default 0,
  score int not null default 0,
  counts jsonb not null default '{}',
  results jsonb not null default '[]',   -- per-test verdicts + diffs
  code text not null default '',
  detail text not null default ''        -- compile error / misc
);

-- migration for tables created before the name column existed:
alter table submissions add column if not exists name text not null default '';

create index if not exists submissions_problem_time
  on submissions (problem, created_at desc);

alter table submissions enable row level security;
