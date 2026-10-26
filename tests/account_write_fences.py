"""Deterministic erasure/write races in disposable PostgreSQL, not production."""
import subprocess
import time
import uuid


PSQL = ['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1']


def query(sql):
    return subprocess.run(PSQL + ['-c', sql], check=True, capture_output=True,
                          text=True, timeout=15).stdout.strip()


class Transaction:
    def __init__(self):
        self.process = subprocess.Popen(PSQL, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
        self.execute("set statement_timeout='10s'; begin; set local role service_role")

    def execute(self, sql):
        marker = 'ready_' + uuid.uuid4().hex
        self.process.stdin.write(sql + ";\nselect '" + marker + "';\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise AssertionError(self.process.stderr.read())
            if line.strip() == marker:
                return

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=15)
        self.process.stdout.close()
        self.process.stderr.close()


def writes(email, ident):
    return [
        f"insert into public.profiles(user_email,display_name) values('{email}','Private') "
        "on conflict(user_email) do update set display_name=excluded.display_name",
        f"insert into public.reports(problem,user_email,message) values('synthetic','{email}','Private')",
        f"insert into public.contest_registrations(contest_id,user_email) values('{ident}','{email}') "
        "on conflict(contest_id,user_email) do update set name=excluded.name",
        f"insert into public.contests(id,starts_at,ends_at,created_by) values('{ident}',now(),now()+interval '1 day','{email}')",
        f"insert into public.contest_announcements(id,contest_id,created_by) values('{uuid.uuid4()}','{ident}','{email}')",
        f"insert into public.admins(email,created_by) values('{ident}@example.invalid','{email}')",
    ]


def erased_rows(email):
    parts = [f"(select count(*) from public.{t} where {col}='{email}')"
             for t, col in [('profiles', 'user_email'), ('reports', 'user_email'),
                            ('contest_registrations', 'user_email'), ('contests', 'created_by'),
                            ('contest_announcements', 'created_by'), ('admins', 'created_by'),
                            ('admins', 'email'), ('users', 'email')]]
    return int(query('select ' + '+'.join(parts)))


def wait_for_lock(name, process):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if query("select count(*) from pg_stat_activity where application_name='" + name +
                 "' and wait_event='advisory'") == '1':
            return
        if process.poll() is not None:
            raise AssertionError(process.communicate())
        time.sleep(.02)
    raise AssertionError('writer/deletion never reached identity lock')


def main():
    if query('select current_database()') != 'newbiegrader_test':
        raise SystemExit('REFUSED: expected disposable database newbiegrader_test')
    # Delete holds the identity lock before the writer statement starts. Its
    # original statement snapshot must not authorize a write after lock release.
    for index in range(6):
        ident = 'fence-' + uuid.uuid4().hex
        email = ident + '@example.invalid'
        query(f"insert into public.users(email) values('{email}')")
        tx = Transaction()
        writer = None
        try:
            tx.execute(f"do $$ begin perform public.account_delete_begin('{email}'); "
                       f"perform public.account_delete_finish('{email}'); end $$")
            name = 'blocked_' + uuid.uuid4().hex
            writer = subprocess.Popen(PSQL + ['-c',
                f"set statement_timeout='10s'; set role service_role; set application_name='{name}'; "
                + writes(email, ident)[index]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            wait_for_lock(name, writer)
            tx.execute('commit')
            _, error = writer.communicate(timeout=15)
            assert writer.returncode != 0 and 'account write unavailable' in error, error
            assert erased_rows(email) == 0
        finally:
            tx.close()
            if writer is not None and writer.poll() is None:
                writer.kill()
                writer.communicate()

    # The reverse ordering is also valid: deletion waits for a legitimate write
    # to commit, then erases/anonymizes that row before reporting success.
    for index in range(6):
        ident = 'fence-' + uuid.uuid4().hex
        email = ident + '@example.invalid'
        query(f"insert into public.users(email) values('{email}')")
        tx = Transaction()
        deletion = None
        try:
            tx.execute(writes(email, ident)[index])
            name = 'deletion_' + uuid.uuid4().hex
            deletion = subprocess.Popen(PSQL + ['-c',
                f"set statement_timeout='10s'; set role service_role; set application_name='{name}'; "
                f"select public.account_delete_begin('{email}'); select public.account_delete_finish('{email}')"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            wait_for_lock(name, deletion)
            tx.execute('commit')
            _, error = deletion.communicate(timeout=15)
            assert deletion.returncode == 0, error
            assert erased_rows(email) == 0
        finally:
            tx.close()
            if deletion is not None and deletion.poll() is None:
                deletion.kill()
                deletion.communicate()
            query(f"delete from public.contests where id='{ident}'; "
                  f"delete from public.contest_announcements where contest_id='{ident}'; "
                  f"delete from public.admins where email='{ident}@example.invalid'")
    print('12 deterministic write/erasure lock-order cases passed (six identity sinks)')


if __name__ == '__main__':
    main()
