/** Only explicit submission membership can merge jobs; identical prompts are separate runs. */
export function groupJobs<T extends { job_id: string }>(jobs: T[], membership: Record<string, string>) {
  const groups = new Map<string, { id: string; jobs: T[] }>()
  for (const job of jobs) {
    const id = membership[job.job_id] ? `batch:${membership[job.job_id]}` : `job:${job.job_id}`
    const group = groups.get(id)
    if (group) group.jobs.push(job)
    else groups.set(id, { id, jobs: [job] })
  }
  return [...groups.values()]
}
