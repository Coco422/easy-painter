"""One maintained source for website, agent-readable docs and downloadable Skill."""
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Response
from app.services.agent_auth import origin_url, resource_url

content_router = APIRouter()
CONTENT = Path(__file__).resolve().parents[1] / 'agent_content'


def document(name: str, *, markdown: bool = False):
    text = (CONTENT / name).read_text().replace('{{ORIGIN}}', origin_url()).replace('{{MCP_URL}}', resource_url())
    return Response(text, media_type='text/markdown' if markdown else 'text/plain', headers={'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff'})


@content_router.get('/llms.txt')
def llms(): return document('llms.txt')


@content_router.get('/llms-full.txt')
def llms_full(): return document('llms-full.txt')


@content_router.get('/mcp/install.md')
def install(): return document('install.md', markdown=True)


@content_router.get('/mcp/skill/SKILL.md')
def skill(): return document('skill/SKILL.md', markdown=True)


@content_router.get('/mcp/easy-painter-skill.zip')
def skill_zip():
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('easy-painter/SKILL.md', (CONTENT / 'skill/SKILL.md').read_bytes())
    return Response(output.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="easy-painter-skill.zip"', 'Cache-Control': 'no-cache'})
