-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Copyright (C) 2026 Newbiegrader contributors
-- Disposable PostgreSQL only. Synthetic identities; transaction always rolls back.
begin;

do $$
declare
  r jsonb;
  version_ bigint;
  i integer;
begin
  insert into public.users(email, name, password_hash)
    values ('legacy-email@example.invalid', 'Unverified', 'pbkdf2$synthetic-old');
  if (select email_verified_at is not null or auth_version <> 0 from public.users
        where email = 'legacy-email@example.invalid') then
    raise exception 'legacy account was automatically trusted';
  end if;
  r := public.auth_google_identity('legacy-email@example.invalid', 'synthetic-google-id', 'Owner');
  if r->>'auth_version' <> '1' or (select password_hash <> '' from public.users
       where email = 'legacy-email@example.invalid') then
    raise exception 'Google legacy claim retained attacker credential';
  end if;
  r := public.auth_google_identity('legacy-email@example.invalid', 'synthetic-google-id', 'Owner');
  if r->>'auth_version' <> '1' then raise exception 'Google login needlessly rotates version'; end if;
  r := public.auth_google_identity('legacy-email@example.invalid', 'different-google-id', 'Other');
  if r->>'link_required' <> 'true' then raise exception 'Google subject rebound'; end if;

  r := public.auth_email_complete('proof-email@example.invalid',
    '00000000-0000-4000-8000-000000000091', 'pbkdf2$synthetic-new', 'Owner');
  if r->>'auth_version' <> '1' or r ? 'password_hash' then raise exception 'bad email proof result'; end if;
  r := public.auth_google_identity('proof-email@example.invalid', 'unlinked-google-id', 'Other');
  if r->>'link_required' <> 'true' then raise exception 'email-only Google autolink'; end if;
  r := public.auth_email_complete('proof-email@example.invalid',
    '00000000-0000-4000-8000-000000000091', 'pbkdf2$synthetic-replacement', 'Owner');
  if r->>'auth_version' <> '2' then raise exception 'reset did not revoke sessions'; end if;
  begin
    perform public.auth_email_complete('proof-email@example.invalid',
      '00000000-0000-4000-8000-000000000092', 'pbkdf2$synthetic-other', 'Other');
    raise exception 'subject mismatch accepted';
  exception when raise_exception then
    if sqlerrm <> 'identity subject mismatch' then raise; end if;
  end;
  if (select auth_version from public.users where email = 'proof-email@example.invalid') <> 2 then
    raise exception 'failed claim modified account';
  end if;
  begin
    perform public.auth_email_complete('other-email@example.invalid',
      '00000000-0000-4000-8000-000000000091', 'pbkdf2$synthetic-other', 'Other');
    raise exception 'subject was assigned two owners';
  exception when unique_violation then null;
  end;

  r := public.auth_email_budget(repeat('a',64), repeat('b',64), 'request');
  if r->>'allowed' <> 'true' then raise exception 'first send refused'; end if;
  r := public.auth_email_budget(repeat('a',64), repeat('c',64), 'request');
  if r->>'allowed' <> 'false' or (r->>'retry_after')::int not between 59 and 60 then
    raise exception 'resend did not enforce minimum 60 seconds';
  end if;
  for i in 1..8 loop
    r := public.auth_email_budget(repeat('a',64), repeat('b',64), 'verify');
    if r->>'allowed' <> 'true' then raise exception 'guess budget early refusal'; end if;
  end loop;
  r := public.auth_email_budget(repeat('a',64), repeat('c',64), 'verify');
  if r->>'allowed' <> 'false' then raise exception 'new network bypassed account guess budget'; end if;

  -- Isolated test transaction: existing fixture rows are restored by rollback.
  delete from public.auth_rate_buckets;
  for i in 1..100 loop
    r := public.auth_email_budget(md5('email-' || i) || md5('email-' || i),
      md5('network-' || i) || md5('network-' || i), 'request');
    if r->>'allowed' <> 'true' then raise exception 'global send budget early refusal'; end if;
  end loop;
  r := public.auth_email_budget(repeat('d',64), repeat('e',64), 'request');
  if r->>'allowed' <> 'false' or (select count(*) from public.auth_rate_buckets) <> 301 then
    raise exception 'new addresses bypassed global budget or created rejected buckets';
  end if;

  if has_table_privilege('anon', 'public.auth_rate_buckets', 'select')
     or has_table_privilege('authenticated', 'public.auth_rate_buckets', 'select') then
    raise exception 'public auth bucket access';
  end if;
  if not (select relrowsecurity from pg_class where oid = 'public.auth_rate_buckets'::regclass) then
    raise exception 'RLS missing';
  end if;
  if has_function_privilege('anon','public.auth_email_complete(text,uuid,text,text)','execute')
     or has_function_privilege('authenticated','public.auth_google_identity(text,text,text)','execute')
     or has_function_privilege('anon','public.auth_email_budget(text,text,text)','execute') then
    raise exception 'public identity RPC access';
  end if;
end $$;

-- Invoker functions must work for the actual backend role, not only postgres.
set local role service_role;
select (public.auth_email_complete('role-email@example.invalid',
  '00000000-0000-4000-8000-000000000093', 'pbkdf2$synthetic-role', 'Owner')->>'auth_version')::int = 1
  as service_role_claim_works;
reset role;
rollback;
