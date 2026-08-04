export interface ReleaseItem {
  type: string
  content: string
}

export interface ReleaseInfo {
  version: string
  date: string
  items: ReleaseItem[]
}

const STABLE_SEMVER_PATTERN = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/
const RELEASE_ITEM_PATTERN = /^\+\s+\[(.+?)\]\s+(.+)$/

export function parseReleaseItems(content: string): ReleaseItem[] {
  return content
    .split('\n')
    .map((line) => line.trim().match(RELEASE_ITEM_PATTERN))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => ({ type: match[1], content: match[2] }))
}

export function parseChangelog(content: string): ReleaseInfo[] {
  return content
    .split(/^## /m)
    .slice(1)
    .map((block) => {
      const [title = '', ...lines] = block.trim().split('\n')
      const [, version = title.trim(), date = ''] = title.match(/^(.+?)(?:\s+-\s+(.+))?$/) ?? []
      return {
        version: version.trim(),
        date: date.trim(),
        items: parseReleaseItems(lines.join('\n')),
      }
    })
    .filter((release) => release.items.length > 0)
}

export function isStableSemver(value: string): boolean {
  return STABLE_SEMVER_PATTERN.test(value.trim())
}

export function compareSemver(left: string, right: string): number {
  const parse = (value: string) => {
    const match = value.trim().match(/^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/)
    return match ? match.slice(1).map(Number) : null
  }
  const leftParts = parse(left)
  const rightParts = parse(right)
  if (!leftParts || !rightParts) return 0
  for (let index = 0; index < 3; index += 1) {
    const difference = (leftParts[index] ?? 0) - (rightParts[index] ?? 0)
    if (difference !== 0) return difference
  }
  return 0
}
