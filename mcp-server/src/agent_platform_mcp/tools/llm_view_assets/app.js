'use strict';
const $ = id => document.getElementById(id);
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('token')) { sessionStorage.setItem('llm-view-token', fragment.get('token')); history.replaceState(null, '', '/'); }
let runs = [];
let selected = null;
const show = value => value === null || value === undefined ? '—' : String(value);
async function api(path) {
  const response = await fetch(path, {headers: {Authorization: 'Bearer ' + (sessionStorage.getItem('llm-view-token') || '')}, cache: 'no-store'});
  if (!response.ok) throw new Error(response.status === 403 ? '서버 실행 시 출력된 접속 URL을 사용하세요.' : '기록을 불러오지 못했습니다. 서버 상태를 확인하세요.');
  return response.json();
}
function render() {
  $('runs').replaceChildren();
  const query = $('search').value.toLowerCase();
  for (const run of runs.filter(r => [r.task_id, r.project_id, r.workspace, r.role, r.backend].join(' ').toLowerCase().includes(query))) {
    const button = document.createElement('button');
    button.className = 'run';
    button.textContent = `${run.backend || "unknown"} · ${run.task_id} · ${run.role}\n${run.project_id || run.workspace}\n${run.ts} · ${run.state} · ${show(run.duration_sec)}s`;
    button.addEventListener('click', () => select(run.run_id));
    $('runs').append(button);
  }
  if (!$('runs').children.length) $('runs').textContent = '표시할 실행이 없습니다. agent-platform에서 실행한 Claude·Codex 세션을 5초마다 수집합니다.';
}
async function select(id) {
  selected = id;
  try {
    const run = await api('/api/runs/' + encodeURIComponent(id));
    $('title').textContent = `${run.task_id} / ${run.role}`;
    $('info').textContent = `${run.workspace} · ${run.backend || 'backend unknown'} · ${run.model || 'model unknown'} · ${run.state} · ${run.run_id}`;
    const usage = run.usage || {};
    $('metrics').textContent = `소요 시간 ${show(run.duration_sec)}s  |  입력 ${show(usage.input_tokens)}  |  출력 ${show(usage.output_tokens)}  |  캐시 읽기 ${show(usage.cache_read_tokens)}  |  캐시 쓰기 ${show(usage.cache_write_tokens)}\n수집 경로: ${run.collection_source} · 토큰 상태: ${usage.completeness || 'unavailable'}`;
    const sourceKind = run.collection_source === 'native_session' ? 'native_turn' : 'platform_run';
    $('feedback-help').textContent = `피드백 등록: feedback add --source-kind ${sourceKind} --source-id ${run.run_id} --kind correction (대상 --root와 요약 JSON을 CLI에 명시하세요)`;
    const content = run.content;
    $('prompt').textContent = content.status !== 'captured' ? '원문 미수집 또는 보관 기간 만료. capture on 이후 새 실행부터 확인할 수 있습니다.' : (content.prompt ?? '입력 원문 없음') + (content.prompt_truncated ? '\n[길이 제한으로 잘림]' : '');
    $('response').textContent = content.status !== 'captured' ? '원문 없음' : (content.response ?? '응답 없음: 실행 중이거나 응답 수집 전에 종료됐습니다.') + (content.response_truncated ? '\n[길이 제한으로 잘림]' : '');
    $('events').textContent = JSON.stringify(run.events, null, 2);
  } catch (error) { $('status').textContent = error.message; }
}
async function refresh() {
  try {
    const result = await api('/api/runs'); runs = result.runs; render();
    const collector = result.collector || {};
    const failed = collector.error || ['claude', 'codex'].some(b => collector[b]?.errors);
    $('status').textContent = `${runs.length} / ${result.total}건 · 5초 자동 갱신 · ${failed ? '수집 오류 발생' : collector.enabled ? 'Claude·Codex 자동 수집 중' : '원문 자동 수집 꺼짐'}`;
    if (selected && runs.some(r => r.run_id === selected)) await select(selected);
    else if (runs.length) await select(runs[0].run_id);
  }
  catch (error) { $('status').textContent = error.message; }
}
$('refresh').addEventListener('click', refresh);
$('search').addEventListener('input', render);
refresh();
setInterval(refresh, 5000);
