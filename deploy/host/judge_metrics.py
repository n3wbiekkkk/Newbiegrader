"""Read-only, bounded judge statistics; exports aggregates, never source or identity."""
import datetime as dt
import json
import math
from pathlib import Path
import shlex
import time
import urllib.parse
import urllib.request

MAX_ROWS = 1000
MAX_RESPONSE = 1024 * 1024
VERDICTS = ('AC', 'WA', 'TLE', 'MLE', 'OLE', 'RE', 'CE')


def read_settings(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            if key in ('SUPABASE_URL', 'SUPABASE_KEY'):
                parts = shlex.split(value, comments=True)
                result[key] = parts[0] if parts else ''
    url = urllib.parse.urlsplit(result['SUPABASE_URL'])
    if (url.scheme != 'https' or not (url.hostname or '').endswith('.supabase.co')
            or url.username or url.password or url.query or url.fragment or url.port not in (None, 443)):
        raise ValueError('unexpected metrics database destination')
    return result


def request_json(settings, path, body=None):
    headers = {'apikey': settings['SUPABASE_KEY'],
               'Authorization': 'Bearer ' + settings['SUPABASE_KEY'],
               'Content-Type': 'application/json'}
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(settings['SUPABASE_URL'].rstrip('/')+'/rest/v1/'+path,
                                     data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=3) as response:
        raw = response.read(MAX_RESPONSE+1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError('oversized metrics response')
    return json.loads(raw)


def duration(row):
    try:
        start = dt.datetime.fromisoformat(row['started_at'].replace('Z', '+00:00'))
        end = dt.datetime.fromisoformat(row['finished_at'].replace('Z', '+00:00'))
        seconds = (end-start).total_seconds()
        return seconds if math.isfinite(seconds) and 0 <= seconds <= 86400 else None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def summarize(jobs, submissions):
    if (not isinstance(jobs, list) or not isinstance(submissions, list)
            or len(jobs) > MAX_ROWS or len(submissions) > MAX_ROWS
            or any(not isinstance(row, dict) for row in jobs + submissions)):
        raise ValueError('invalid metric rows')
    values = sorted(value for row in jobs if isinstance(row, dict)
                    and row.get('kind') in ('submit', 'rejudge')
                    and (value := duration(row)) is not None)
    result = {'completed': len(jobs), 'backend_errors': sum(row.get('status') == 'error' for row in jobs),
              'samples': len(values), 'truncated': int(len(jobs) >= MAX_ROWS or len(submissions) >= MAX_ROWS),
              'failed': sum(row.get('accepted') is False for row in submissions),
              'verdicts': {v: sum(row.get('verdict') == v for row in submissions) for v in VERDICTS}}
    if values:
        result['p50'] = values[max(0, math.ceil(len(values)*0.50)-1)]
        result['p95'] = values[max(0, math.ceil(len(values)*0.95)-1)]
    return result


def statistics(settings, now):
    lower = dt.datetime.fromtimestamp(now-3600, dt.timezone.utc).isoformat()
    jobs = request_json(settings, 'judge_jobs?'+urllib.parse.urlencode({
        'select': 'status,kind,started_at,finished_at', 'status': 'in.(done,error)',
        'created_at': 'gte.'+lower, 'order': 'created_at.desc', 'limit': MAX_ROWS}))
    submissions = request_json(settings, 'submissions?'+urllib.parse.urlencode({
        'select': 'verdict,accepted', 'created_at': 'gte.'+lower,
        'order': 'created_at.desc', 'limit': MAX_ROWS}))
    return summarize(jobs, submissions)


def collect(config, now=None):
    """Called only by the existing trusted observer; no credentials in child envs."""
    if not config:
        return []
    now = time.time() if now is None else now
    try:
        settings = read_settings(config['env_file'])
        counts = request_json(settings, 'rpc/judge_queue_diagnostics', {})
        queued, running = counts['queued'], counts['running']
        if any(type(v) is not int or v < 0 for v in (queued, running)):
            raise ValueError('invalid queue counts')
        cache = Path(config['cache_file'])
        try:
            state = json.loads(cache.read_text())
        except (OSError, ValueError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        if not 0 <= now-state.get('at', 0) < 60:
            state = {'at': now, 'summary': statistics(settings, now)}
            temp = cache.with_suffix('.new')
            temp.write_text(json.dumps(state));temp.chmod(0o600);temp.replace(cache)
        data = state['summary']
        lines = ['newbiegrader_judge_metrics_up 1', f'newbiegrader_queue_queued {queued}',
                 f'newbiegrader_queue_running {running}', f'newbiegrader_judge_statistics_seconds {state["at"]}',
                 f'newbiegrader_judge_window_truncated {data["truncated"]}',
                 f'newbiegrader_judge_completed_window {data["completed"]}',
                 f'newbiegrader_backend_errors_window {data["backend_errors"]}',
                 f'newbiegrader_failed_submissions_window {data["failed"]}',
                 f'newbiegrader_judge_processing_samples {data["samples"]}']
        for key in ('p50', 'p95'):
            if key in data:
                lines.append(f'newbiegrader_judge_processing_seconds_{key} {data[key]}')
        lines.extend('newbiegrader_submission_verdict_window{verdict="'+v+'"} '+str(data['verdicts'][v]) for v in VERDICTS)
        return lines
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        # Do not log URLs, headers, identities or provider exception bodies.
        return ['newbiegrader_judge_metrics_up 0']
