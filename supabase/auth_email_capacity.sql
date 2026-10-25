-- 2026-10-25: operator-approved public email capacity.
-- 300 project requests/day and 200 requests/hour per classroom network.
-- Keep per-email resend/guess budgets and atomic admission unchanged.
-- Apply through the maintainer's Supabase SQL Editor after offline tests.
begin;
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
      jsonb_build_array('send:global', 300, 86400),
      jsonb_build_array('send:network:' || p_network_key, 200, 3600),
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
revoke all on function public.auth_email_budget(text,text,text) from public,anon,authenticated;
grant execute on function public.auth_email_budget(text,text,text) to service_role;
notify pgrst,'reload schema';
commit;
