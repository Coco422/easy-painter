import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseCreationHistory, creationVersionRows, creationHistoryKey } from '../src/lib/creation-versions.ts'
import { appendGenerationImage } from '../src/lib/canvas/from-generation.ts'
import { newProject, newNode, validateProject } from '../src/lib/canvas/model.ts'

test('versions retain independent branches from older images and sort by creation time', () => {
  const jobs = ['c','a','b'].map(id => ({job_id:id, created_at:{a:'2026-01-01',b:'2026-01-02',c:'2026-01-03'}[id]}))
  const rows = creationVersionRows(jobs, {a:null,b:'a',c:'a'})
  assert.deepEqual(rows.map(row => [row.job.job_id,row.number,row.parentNumber]), [['a',1,undefined],['b',2,1],['c',3,1]])
  assert.equal(creationVersionRows(jobs.slice(0,1), {c:'missing'})[0].parentNumber, undefined)
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
  const result=appendGenerationImage(p,{jobId:'job-1',assetId:'a'.repeat(64),label:'创作 V1',prompt:'描述',model:'m',size:'auto',width:1600,height:900})
  assert.equal(JSON.stringify(p),original)
  assert.equal(result.nodes.length,4)
  assert.equal(result.nodes[0].id,p.nodes[0].id)
  assert.equal(result.runs.length,0)
  assert.equal(result.edges.length,1)
  assert.equal(result.nodes[2].prompt,'')
  assert.equal(validateProject(result,'alice').ownerId,'alice')
  assert.match(result.nodes[3].text,/job-1/)
  p.nodes=Array.from({length:298},()=>newNode('text',{x:0,y:0}))
  assert.throws(()=>appendGenerationImage(p,{width:1,height:1}),/节点已达上限/)
})
