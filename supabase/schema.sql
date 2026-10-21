-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Copyright (C) 2026 Newbiegrader contributors
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

-- ============================================================================
-- Migration 2026-10-15: opt-in coordinated judge queue. Apply before enabling
-- GRADER_QUEUE_MODE=database. Every RPC is restricted to the backend service role.
-- Local queue mode remains single-process; do not mix modes against this table.
-- ============================================================================
alter table public.judge_jobs add column if not exists payload jsonb not null default '{}';
alter table public.judge_jobs add column if not exists track_active boolean not null default true;
alter table public.judge_jobs add column if not exists worker_id text;
alter table public.judge_jobs add column if not exists attempt integer not null default 0;
alter table public.judge_jobs add column if not exists lease_until timestamptz;
alter table public.judge_jobs add column if not exists submission_id uuid;
-- The rollout stops the legacy local consumer first. It had no lease/owner;
-- initialize only those orphan rows, never disturb an active leased worker.
update public.judge_jobs set lease_until=now()
  where status='running' and worker_id is null and attempt=0 and lease_until is null;
create index if not exists judge_jobs_lease on public.judge_jobs (lease_until) where status = 'running';
create index if not exists judge_jobs_active_user on public.judge_jobs (user_email)
  where status in ('queued', 'running') and track_active;
create table if not exists public.judge_quota_events (
  user_email text not null, kind text not null, admitted_at timestamptz not null default now()
);
create index if not exists judge_quota_window on public.judge_quota_events (user_email, kind, admitted_at);
alter table public.judge_quota_events enable row level security;
revoke all on public.judge_quota_events from public, anon, authenticated;
grant all on public.judge_quota_events to service_role;

create or replace function public.judge_queue_admit(
  p_job jsonb, p_queue_max integer, p_track_active boolean,
  p_quota_limit integer, p_quota_window integer
) returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_job public.judge_jobs; v_email text := coalesce(p_job->>'user_email', '');
  v_kind text := coalesce(p_job->>'kind', 'submit'); v_quota_kind text;
  v_first timestamptz; v_count integer;
begin
  -- Serialize admission across API replicas: queue and account checks plus insert
  -- form one transaction. A check in Python cannot provide this guarantee.
  perform pg_advisory_xact_lock(64723487231);
  if p_track_active and v_email <> '' and exists (
    select 1 from public.judge_jobs where user_email=v_email and track_active
      and status in ('queued','running')
  ) then
    return jsonb_build_object('error','you already have a submission judging, please wait','status_code',409);
  end if;
  if (select count(*) from public.judge_jobs where status='queued') >= p_queue_max then
    return jsonb_build_object('error','judge queue is full — try again in a moment','status_code',503,'retry_after',30);
  end if;
  v_quota_kind := case when v_kind='playground' then 'run' else 'submit' end;
  if p_quota_limit > 0 and p_quota_window > 0 and v_email <> '' then
    delete from public.judge_quota_events where admitted_at < now() - interval '7 days';
    select count(*), min(admitted_at) into v_count, v_first from public.judge_quota_events
      where user_email=v_email and kind=v_quota_kind
        and admitted_at > now() - make_interval(secs => p_quota_window);
    if v_count >= p_quota_limit then
      return jsonb_build_object('error','quota exceeded','status_code',429,
        'retry_after',greatest(1,ceil(extract(epoch from v_first + make_interval(secs => p_quota_window)-now()))::integer));
    end if;
    insert into public.judge_quota_events(user_email,kind) values(v_email,v_quota_kind);
  end if;
  insert into public.judge_jobs (id,kind,user_email,name,problem,language,filename,contest_id,
      source,target_id,reveal,tests_hash,grader_version,payload,track_active)
    values(coalesce((p_job->>'id')::uuid,gen_random_uuid()),v_kind,v_email,
      coalesce(p_job->>'name',''),coalesce(p_job->>'problem',''),coalesce(p_job->>'language',''),
      p_job->>'filename',p_job->>'contest_id',coalesce(p_job->>'source',''),
      (p_job->>'target_id')::uuid,coalesce(p_job->>'reveal','samples'),
      coalesce(p_job->>'tests_hash',''),coalesce(p_job->>'grader_version',''),
      coalesce(p_job->'payload','{}'::jsonb),p_track_active)
    returning * into v_job;
  return jsonb_build_object('job',to_jsonb(v_job));
end $$;

create or replace function public.judge_queue_claim(p_worker text,p_lease_seconds integer)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_job public.judge_jobs;
begin
  update public.judge_jobs set status='error',error='stale job dropped',finished_at=now()
    where status='queued' and created_at < now() - interval '24 hours';
  select * into v_job from public.judge_jobs
    where status='queued' or (status='running' and lease_until <= now())
    order by (kind='rejudge'), created_at, id for update skip locked limit 1;
  if not found then return null; end if;
  update public.judge_jobs set status='running',worker_id=p_worker,attempt=attempt+1,
      started_at=now(),lease_until=now()+make_interval(secs=>greatest(1,p_lease_seconds)),
      error='',finished_at=null
    where id=v_job.id returning * into v_job;
  return to_jsonb(v_job);
end $$;

create or replace function public.judge_queue_heartbeat(
  p_id uuid,p_worker text,p_attempt integer,p_lease_seconds integer
) returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  update public.judge_jobs set lease_until=now()+make_interval(secs=>greatest(1,p_lease_seconds))
    where id=p_id and status='running' and worker_id=p_worker and attempt=p_attempt and lease_until>now();
  return found;
end $$;

create or replace function public.judge_queue_finish(
  p_id uuid,p_worker text,p_attempt integer,p_result jsonb,p_submission jsonb,p_error text
) returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare v_job public.judge_jobs; v_id uuid; v_sub public.submissions;
begin
  select * into v_job from public.judge_jobs where id=p_id for update;
  if not found or p_worker is null or p_attempt is null
      or v_job.worker_id is distinct from p_worker or v_job.attempt is distinct from p_attempt then
    return jsonb_build_object('applied',false);
  end if;
  if v_job.status in ('done','error') then
    return jsonb_build_object('applied',true,'submission_id',v_job.submission_id);
  end if;
  if v_job.status <> 'running' or v_job.lease_until is null or v_job.lease_until <= now() then
    return jsonb_build_object('applied',false);
  end if;
  -- History and terminal status commit together under the attempt fence.
  if p_submission is not null and coalesce(p_error,'')='' then
    v_sub := jsonb_populate_record(null::public.submissions,p_submission);
    if v_job.target_id is not null then
      update public.submissions set verdict=v_sub.verdict,accepted=v_sub.accepted,
        passed=v_sub.passed,total=v_sub.total,score=v_sub.score,counts=v_sub.counts,
        results=v_sub.results,detail=v_sub.detail,tests_hash=v_sub.tests_hash,
        grader_version=v_sub.grader_version,kind=v_sub.kind,job_id=p_id
        where id=v_job.target_id returning id into v_id;
    else
      insert into public.submissions(problem,language,filename,name,user_email,verdict,accepted,
        passed,total,score,counts,results,code,detail,tests_hash,grader_version,kind,contest_id,job_id)
      values(v_sub.problem,v_sub.language,v_sub.filename,coalesce(v_sub.name,''),coalesce(v_sub.user_email,''),
        v_sub.verdict,coalesce(v_sub.accepted,false),coalesce(v_sub.passed,0),coalesce(v_sub.total,0),
        coalesce(v_sub.score,0),coalesce(v_sub.counts,'{}'::jsonb),coalesce(v_sub.results,'[]'::jsonb),
        coalesce(v_sub.code,''),coalesce(v_sub.detail,''),coalesce(v_sub.tests_hash,''),
        coalesce(v_sub.grader_version,''),coalesce(v_sub.kind,'submit'),v_sub.contest_id,p_id)
      returning id into v_id;
    end if;
  end if;
  update public.judge_jobs set status=case when coalesce(p_error,'')='' then 'done' else 'error' end,
    result=case when p_result is null then null else p_result || jsonb_build_object('id',v_id) end,
    error=coalesce(p_error,''),finished_at=now(),lease_until=null,submission_id=v_id,
    -- The submission row owns the validated source. Terminal jobs need only
    -- the result; retaining source/payload would duplicate user code and
    -- playground input indefinitely in the queue table.
    source='',payload='{}'::jsonb where id=p_id;
  return jsonb_build_object('applied',true,'submission_id',v_id);
end $$;

create or replace function public.judge_queue_diagnostics() returns jsonb
language sql security definer set search_path = pg_catalog, public as $$
  select jsonb_build_object('queued',count(*) filter(where status='queued'),
    'running',count(*) filter(where status='running')) from public.judge_jobs;
$$;

revoke all on function public.judge_queue_admit(jsonb,integer,boolean,integer,integer) from public,anon,authenticated;
revoke all on function public.judge_queue_claim(text,integer) from public,anon,authenticated;
revoke all on function public.judge_queue_heartbeat(uuid,text,integer,integer) from public,anon,authenticated;
revoke all on function public.judge_queue_finish(uuid,text,integer,jsonb,jsonb,text) from public,anon,authenticated;
revoke all on function public.judge_queue_diagnostics() from public,anon,authenticated;
grant execute on function public.judge_queue_admit(jsonb,integer,boolean,integer,integer) to service_role;
grant execute on function public.judge_queue_claim(text,integer) to service_role;
grant execute on function public.judge_queue_heartbeat(uuid,text,integer,integer) to service_role;
grant execute on function public.judge_queue_finish(uuid,text,integer,jsonb,jsonb,text) to service_role;
grant execute on function public.judge_queue_diagnostics() to service_role;

-- ============================================================================
-- 2026-10: contest announcements (organizer clarifications during a round).
-- Admins post via POST /api/contests/{cid}/announcements; everyone reads once
-- the contest has started (before the start only admins see them, since they
-- may hint at problems). Missing table = feature off (empty list), never fatal.
-- Append-only: safe to re-run.
-- ============================================================================

create table if not exists contest_announcements (
  id uuid not null primary key,
  contest_id text not null,
  body text not null default '',
  created_by text not null default '',
  created_at timestamptz not null default now()
);
create index if not exists contest_announcements_contest_time
  on contest_announcements (contest_id, created_at);
alter table contest_announcements enable row level security;

-- ============================================================================
-- 2026-10-15: history/leaderboard read path (API perf).
-- GET /api/history orders by created_at with optional problem/user_email
-- filters; the aggregates read via leaderboard_scores/problem_stats views.
-- Apply with the rest of this file in the Supabase SQL Editor.
-- Append-only: safe to re-run.
-- ============================================================================
create index if not exists submissions_history_filter
  on submissions (user_email, problem, created_at desc);

-- ============================================================================
-- 2026-10-16: problem storage migration (local problems/ -> Supabase).
-- Queryable metadata + public statements live in Postgres; hidden test FILES
-- live in the private `judge-assets` Storage bucket (never in public rows).
-- Append-only: safe to re-run in the Supabase SQL Editor.
--
-- Local format mapped here (see tools/import_problems_supabase.py):
--   problems/<slug>/config.json -> slug/no/title/limits/checker/tolerance/
--     difficulty/tags/samples/hidden
--   problems/<slug>/statement.md -> statement_md (public)
--   problems/<slug>/tests/<name>.in/.out where <name> in samples ->
--     samples_data (public JSON, served by the API)
--   problems/<slug>/tests/<name>.in/.out where <name> NOT in samples ->
--     hidden_tests manifest ONLY (name/sha256/sizes, no contents) +
--     bytes in Storage at <slug>/tests/<name>.in(.out)
--   problems/<slug>/statement.pdf -> Storage at <slug>/statement.pdf
--     (row keeps statement_pdf_path, never a public URL)
-- ============================================================================

create table if not exists problems (
  slug text primary key,
  no int unique not null,
  title text not null default '',
  time_limit double precision not null default 1.0,
  memory_limit int not null default 256,
  checker text not null default 'token',
  tolerance double precision not null default 1e-6,
  difficulty text not null default '',
  tags jsonb not null default '[]',
  samples jsonb not null default '[]',
  samples_data jsonb not null default '[]',
  statement_md text not null default '',
  tests_hash text not null default '',
  tests_count int not null default 0,
  hidden_tests jsonb not null default '[]',
  hidden boolean not null default false,
  is_published boolean not null default true,
  statement_pdf_path text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists problems_no_idx on problems (no);
create index if not exists problems_published_idx on problems (is_published, hidden);
alter table problems enable row level security;

-- Least privilege: backend uses service_role (bypasses RLS). Direct
-- anon/authenticated reads are limited to published, non-hidden problems
-- (public metadata + statement + SAMPLE contents only; hidden test contents
-- are never stored in this table, only their manifest).
revoke all on problems from public, anon, authenticated;
grant select on problems to anon, authenticated;
grant all on problems to service_role;
drop policy if exists problems_public_read on problems;
create policy problems_public_read on problems
  for select to anon, authenticated
  using (is_published = true and hidden = false);

-- Private Storage bucket for hidden tests + PDFs. Only service_role may
-- touch it: no anon/authenticated storage.objects policies are created for
-- this bucket, and no public URLs are ever issued (backend streams bytes).
-- Guarded so vanilla Postgres CI (no storage schema) still applies this file.
do $$
begin
  if exists (select 1 from information_schema.schemata where schema_name = 'storage') then
    insert into storage.buckets (id, name, public)
    values ('judge-assets', 'judge-assets', false)
    on conflict (id) do nothing;
  end if;
end
$$;

-- ============================================================================
-- 2026-10-17: judge hot-path indexes (optimize batch).
-- Additive only, safe to re-run. Apply in Supabase SQL Editor.
-- Covers leaderboard/problem_stats GROUP BY with contest_id IS NULL,
-- contest scoreboard per contest_id, and judge_jobs claim/admit scans.
-- ============================================================================
create index if not exists submissions_leaderboard_cover
  on submissions (contest_id, user_email, problem);
create index if not exists submissions_stats_cover
  on submissions (contest_id, problem);
create index if not exists submissions_contest_created
  on submissions (contest_id, created_at desc);
create index if not exists judge_jobs_claim_cover
  on judge_jobs (status, kind, created_at, id);

-- ============================================================================
-- 2026-10-18: server-only Data API permissions. Review before production apply.
-- The SPA uses the FastAPI proxy, never direct Supabase reads. Views previously
-- inherited their creator's privileges and bypassed submissions RLS for anon.
-- Contest visibility also depends on API policy, not just problems.hidden.
-- ============================================================================
alter table public.reports enable row level security;
alter view public.leaderboard_scores set (security_invoker = true);
alter view public.problem_stats set (security_invoker = true);

revoke all on public.submissions, public.profiles, public.reports, public.users,
  public.judge_jobs, public.contests, public.contest_registrations,
  public.contest_announcements, public.judge_quota_events, public.problems,
  public.leaderboard_scores, public.problem_stats from public, anon, authenticated;
grant all on public.submissions, public.profiles, public.reports, public.users,
  public.judge_jobs, public.contests, public.contest_registrations,
  public.contest_announcements, public.judge_quota_events, public.problems
  to service_role;
grant select on public.leaderboard_scores, public.problem_stats to service_role;
drop policy if exists problems_public_read on public.problems;

-- ============================================================================
-- 2026-10-18: verified email identities. REVIEW before applying to production.
-- Additive: existing passwords are NOT marked verified. Old sessions lack a
-- version and are rejected by the new backend. Do not deploy it before this SQL.
-- ============================================================================
alter table public.users add column if not exists email_verified_at timestamptz;
alter table public.users add column if not exists email_auth_subject uuid;
alter table public.users add column if not exists google_subject text;
alter table public.users add column if not exists auth_version bigint not null default 0;
create unique index if not exists users_email_auth_subject_unique
  on public.users(email_auth_subject) where email_auth_subject is not null;
create unique index if not exists users_google_subject_unique
  on public.users(google_subject) where google_subject is not null;

create table if not exists public.auth_rate_buckets (
  bucket text primary key,
  window_start timestamptz not null,
  attempts integer not null check (attempts > 0),
  expires_at timestamptz not null
);
create index if not exists auth_rate_buckets_expiry on public.auth_rate_buckets(expires_at);
alter table public.auth_rate_buckets enable row level security;
revoke all on public.auth_rate_buckets from public, anon, authenticated;
grant all on public.auth_rate_buckets to service_role;

-- One transaction for every replica. Hash keys are supplied by the trusted
-- backend; no email addresses or OTPs are stored in this abuse-control table.
-- Global send ceiling is deliberately small for the initial Gmail test sender.
create or replace function public.auth_email_budget(
  p_email_key text, p_network_key text, p_action text
) returns jsonb language plpgsql security invoker set search_path = pg_catalog, public as $$
declare
  limits jsonb;
  item jsonb;
  current_time_ timestamptz := clock_timestamp();
  start_ timestamptz;
  seconds_ integer;
  hits_ integer;
  retry_ integer := 0;
begin
  if p_email_key !~ '^[0-9a-f]{64}$' or p_network_key !~ '^[0-9a-f]{64}$'
     or p_action not in ('request', 'verify') then
    raise exception 'invalid auth budget';
  end if;
  perform pg_advisory_xact_lock(hashtext('newbiegrader-email-budget'));
  current_time_ := clock_timestamp();
  if p_action = 'request' then
    limits := jsonb_build_array(
      jsonb_build_array('send:global', 100, 86400),
      jsonb_build_array('send:network:' || p_network_key, 50, 3600),
      jsonb_build_array('send:hour:' || p_email_key, 5, 3600),
      jsonb_build_array('send:minute:' || p_email_key, 1, 60));
  else
    limits := jsonb_build_array(
      jsonb_build_array('verify:global', 1000, 3600),
      jsonb_build_array('verify:network:' || p_network_key, 100, 900),
      jsonb_build_array('verify:email:' || p_email_key, 8, 900));
  end if;
  for item in select value from jsonb_array_elements(limits) loop
    seconds_ := (item->>2)::integer;
    start_ := current_time_;
    select attempts into hits_ from public.auth_rate_buckets
      where bucket = item->>0 and expires_at > current_time_;
    if coalesce(hits_, 0) >= (item->>1)::integer then
      select expires_at into start_ from public.auth_rate_buckets where bucket = item->>0;
      retry_ := greatest(retry_, ceil(extract(epoch from (start_ - current_time_)))::integer);
    end if;
  end loop;
  if retry_ > 0 then
    return jsonb_build_object('allowed', false, 'retry_after', retry_);
  end if;
  delete from public.auth_rate_buckets where expires_at <= current_time_;
  for item in select value from jsonb_array_elements(limits) loop
    seconds_ := (item->>2)::integer;
    start_ := current_time_;
    insert into public.auth_rate_buckets as b(bucket, window_start, attempts, expires_at)
      values (item->>0, start_, 1, start_ + make_interval(secs => seconds_))
    on conflict (bucket) do update set
      attempts = case when b.expires_at > current_time_ then b.attempts + 1 else 1 end,
      window_start = case when b.expires_at > current_time_ then b.window_start else excluded.window_start end,
      expires_at = case when b.expires_at > current_time_ then b.expires_at else excluded.expires_at end;
  end loop;
  return jsonb_build_object('allowed', true);
end $$;

-- Call only AFTER a successful server-to-server /verify response. The password
-- is chosen after email proof, never recovered from a pending signup/session.
-- The row lock serializes credential replacement; every replacement revokes
-- all previous session/remember versions without rewriting any history owner.
create or replace function public.auth_email_complete(
  p_email text, p_subject uuid, p_password_hash text, p_name text
) returns jsonb language plpgsql security invoker set search_path = pg_catalog, public as $$
declare
  account_ public.users%rowtype;
begin
  if p_email is null or p_email <> lower(btrim(p_email)) or length(p_email) > 254
     or p_subject is null or p_password_hash not like 'pbkdf2$%' then
    raise exception 'invalid verified identity';
  end if;
  perform pg_advisory_xact_lock(hashtext('identity:' || p_email));
  select * into account_ from public.users where email = p_email for update;
  if found and account_.email_auth_subject is not null and account_.email_auth_subject <> p_subject then
    raise exception 'identity subject mismatch';
  end if;
  insert into public.users as u(email, name, password_hash, email_verified_at, email_auth_subject, auth_version)
    values (p_email, left(p_name, 50), p_password_hash, clock_timestamp(), p_subject, 1)
  on conflict (email) do update set name = excluded.name, password_hash = excluded.password_hash,
    email_verified_at = excluded.email_verified_at, email_auth_subject = excluded.email_auth_subject,
    auth_version = u.auth_version + 1
  returning * into account_;
  return jsonb_build_object('email', account_.email, 'name', account_.name,
                           'auth_version', account_.auth_version);
end $$;

-- Google subjects are bound explicitly. A verified password account is NOT
-- silently linked because an OAuth response happens to have the same email.
-- A first trusted Google claim clears any unverified legacy password.
create or replace function public.auth_google_identity(
  p_email text, p_subject text, p_name text
) returns jsonb language plpgsql security invoker set search_path = pg_catalog, public as $$
declare
  account_ public.users%rowtype;
begin
  if p_email is null or p_email <> lower(btrim(p_email)) or p_subject is null
     or length(p_subject) not between 1 and 255 then
    raise exception 'invalid google identity';
  end if;
  perform pg_advisory_xact_lock(hashtext('identity:' || p_email));
  select * into account_ from public.users where email = p_email for update;
  if found and account_.email_verified_at is not null then
    if account_.google_subject is distinct from p_subject then
      return jsonb_build_object('link_required', true);
    end if;
  else
    insert into public.users as u(email, name, password_hash, email_verified_at, google_subject, auth_version)
      values (p_email, left(p_name, 50), '', clock_timestamp(), p_subject, 1)
    on conflict (email) do update set name = excluded.name, password_hash = '',
      email_verified_at = excluded.email_verified_at, google_subject = excluded.google_subject,
      auth_version = u.auth_version + 1
    returning * into account_;
  end if;
  return jsonb_build_object('email', account_.email, 'name', account_.name,
                           'auth_version', account_.auth_version);
end $$;

revoke all on function public.auth_email_budget(text,text,text) from public, anon, authenticated;
revoke all on function public.auth_email_complete(text,uuid,text,text) from public, anon, authenticated;
revoke all on function public.auth_google_identity(text,text,text) from public, anon, authenticated;
grant execute on function public.auth_email_budget(text,text,text) to service_role;
grant execute on function public.auth_email_complete(text,uuid,text,text) to service_role;
grant execute on function public.auth_google_identity(text,text,text) to service_role;

-- ============================================================================
-- 2026-10-20: realtime admin management. ADMIN_EMAILS stays the immutable
-- bootstrap set; rows here are additional admins editable from the admin page.
-- ============================================================================
create table if not exists public.admins (
  email text primary key check (email = lower(btrim(email)) and email <> ''),
  created_at timestamptz not null default now(),
  created_by text not null default ''
);
alter table public.admins enable row level security;
revoke all on public.admins from public, anon, authenticated;
grant all on public.admins to service_role;

-- ============================================================================
-- 2026-10-21: queue RPCs use the caller's existing backend privileges.
-- Only service_role can execute these functions; it already has the required
-- table grants and BYPASSRLS. Running as the function owner adds unnecessary
-- privileges. Keep the fixed search_path and the server-only EXECUTE grants.
-- Append-only and re-runnable; review before applying in Supabase SQL Editor.
-- ============================================================================
alter function public.judge_queue_admit(jsonb,integer,boolean,integer,integer) security invoker;
alter function public.judge_queue_claim(text,integer) security invoker;
alter function public.judge_queue_heartbeat(uuid,text,integer,integer) security invoker;
alter function public.judge_queue_finish(uuid,text,integer,jsonb,jsonb,text) security invoker;
alter function public.judge_queue_diagnostics() security invoker;
