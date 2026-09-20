import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  newProject,
  newNode,
  zoomAt,
  worldPoint,
  connect,
  generationInputs,
  removeNodes,
  validateProject,
  assetIds,
} from '../src/lib/canvas/model.ts'

test('zoom remains anchored to the pointer and is bounded', () => {
  const viewport = { x: -300, y: 90, scale: 0.5 },
    pointer = { x: 400, y: 250 }
  const before = worldPoint(pointer, viewport),
    after = zoomAt(viewport, pointer, 2)
  assert.deepEqual(worldPoint(pointer, after), before)
  assert.equal(zoomAt(viewport, pointer, 0).scale, 0.1)
  assert.equal(zoomAt(viewport, pointer, 100).scale, 3)
})

test('ordered references include groups and deduplicate repeated images', () => {
  const p = newProject('owner'),
    a = newNode('image', { x: 0, y: 0 }),
    b = newNode('image', { x: 0, y: 0 }),
    g = newNode('group', { x: 0, y: 0 }),
    t = newNode('text', { x: 0, y: 0 }),
    output = newNode('generation', { x: 0, y: 0 })
  a.assetId = 'a'.repeat(64)
  b.assetId = 'b'.repeat(64)
  b.groupId = g.id
  t.text = 'a prompt'
  p.nodes.push(a, b, g, t, output)
  connect(p, g.id, output.id)
  connect(p, a.id, output.id)
  connect(p, b.id, output.id)
  connect(p, t.id, output.id)
  assert.deepEqual(generationInputs(p, output.id), {
    assets: [b.assetId, a.assetId],
    text: 'a prompt',
  })
  assert.throws(() => connect(p, output.id, a.id))
  connect(p, g.id, output.id)
  assert.equal(p.edges.length, 4)
})

test('removing nodes leaves paid tasks intact and ungrouping preserves children', () => {
  const p = newProject('owner'),
    group = newNode('group', { x: 0, y: 0 }),
    image = newNode('image', { x: 0, y: 0 })
  image.groupId = group.id
  p.nodes = [group, image]
  p.runs = [
    {
      id: 'r1',
      nodeId: image.id,
      sourceId: 'gen',
      prompt: 'test',
      model: 'm',
      size: 'auto',
      referenceIds: [],
      uploadedIds: [],
      status: 'queued',
      jobId: 'job-1',
      assetId: 'a'.repeat(64),
    },
  ]
  removeNodes(p, [group.id])
  assert.equal(p.nodes.length, 1)
  assert.equal(p.nodes[0].groupId, undefined)
  removeNodes(p, [image.id])
  assert.equal(p.runs[0].jobId, 'job-1')
  assert.deepEqual(assetIds(p), ['a'.repeat(64)])
})

test('import validation rejects malformed nodes, links and task recovery data', () => {
  const p = newProject('old-owner')
  p.nodes.push(newNode('text', { x: 0, y: 0 }))
  assert.equal(validateProject(p, 'new-owner').ownerId, 'new-owner')
  assert.throws(() =>
    validateProject({ ...p, nodes: [...p.nodes, ...p.nodes] }, 'owner'),
  )
  assert.throws(() =>
    validateProject(
      { ...p, viewport: { x: 0, y: 0, scale: Infinity } },
      'owner',
    ),
  )
  assert.throws(() =>
    validateProject(
      { ...p, edges: [{ id: 'e1', from: 'unknown', to: p.nodes[0].id }] },
      'owner',
    ),
  )
  assert.throws(() =>
    validateProject({ ...p, runs: [{ id: 'r1', status: 'queued' }] }, 'owner'),
  )
  assert.throws(() =>
    validateProject(
      {
        ...p,
        nodes: [{ ...p.nodes[0], assetId: 'https://untrusted.invalid/x.png' }],
      },
      'owner',
    ),
  )
})
