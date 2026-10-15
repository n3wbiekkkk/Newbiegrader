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
  user_email text not null default '',
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

-- migration for tables created before the name/user_email columns existed:
alter table submissions add column if not exists name text not null default '';
alter table submissions add column if not exists user_email text not null default '';

create index if not exists submissions_problem_time
  on submissions (problem, created_at desc);

alter table submissions enable row level security;

-- user profiles (display name + defaults, keyed by login email)
create table if not exists profiles (
  user_email text primary key,
  display_name text not null default '',
  default_language text not null default ''
);
alter table profiles enable row level security;

-- problem reports (broken statement/tests)
create table if not exists reports (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  problem text not null,
  kind text not null default 'other',
  message text not null default '',
  user_email text not null default '',
  name text not null default '',
  status text not null default 'open'
);
create index if not exists reports_problem_time
  on reports (problem, created_at desc);
-- user accounts for password login (Google users live in session only)
create table if not exists users (
  email text primary key,
  name text not null default '',
  password_hash text not null default '',
  created_at timestamptz not null default now()
);
alter table users enable row level security;

create index if not exists submissions_user_time
  on submissions (user_email, created_at desc);
create index if not exists submissions_created
  on submissions (created_at desc);

-- ============================================================================
-- Migration 2026-10: hidden-test policy, judge jobs, contests, all-time views.
-- Append-only: safe to re-run in the Supabase SQL Editor.
-- ============================================================================

-- A4: traceability — which test set / judging version scored a submission.
alter table submissions add column if not exists tests_hash text not null default '';
alter table submissions add column if not exists grader_version text not null default '';
alter table submissions add column if not exists kind text not null default 'submit';
alter table submissions add column if not exists contest_id text;
alter table submissions add column if not exists job_id uuid;

create index if not exists submissions_contest_time
  on submissions (contest_id, created_at desc);

-- B9: async judging queue. The web process never judges inline: it inserts a
-- row here, a worker picks it up, and the client polls /api/jobs/{id}.
-- Rows left in `running` by a crash/restart are re-queued on boot.
create table if not exists judge_jobs (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  status text not null default 'queued',   -- queued | running | done | error
  kind text not null default 'submit',     -- submit | rejudge
  user_email text not null default '',
  name text not null default '',
  problem text not null,
  language text not null,
  filename text,
  contest_id text,
  source text not null default '',
  target_id uuid,                          -- rejudge: submission row to overwrite
  result jsonb,
  error text not null default '',
  tests_hash text not null default '',
  grader_version text not null default '',
  reveal text not null default 'samples'    -- all | samples | none (feedback policy)
);
create index if not exists judge_jobs_status_time
  on judge_jobs (status, created_at);
alter table judge_jobs add column if not exists reveal text not null default 'samples';
alter table judge_jobs enable row level security;

-- B7: contests (timed windows + frozen scoreboard).
create table if not exists contests (
  id text primary key,
  created_at timestamptz not null default now(),
  title text not null default '',
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  problems jsonb not null default '[]',
  freeze_minutes int not null default 0,
  show_samples boolean not null default true,
  created_by text not null default ''
);
alter table contests enable row level security;

-- A6: all-time aggregates. The API falls back to a bounded window when these
-- views are missing, which silently drops old rows once data grows — so run
-- this file.
-- `name` = the newest non-empty display name that user used, so the leaderboard
-- never shows "?" for someone who has submissions.
create or replace view leaderboard_scores as
select user_email, problem,
       max(score) as best,
       bool_or(accepted) as accepted,
       max(created_at) as last_at,
       (array_agg(name order by created_at desc)
        filter (where coalesce(name, '') <> ''))[1] as name
from submissions
where user_email <> ''
group by user_email, problem;

create or replace view problem_stats as
select problem,
       count(*) as subs,
       count(*) filter (where accepted) as accepted,
       max(score) as best,
       sum(score) as total_score,
       count(distinct user_email) filter (where accepted) as solvers
from submissions
group by problem;

-- ============================================================================
-- Migration 2026-10b: contest problems can be kept out of the public Task list.
-- Append-only: safe to re-run.
-- ============================================================================

-- true = problems listed in this contest disappear from the public /api/problems
-- (Tasks/Archive) for everyone except admins; they stay listed inside the
-- contest page and in the admin panel. Problems with "hidden": true in their
-- config.json are always kept out of the public list.
alter table contests add column if not exists hide_from_tasks boolean not null default true;

-- ============================================================================
-- Migration 2026-10c: Codeforces-style contests
--   * contest_registrations: who signed up for a contest (Register button)
--   * contest submissions stop counting in the global leaderboard/stats
-- Append-only: safe to re-run.
-- ============================================================================

create table if not exists contest_registrations (
  contest_id text not null,
  user_email text not null,
  name text not null default '',
  registered_at timestamptz not null default now(),
  primary key (contest_id, user_email)
);
alter table contest_registrations enable row level security;

-- Scores earned inside a contest belong to that contest only: keep them out of
-- the all-time views (the contest scoreboard reads submissions directly).
create or replace view leaderboard_scores as
select user_email, problem,
       max(score) as best,
       bool_or(accepted) as accepted,
       max(created_at) as last_at,
       (array_agg(name order by created_at desc)
        filter (where coalesce(name, '') <> ''))[1] as name
from submissions
where user_email <> '' and contest_id is null
group by user_email, problem;

create or replace view problem_stats as
select problem,
       count(*) as subs,
       count(*) filter (where accepted) as accepted,
       max(score) as best,
       sum(score) as total_score,
       count(distinct user_email) filter (where accepted) as solvers
from submissions
where contest_id is null
group by problem;
