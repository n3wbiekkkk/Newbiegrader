-- Account erasure write fences. Apply in Supabase SQL Editor before backend rollout.
-- Additive/idempotent: existing rows and historical migrations are not rewritten.
begin;
create or replace function public.account_write_guard() returns trigger
language plpgsql security invoker set search_path='' as $$
declare
 column_ text;
 email_ text;
 owners_ text[] := array[]::text[];
 live_ text[] := array[]::text[];
begin
 foreach column_ in array tg_argv loop
  email_ := pg_catalog.to_jsonb(new)->>column_;
  if email_ is null or email_='' then continue; end if;
  if tg_op='UPDATE' then
   if email_ is not distinct from (pg_catalog.to_jsonb(old)->>column_) then continue; end if;
  end if;
  -- Erasure predicates compare canonical identities exactly. Do not permit an
  -- alternate spelling that would survive those predicates.
  if email_<>pg_catalog.lower(pg_catalog.btrim(email_)) then
   raise exception 'noncanonical account identity' using errcode='23514';
  end if;
  owners_ := pg_catalog.array_append(owners_,email_);
  if column_ in ('user_email','created_by') then
   live_ := pg_catalog.array_append(live_,email_);
  end if;
 end loop;
 -- Stable order also covers admin rows carrying both target and actor emails.
 for email_ in select distinct x from pg_catalog.unnest(owners_) x order by x loop
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('identity:'||email_));
  if public.account_is_deleted(email_) or
     (email_=any(live_) and not exists(select 1 from public.users where email=email_)) then
   raise exception 'account write unavailable' using errcode='23514';
  end if;
 end loop;
 return new;
end $$;
revoke all on function public.account_write_guard() from public,anon,authenticated;
grant execute on function public.account_write_guard() to service_role;

drop trigger if exists account_write_fence on public.profiles;
create trigger account_write_fence before insert or update of user_email on public.profiles
 for each row execute function public.account_write_guard('user_email');
drop trigger if exists account_write_fence on public.reports;
create trigger account_write_fence before insert or update of user_email on public.reports
 for each row execute function public.account_write_guard('user_email');
drop trigger if exists account_write_fence on public.contest_registrations;
create trigger account_write_fence before insert or update of user_email on public.contest_registrations
 for each row execute function public.account_write_guard('user_email');
-- Deletion also anonymizes actor fields. Fence their reintroduction by an
-- already-authorized admin request without forbidding invites to new emails.
drop trigger if exists account_write_fence on public.contests;
create trigger account_write_fence before insert or update of created_by on public.contests
 for each row execute function public.account_write_guard('created_by');
drop trigger if exists account_write_fence on public.contest_announcements;
create trigger account_write_fence before insert or update of created_by on public.contest_announcements
 for each row execute function public.account_write_guard('created_by');
drop trigger if exists account_write_fence on public.admins;
create trigger account_write_fence before insert or update of email,created_by on public.admins
 for each row execute function public.account_write_guard('email','created_by');
notify pgrst,'reload schema';
commit;
