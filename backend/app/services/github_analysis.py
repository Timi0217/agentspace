"""
GitHub Analysis - Port of vibechekk's code fetching and quality detection

This ports vibechekk's:
- fetchCodeQualitySignals (detect tests, CI, TypeScript, etc.)
- fetchSmartDiffs (extract code samples from commits)
- detectEducationalContent
"""

import requests
import base64
from typing import Dict, List, Optional
from app.core.logging import get_logger

logger = get_logger(__name__)


def fetch_code_quality_signals(github_token: str, owner: str, repo: str) -> Optional[Dict]:
    """
    Port of vibechekk's fetchCodeQualitySignals.

    Detects: tests, CI, TypeScript, linting, docs, file count.
    """
    try:
        headers = {'Authorization': f'token {github_token}'}

        # Get repo tree (all files)
        tree_url = f'https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1'
        tree_response = requests.get(tree_url, headers=headers, timeout=10)

        if not tree_response.ok:
            return None

        tree_data = tree_response.json()
        paths = [item['path'] for item in tree_data.get('tree', [])]

        # Check for README
        readme_preview = 'No README found'
        try:
            readme_url = f'https://api.github.com/repos/{owner}/{repo}/readme'
            readme_response = requests.get(readme_url, headers=headers, timeout=5)
            if readme_response.ok:
                readme_data = readme_response.json()
                content = base64.b64decode(readme_data['content']).decode('utf-8')
                readme_preview = content[:500]
        except:
            pass

        # Check for substantial docs (not just README)
        # PROFESSOR-worthy docs = dedicated docs/ folder with multiple files OR examples/tutorials
        docs_files = [p for p in paths if 'docs/' in p or 'documentation/' in p]
        examples_files = [p for p in paths if 'examples/' in p or 'tutorials/' in p or 'guides/' in p]
        has_substantial_docs = len(docs_files) >= 3 or len(examples_files) >= 2

        return {
            'hasTests': any('test' in p.lower() or 'spec' in p.lower() for p in paths),
            'hasDocs': has_substantial_docs,  # FIXED: Require substantial docs, not just README
            'hasCI': any('.github/workflows' in p or '.circleci' in p or 'travis.yml' in p for p in paths),
            'hasTypeScript': any(p.endswith('.ts') or p.endswith('.tsx') for p in paths),
            'hasLinting': any('eslint' in p or '.prettierrc' in p or 'tsconfig.json' in p for p in paths),
            'fileCount': len(tree_data.get('tree', [])),
            'complexity': 'high' if len(tree_data.get('tree', [])) > 100 else 'medium' if len(tree_data.get('tree', [])) > 30 else 'low',
            'readmePreview': readme_preview,
            'docsFileCount': len(docs_files),  # For debugging
            'examplesFileCount': len(examples_files)  # For debugging
        }
    except Exception as e:
        logger.error("Quality signals error for %s/%s: %s", owner, repo, e)
        return None


def fetch_smart_diffs(github_token: str, owner: str, repos: List[Dict]) -> str:
    """
    Port of vibechekk's fetchSmartDiffs.

    Extracts code samples from top commits in top repos.
    Returns combined code samples as a string.
    """
    headers = {'Authorization': f'token {github_token}'}
    all_diffs = []

    for repo in repos[:5]:  # Top 5 repos
        repo_name = repo.get('name')
        if not repo_name:
            continue

        try:
            # Get recent commits for this repo (per_page=100 for efficiency)
            commits_url = f'https://api.github.com/repos/{owner}/{repo_name}/commits?per_page=100'
            commits_response = requests.get(commits_url, headers=headers, timeout=10)

            if not commits_response.ok:
                logger.warning("Failed to fetch commits for %s/%s: %s", owner, repo_name, commits_response.status_code)
                continue

            commits = commits_response.json()

            # Get diffs for top 3 commits
            for commit in commits[:3]:
                try:
                    commit_url = commit['url']
                    commit_response = requests.get(commit_url, headers=headers, timeout=10)

                    if not commit_response.ok:
                        continue

                    commit_data = commit_response.json()
                    files = commit_data.get('files', [])

                    # Filter for code files
                    code_files = []
                    skip_patterns = [
                        'package-lock.json', 'yarn.lock', 'Cargo.lock', 'poetry.lock',
                        '.min.js', '.bundle.js', 'dist/', 'build/',
                        'node_modules/', '.git/', '__pycache__/'
                    ]
                    code_extensions = [
                        '.ts', '.tsx', '.js', '.jsx', '.py', '.rs', '.go',
                        '.java', '.cpp', '.c', '.rb', '.php', '.swift', '.kt'
                    ]

                    for f in files:
                        if not f.get('patch'):
                            continue
                        filename = f.get('filename', '')
                        if any(skip in filename for skip in skip_patterns):
                            continue
                        if any(filename.endswith(ext) for ext in code_extensions):
                            code_files.append(f)

                    # Extract code snippets
                    for f in code_files[:5]:  # Top 5 files per commit
                        patch = f.get('patch', '')

                        # Extract meaningful lines (not imports/whitespace)
                        meaningful_lines = []
                        for line in patch.split('\n'):
                            trimmed = line.strip()
                            if not trimmed or trimmed.startswith('@@'):
                                continue
                            if trimmed.startswith('import ') or trimmed.startswith('from '):
                                continue
                            if trimmed.startswith('//') or trimmed.startswith('#'):
                                continue
                            meaningful_lines.append(line)

                        if len(meaningful_lines) > 5:  # At least 5 meaningful lines
                            code_snippet = '\n'.join(meaningful_lines[:50])  # Max 50 lines per file
                            all_diffs.append(f"\n--- {repo_name}/{f.get('filename')} ---\n{code_snippet}")

                except Exception as e:
                    logger.debug("Error fetching commit: %s", e)
                    continue

        except Exception as e:
            logger.debug("Error for repo %s: %s", repo_name, e)
            continue

    combined = '\n'.join(all_diffs)

    # Truncate if too long (max 8000 chars for DeepSeek prompt)
    if len(combined) > 8000:
        combined = combined[:8000] + '\n\n[Truncated - showing first 8000 chars of code samples]'

    if not combined:
        logger.warning("No code samples found for %s across %d repos", owner, len(repos[:5]))
        return 'No code samples available'

    logger.info("Extracted %d code samples (%d chars) for %s", len(all_diffs), len(combined), owner)
    return combined


def detect_educational_content(repo: Dict) -> Dict:
    """
    Port of vibechekk's detectEducationalContent.

    Identifies tutorial/guide repos vs production code.
    """
    educational_keywords = [
        'tutorial', 'guide', 'learning', 'course', 'example', 'sample',
        'clone', 'implementation', 'algorithm', 'interview', 'leetcode',
        'bootcamp', 'practice', 'exercise', 'roadmap', 'notes', 'study',
        'primer', 'cheatsheet', 'reference', 'university', 'curriculum'
    ]

    production_exclusions = ['framework', 'library', 'engine', 'platform', 'api']

    name_and_desc = f"{repo.get('name', '')} {repo.get('description', '')}".lower()
    is_educational = any(kw in name_and_desc for kw in educational_keywords)
    has_production_signals = any(kw in name_and_desc for kw in production_exclusions)

    total_commits = repo.get('total_commits', 0)
    stars = repo.get('stars', 0)

    suspicious_ratio = (stars / total_commits) if total_commits > 0 else 0
    is_likely_curated = suspicious_ratio > 50
    has_readme_only = total_commits < 10

    return {
        'isEducational': is_educational and not has_production_signals,
        'isLikelyGuide': is_educational and (has_readme_only or is_likely_curated),
        'educationalSignalStrength': 'high' if is_educational else 'low',
        'starsPerCommit': suspicious_ratio
    }
