-- Disposable database qualification: compatible writes, alternate identities,
-- deleted admin targets, actor reintroduction and backend-only privileges.
begin;
insert into public.users(email) values('fence-live@example.invalid'),('fence-deleted@example.invalid');
set local role service_role;
insert into public.profiles(user_email) values('fence-live@example.invalid');
update public.profiles set display_name='Updated' where user_email='fence-live@example.invalid';
-- Legacy anonymous records and future admin invitations remain supported.
insert into public.reports(problem,message) values('synthetic','Anonymous legacy record');
insert into public.admins(email,created_by) values('fence-future@example.invalid','fence-live@example.invalid');
insert into public.contests(id,starts_at,ends_at,created_by)
 values('fence-existing',now(),now()+interval '1 day','fence-deleted@example.invalid');
select public.account_delete_begin('fence-deleted@example.invalid');
select public.account_delete_finish('fence-deleted@example.invalid');
do $$ begin
 if exists(select 1 from public.contests where id='fence-existing' and created_by<>'') then
  raise exception 'actor was not anonymized';
 end if;
 begin
  insert into public.profiles(user_email) values(' FENCE-DELETED@example.invalid ');
  raise exception 'noncanonical owner accepted';
 exception when check_violation then null;
 end;
 begin
  insert into public.profiles(user_email) values('fence-missing@example.invalid');
  raise exception 'orphan owner accepted';
 exception when check_violation then null;
 end;
 begin
  insert into public.admins(email) values('fence-deleted@example.invalid');
  raise exception 'deleted admin target accepted';
 exception when check_violation then null;
 end;
 begin
  update public.contests set created_by='fence-deleted@example.invalid' where id='fence-existing';
  raise exception 'erased actor reintroduced';
 exception when check_violation then null;
 end;
 -- Non-identity updates must still work after actor anonymization.
 update public.contests set title='Updated title' where id='fence-existing';
 if not exists(select 1 from public.profiles where user_email='fence-live@example.invalid' and display_name='Updated') then
  raise exception 'legitimate profile update broken';
 end if;
end $$;
reset role;
do $$ begin
 if has_function_privilege('anon','public.account_write_guard()','execute') or
    has_function_privilege('authenticated','public.account_write_guard()','execute') or
    not has_function_privilege('service_role','public.account_write_guard()','execute') then
  raise exception 'write guard privilege boundary broken';
 end if;
end $$;
rollback;
