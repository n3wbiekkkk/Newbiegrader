-- Run only against the disposable CI database after applying schema.sql twice.
begin;
do $$
declare item record; role_name text; object_name text; privilege_name text;
begin
  foreach object_name in array array[
    'submissions','profiles','reports','users','judge_jobs','contests',
    'contest_registrations','contest_announcements','judge_quota_events','problems',
    'admins','leaderboard_scores','problem_stats'
  ] loop
    foreach role_name in array array['anon','authenticated'] loop
      foreach privilege_name in array array[
        'select','insert','update','DELETE','truncate','references','trigger'
      ] loop
        if has_table_privilege(role_name,'public.'||object_name,privilege_name)
           or has_any_column_privilege(role_name,'public.'||object_name,privilege_name) then
          raise exception '% unexpectedly has % on %',role_name,privilege_name,object_name;
        end if;
      end loop;
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
end $$;

-- A real service-role read still works after changing the views' security mode.
set local role service_role;
select count(*) from public.leaderboard_scores;
select count(*) from public.problem_stats;
select count(*) from public.problems;
rollback;
