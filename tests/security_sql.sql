-- Run only against the disposable CI database after applying schema.sql twice.
begin;
do $$
declare item record; role_name text; object_name text;
begin
  foreach object_name in array array[
    'submissions','profiles','reports','users','judge_jobs','contests',
    'contest_registrations','contest_announcements','judge_quota_events','problems',
    'admins','auth_rate_buckets','web_sessions','leaderboard_scores','problem_stats'
  ] loop
    foreach role_name in array array['anon','authenticated'] loop
      if has_table_privilege(role_name,'public.'||object_name,'select,insert,update,delete')
         or has_any_column_privilege(role_name,'public.'||object_name,'select,insert,update') then
        raise exception '% unexpectedly has access to %',role_name,object_name;
      end if;
    end loop;
    if not has_table_privilege('service_role','public.'||object_name,'select') then
      raise exception 'service_role cannot read %',object_name;
    end if;
  end loop;
  for item in select c.relname,c.reloptions from pg_class c
      join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relname in ('leaderboard_scores','problem_stats') loop
    if not ('security_invoker=true'=any(coalesce(item.reloptions,array[]::text[]))) then
      raise exception 'view % bypasses caller RLS',item.relname;
    end if;
  end loop;
  if exists (select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relkind='r' and not c.relrowsecurity) then
    raise exception 'public table without RLS';
  end if;
  -- All application RPCs are server-only and run with the backend's existing
  -- privileges. Check exact signatures so a missing RPC also fails this test.
  foreach object_name in array array[
    'judge_queue_admit(jsonb,integer,boolean,integer,integer)',
    'judge_queue_claim(text,integer)',
    'judge_queue_heartbeat(uuid,text,integer,integer)',
    'judge_queue_finish(uuid,text,integer,jsonb,jsonb,text)',
    'judge_queue_diagnostics()',
    'auth_email_budget(text,text,text)',
    'auth_email_complete(text,uuid,text,text)',
    'auth_google_identity(text,text,text)',
    'auth_session_start(text,text,bigint,boolean,boolean,text,text,text[])',
    'auth_session_identity(text,text,text[])',
    'auth_session_revoke(text[])'
  ] loop
    select prosecdef, proconfig into strict item from pg_proc
      where oid = ('public.' || object_name)::regprocedure;
    if item.prosecdef then
      raise exception '% unnecessarily runs as its owner', object_name;
    end if;
    if not exists (select 1 from unnest(item.proconfig) setting
        where setting like 'search_path=%') then
      raise exception '% has no fixed search_path', object_name;
    end if;
    foreach role_name in array array['anon','authenticated'] loop
      if has_function_privilege(role_name, 'public.' || object_name, 'execute') then
        raise exception '% unexpectedly can execute %', role_name, object_name;
      end if;
    end loop;
    if not has_function_privilege('service_role', 'public.' || object_name, 'execute') then
      raise exception 'service_role cannot execute %', object_name;
    end if;
  end loop;
  if has_table_privilege('service_role','public.web_sessions','truncate,references,trigger') then
    raise exception 'session table has unnecessary service-role privileges';
  end if;

end $$;

-- A real service-role read still works after changing the views' security mode.
set local role service_role;
select count(*) from public.leaderboard_scores;
select count(*) from public.problem_stats;
select count(*) from public.problems;
rollback;
