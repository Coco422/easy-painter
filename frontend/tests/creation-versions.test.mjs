import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseCreationHistory, creationVersionRows, creationResultBatches, creationHistoryKey } from '../src/lib/creation-versions.ts'
import { appendGenerationImage } from '../src/lib/canvas/from-generation.ts'
import { newProject, newNode, validateProject } from '../src/lib/canvas/model.ts'

test('versions retain independent branches from older images and sort by creation time', () => {
  const jobs = ['c','a','b'].map(id => ({job_id:id, created_at:{a:'2026-01-01',b:'2026-01-02',c:'2026-01-03'}[id]}))
  const rows = creationVersionRows(jobs, {a:null,b:'a',c:'a'})
  assert.deepEqual(rows.map(row => [row.job.job_id,row.number,row.parentNumber]), [['a',1,undefined],['b',2,1],['c',3,1]])
  assert.equal(creationVersionRows(jobs.slice(0,1), {c:'missing'})[0].parentNumber, undefined)
})

const draws = ids => ids.map((job_id, index) => ({ job_id, created_at: `2026-01-01T00:00:${String(index).padStart(2, '0')}Z`, prompt: 'same prompt', status: 'succeeded' }))

test('single-image labels remain results until actual edits introduce version numbers', () => {
  const original = creationVersionRows(draws(['a']), { a: null }, { a: 'single' })
  assert.equal(original[0].candidateCount, 1)
  assert.equal(original[0].label, '生成结果')
  assert.doesNotMatch(original[0].label, /候选|V\d/)
  const edited = creationVersionRows(draws(['a', 'edit']), { a: null, edit: 'a' }, { a: 'single', edit: 'edit-submission' })
  assert.deepEqual(edited.map(row => row.label), ['生成结果', 'V2'])
  assert.equal(creationResultBatches(edited).length, 1)
})

test('parallel draws are peer candidates and identical prompts in later batches stay separate', () => {
  const jobs = draws(['a', 'b', 'c', 'd'])
  const rows = creationVersionRows(jobs.toReversed(), { a: null, b: null, c: null, d: null }, { a: 'one', b: 'one', c: 'two', d: 'two' })
  assert.deepEqual(rows.map(row => [row.label, row.number, row.parentId]), [
    ['候选图 1', 1, null], ['候选图 2', 1, null], ['候选图 1', 1, null], ['候选图 2', 1, null],
  ])
  assert.deepEqual(creationResultBatches(rows).map(batch => batch.candidates.map(candidate => candidate.job.job_id)), [['a', 'b'], ['c', 'd']])
  assert.equal(creationResultBatches(creationVersionRows(jobs, {})).length, 4, 'missing membership must not infer batches from identical parameters')
})

test('edits follow the selected candidate and its original batch with independent version numbering', () => {
  const jobs = draws(['a', 'b', 'c', 'b-edit', 'a-edit', 'b-fork', 'b-next'])
  const parents = { a: null, b: null, c: null, 'b-edit': 'b', 'a-edit': 'a', 'b-fork': 'b', 'b-next': 'b-edit' }
  const membership = { a: 'one', b: 'one', c: 'two', 'b-edit': 'edit-submission', 'a-edit': 'another-edit' }
  const rows = creationVersionRows(jobs.toReversed(), parents, membership)
  const batches = creationResultBatches(rows)
  assert.equal(batches.length, 2)
  assert.deepEqual(batches[0].candidates.map(candidate => candidate.rows.map(row => row.job.job_id)), [
    ['a', 'a-edit'], ['b', 'b-edit', 'b-fork', 'b-next'],
  ])
  assert.deepEqual(batches[0].candidates[1].rows.map(row => [row.number, row.parentNumber]), [[1, undefined], [2, 1], [3, 1], [4, 2]])
  assert.equal(rows.find(row => row.job.job_id === 'a-edit').label, '候选图 1 · V2')
  assert.equal(rows.find(row => row.job.job_id === 'b-edit').label, '候选图 2 · V2')
  assert.equal(batches[1].candidates[0].rows.length, 1)
})

test('restoring local ancestry and membership preserves candidate groups across polling and failures', () => {
  const jobs = draws(['a', 'b', 'edit'])
  const parents = parseCreationHistory(JSON.stringify({ parents: { a: null, b: null, edit: 'b' } })).parents
  const membership = JSON.parse(JSON.stringify({ a: 'one', b: 'one', edit: 'own-submission' }))
  jobs[1].status = 'processing'
  jobs[2].status = 'failed'
  const snapshot = list => creationResultBatches(creationVersionRows(list, parents, membership)).map(batch => batch.candidates.map(candidate => candidate.rows.map(row => row.job.job_id)))
  assert.deepEqual(snapshot(jobs), [[['a'], ['b', 'edit']]])
  jobs[1].status = 'succeeded'
  assert.deepEqual(snapshot(jobs.toReversed()), snapshot(jobs))
  assert.deepEqual(snapshot(jobs.filter(job => job.job_id !== 'b')), [[['a'], ['edit']]], 'a missing original cannot attach an edit to another candidate')
})

test('server timestamps cannot swap parallel candidate labels while polling', () => {
  const jobs = draws(['a', 'b'])
  const membership = { a: 'one', b: 'one' }
  const snapshot = () => creationResultBatches(creationVersionRows(jobs, {}, membership))[0].candidates.map(candidate => [candidate.job.job_id, candidate.label])
  assert.deepEqual(snapshot(), [['a', '候选图 1'], ['b', '候选图 2']])
  jobs[0].created_at = jobs[1].created_at
  jobs[1].created_at = '2026-01-01T00:00:00Z'
  assert.deepEqual(snapshot(), [['a', '候选图 1'], ['b', '候选图 2']])
})

test('local version history is bounded, account-scoped and rejects malformed cycles', () => {
  assert.notEqual(creationHistoryKey('alice'), creationHistoryKey('bob'))
  assert.deepEqual(parseCreationHistory('{bad'), {parents:{},pending:null})
  const parents = Object.fromEntries(Array.from({length:150},(_,i)=>['job-'+i,null]))
  assert.equal(Object.keys(parseCreationHistory(JSON.stringify({parents})).parents).length,100)
  const parsed = parseCreationHistory(JSON.stringify({parents:{a:'b',b:'a',c:'c',d:12}}))
  assert.equal(parsed.parents.a,null)
  assert.equal(parsed.parents.c,undefined)
})

test('unknown revision submissions preserve the exact request and idempotency key for confirmation', () => {
  const pending={key:'stable-key',parentId:'source',request:{prompt:'改蓝色',model:'m',size:'auto',reference_image_ids:['ref-1']}}
  assert.deepEqual(parseCreationHistory(JSON.stringify({parents:{source:null},pending})).pending,pending)
  assert.equal(parseCreationHistory(JSON.stringify({pending:{...pending,request:{...pending.request,reference_image_ids:[]}}})).pending,null)
})

test('adding a result to an existing canvas preserves prior content and never creates paid runs', () => {
  const p=newProject('alice')
  p.nodes.push(newNode('text',{x:0,y:0}))
  const original=JSON.stringify(p)
  const result=appendGenerationImage(p,{jobId:'job-1',assetId:'a'.repeat(64),label:'第 1 批 · 候选图 1',prompt:'描述',model:'m',size:'auto',width:1600,height:900})
  assert.equal(JSON.stringify(p),original)
  assert.equal(result.nodes.length,4)
  assert.equal(result.nodes[0].id,p.nodes[0].id)
  assert.equal(result.nodes[1].title,'第 1 批 · 候选图 1')
  assert.equal(result.runs.length,0)
  assert.equal(result.edges.length,1)
  assert.equal(result.nodes[2].prompt,'')
  assert.equal(validateProject(result,'alice').ownerId,'alice')
  assert.match(result.nodes[3].text,/job-1/)
  p.nodes=Array.from({length:298},()=>newNode('text',{x:0,y:0}))
  assert.throws(()=>appendGenerationImage(p,{width:1,height:1}),/节点已达上限/)
})
