import { test } from 'node:test'
import assert from 'node:assert/strict'
import { groupJobs } from '../src/lib/job-batches.ts'

test('explicit batches survive status updates without merging separate identical prompts', () => {
  const jobs = ['a', 'b', 'c', 'd', 'e'].map(job_id => ({ job_id, prompt: 'same', status: 'queued' }))
  const membership = { a: 'one', b: 'one', c: 'one', d: 'one', e: 'two' }
  const groups = groupJobs(jobs, JSON.parse(JSON.stringify(membership)))
  assert.deepEqual(groups.map(group => group.jobs.length), [4, 1])
  jobs[0].status = 'succeeded'
  jobs[1].status = 'failed'
  assert.deepEqual(groupJobs(jobs, membership).map(group => group.jobs.length), [4, 1])
  assert.equal(groupJobs(jobs, {}).length, 5)
  assert.deepEqual(groupJobs(jobs.slice(1), membership)[0].jobs.map(job => job.job_id), ['b', 'c', 'd'])
})
