-- Run only against an empty disposable test database after applying schema.sql.
-- CI uses PostgreSQL 17. Each assertion raises on failure; fixtures roll back.
begin;

-- Exercise the full lifecycle with the role used by the API/worker. Running
-- only as postgres would hide missing grants after switching to invoker RPCs.
set local role service_role;

do $test$
declare
    first_job jsonb;
    second_job jsonb;
    first_claim jsonb;
    second_claim jsonb;
    answer jsonb;
    history_row jsonb;
    history_id uuid;
    queue_function record;
begin
    if exists (select 1 from public.judge_jobs) then
        raise exception 'queue SQL tests require an empty disposable database';
    end if;

    for queue_function in
        select oid, proname, prosecdef, proconfig
        from pg_proc where pronamespace = 'public'::regnamespace
        and proname like 'judge_queue_%'
    loop
        if has_function_privilege('anon', queue_function.oid, 'EXECUTE')
           or has_function_privilege('authenticated', queue_function.oid, 'EXECUTE') then
            raise exception '% is callable by a browser role', queue_function.proname;
        end if;
        if not has_function_privilege('service_role', queue_function.oid, 'EXECUTE') then
            raise exception '% is not callable by service_role', queue_function.proname;
        end if;
        if queue_function.prosecdef then
            raise exception '% unnecessarily runs as its owner', queue_function.proname;
        end if;
        if not exists (
            select 1 from unnest(queue_function.proconfig) setting
            where setting like 'search_path=%'
        ) then
            raise exception '% has no fixed search_path', queue_function.proname;
        end if;
    end loop;

    answer := public.judge_queue_admit(
        '{"kind":"submit","user_email":"sql-a@example.test","problem":"thai_time","language":"python","source":"print(1)","reveal":"samples"}',
        2, true, 1, 600);
    first_job := answer->'job';
    if first_job->>'id' is null then raise exception 'first admission failed: %', answer; end if;

    answer := public.judge_queue_admit(
        '{"kind":"submit","user_email":"sql-a@example.test","problem":"thai_time","language":"python"}',
        2, true, 0, 0);
    if (answer->>'status_code')::int is distinct from 409 then raise exception 'same-user admission was not rejected: %', answer; end if;

    answer := public.judge_queue_admit(
        '{"kind":"submit","user_email":"sql-b@example.test","problem":"thai_time","language":"python"}',
        2, true, 0, 0);
    second_job := answer->'job';
    if second_job->>'id' is null then raise exception 'second admission failed: %', answer; end if;

    answer := public.judge_queue_diagnostics();
    if (answer->>'queued')::int is distinct from 2
       or (answer->>'running')::int is distinct from 0 then
        raise exception 'backend queue diagnostics failed: %', answer;
    end if;

    answer := public.judge_queue_admit(
        '{"kind":"submit","user_email":"sql-c@example.test","problem":"thai_time","language":"python"}',
        2, true, 0, 0);
    if (answer->>'status_code')::int is distinct from 503 then raise exception 'full queue was not rejected: %', answer; end if;

    -- Deterministic claim order: the whole test runs in one transaction, so
    -- created_at default now() is identical for every admitted job and the
    -- claim's (created_at, id) tiebreak falls back to random uuid order.
    -- Pin sql-a as oldest so first_claim is always its job (quota assertions
    -- below depend on it). Production is unaffected (separate transactions).
    update public.judge_jobs set created_at = now() - interval '2 seconds'
        where user_email = 'sql-a@example.test';

    first_claim := public.judge_queue_claim('sql-worker-a', 60);
    second_claim := public.judge_queue_claim('sql-worker-b', 60);
    if first_claim->>'id' is null or second_claim->>'id' is null
       or first_claim->>'id' = second_claim->>'id' then
        raise exception 'workers did not claim distinct jobs';
    end if;
    if public.judge_queue_claim('sql-worker-c', 60) is not null then
        raise exception 'running job was claimed twice';
    end if;
    if public.judge_queue_heartbeat((first_claim->>'id')::uuid, 'wrong-owner',
                                   (first_claim->>'attempt')::int, 60) then
        raise exception 'wrong owner renewed a lease';
    end if;
    if public.judge_queue_heartbeat((first_claim->>'id')::uuid, 'sql-worker-a',
                                  (first_claim->>'attempt')::int, 60) is not true then
        raise exception 'current owner could not renew its lease';
    end if;
    answer := public.judge_queue_finish((first_claim->>'id')::uuid, 'wrong-owner',
        (first_claim->>'attempt')::int, '{"score":100}', null, '');
    if (answer->>'applied')::boolean then raise exception 'wrong owner finalized a job'; end if;

    history_row := jsonb_build_object(
        'problem', 'thai_time', 'language', 'python', 'name', 'SQL test',
        'user_email', first_claim->>'user_email', 'verdict', 'AC', 'accepted', true,
        'passed', 1, 'total', 1, 'score', 100, 'counts', '{"AC":1}'::jsonb,
        'results', '[]'::jsonb, 'code', 'print(1)', 'detail', '', 'kind', 'submit',
        'tests_hash', '', 'grader_version', 'test', 'job_id', first_claim->>'id');
    answer := public.judge_queue_finish((first_claim->>'id')::uuid, 'sql-worker-a',
        (first_claim->>'attempt')::int, '{"score":100}', history_row, '');
    if not coalesce((answer->>'applied')::boolean, false) then
        raise exception 'valid completion failed: %', answer;
    end if;
    history_id := (answer->>'submission_id')::uuid;
    if history_id is null then raise exception 'completion did not persist history'; end if;
    if (select source from public.judge_jobs where id = (first_claim->>'id')::uuid) <> ''
       or (select payload from public.judge_jobs where id = (first_claim->>'id')::uuid) <> '{}'::jsonb then
        raise exception 'completed job retained source/payload';
    end if;
    perform public.judge_queue_finish((first_claim->>'id')::uuid, 'sql-worker-a',
        (first_claim->>'attempt')::int, '{"score":0}', history_row, '');
    if (select count(*) from public.submissions where job_id = (first_claim->>'id')::uuid) <> 1
       or (select score from public.submissions where id = history_id) is distinct from 100 then
        raise exception 'duplicate completion changed history';
    end if;

    answer := public.judge_queue_admit(
        jsonb_build_object('kind', 'submit', 'user_email', first_claim->>'user_email',
                           'problem', 'thai_time', 'language', 'python'),
        2, true, 1, 600);
    if (answer->>'status_code')::int is distinct from 429 then
        raise exception 'shared completed-job quota was not enforced: %', answer;
    end if;

    update public.judge_jobs set lease_until = now() - interval '1 second'
        where id = (second_claim->>'id')::uuid;
    if public.judge_queue_heartbeat((second_claim->>'id')::uuid, 'sql-worker-b',
                                   (second_claim->>'attempt')::int, 60) is not false then
        raise exception 'expired worker renewed its lease';
    end if;
    answer := public.judge_queue_finish((second_claim->>'id')::uuid, 'sql-worker-b',
        (second_claim->>'attempt')::int, '{"score":100}', history_row, '');
    if (answer->>'applied')::boolean is not false then raise exception 'expired lease finalized a job'; end if;
    first_claim := public.judge_queue_claim('sql-worker-c', 60);
    if first_claim->>'id' is distinct from second_claim->>'id'
       or (first_claim->>'attempt')::int is distinct from (second_claim->>'attempt')::int + 1 then
        raise exception 'expired job did not receive a new attempt';
    end if;
    answer := public.judge_queue_finish((second_claim->>'id')::uuid, 'sql-worker-b',
        (second_claim->>'attempt')::int, '{"score":100}', history_row, '');
    if (answer->>'applied')::boolean is not false then raise exception 'old attempt overrode new ownership'; end if;
    answer := public.judge_queue_finish((first_claim->>'id')::uuid, 'sql-worker-c',
        (first_claim->>'attempt')::int, null, null, 'test worker error');
    if (answer->>'applied')::boolean is not true then raise exception 'current attempt could not fail a job'; end if;
    if (select count(*) from public.submissions) <> 1 then raise exception 'failed/expired attempts wrote history'; end if;

    answer := public.judge_queue_admit(
        jsonb_build_object('kind', 'rejudge', 'user_email', 'sql-admin@example.test',
                           'problem', 'thai_time', 'language', 'python', 'target_id', history_id),
        2, false, 0, 0);
    second_job := answer->'job';
    answer := public.judge_queue_admit(
        '{"kind":"submit","user_email":"sql-student@example.test","problem":"thai_time","language":"python"}',
        2, true, 0, 0);
    first_claim := public.judge_queue_claim('sql-student-worker', 60);
    if first_claim->>'kind' is distinct from 'submit' then raise exception 'rejudge displaced a queued student'; end if;
    second_claim := public.judge_queue_claim('sql-rejudge-worker', 60);
    if second_claim->>'id' is distinct from second_job->>'id' then raise exception 'rejudge not claimed'; end if;
    history_row := history_row || '{"score":50,"verdict":"REJECTED","accepted":false,"kind":"rejudge"}';
    answer := public.judge_queue_finish((second_claim->>'id')::uuid, 'sql-rejudge-worker',
        (second_claim->>'attempt')::int, '{"score":50}', history_row, '');
    if (answer->>'submission_id')::uuid is distinct from history_id
       or (select count(*) from public.submissions) <> 1
       or (select score from public.submissions where id = history_id) is distinct from 50 then
        raise exception 'rejudge did not update original history row';
    end if;
end;
$test$;

rollback;
